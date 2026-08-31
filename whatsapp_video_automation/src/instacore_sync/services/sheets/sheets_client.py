"""Google Sheets integration: find-or-create a row per uploaded video.

A row is identified by filename (unique per upload). If a row for the
filename already exists (e.g. a retry after the app crashed mid-run) it is
updated in place instead of appended, so re-processing never creates
duplicate rows.

Row lookups are served from an in-memory `filename -> row number` cache
built from a single read the first time it's needed, instead of one
`values.get` API call per upload — at 200-500 uploads/day that's the
difference between 200-500 lookup calls and effectively one. The cache is
process-lifetime (rebuilt fresh on every app restart) and assumes this
process is the sole writer to the sheet while it's running; call
`invalidate_cache()` (wired to a future "Resync Sheet" action) if the sheet
was edited by hand mid-session.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from instacore_sync.core.config import SheetsSettings
from instacore_sync.core.exceptions import SheetsApiError
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.domain.models import SheetUpdateResult
from instacore_sync.utils.retry import google_api_retry
from instacore_sync.utils.text_sanitize import sanitize_for_spreadsheet_cell

logger = get_logger(__name__)


class SheetsClient:
    def __init__(
        self,
        settings: SheetsSettings,
        credentials_provider: Callable[[], Credentials],
    ) -> None:
        self._settings = settings
        self._credentials_provider = credentials_provider
        self._service: Resource | None = None
        self._row_cache: dict[str, int] = {}
        self._next_row_number: int | None = None

    def _sheets(self) -> Resource:
        if self._service is None:
            self._service = build(
                "sheets", "v4", credentials=self._credentials_provider(), cache_discovery=False
            )
        return self._service

    def invalidate_cache(self) -> None:
        """Force the next lookup to re-read the sheet instead of trusting
        the in-memory row index — use after an out-of-band edit to the
        sheet (e.g. a human manually reordered/deleted rows)."""
        self._row_cache = {}
        self._next_row_number = None

    @google_api_retry()
    def upsert_row(
        self,
        *,
        date_label: str,
        device_id: str,
        filename: str,
        drive_link: str,
        status: str,
        ocr_confidence: float,
    ) -> SheetUpdateResult:
        cols = self._settings.columns
        sheet = self._settings.worksheet_name

        self._ensure_row_cache()
        existing_row = self._row_cache.get(filename)
        row_values = {
            cols.date: sanitize_for_spreadsheet_cell(date_label),
            cols.device_id: sanitize_for_spreadsheet_cell(device_id),
            cols.filename: sanitize_for_spreadsheet_cell(filename),
            cols.drive_link: drive_link,  # our own generated Drive URL — never attacker-controlled
            cols.status: status,
            cols.uploaded_at: datetime.now().isoformat(timespec="seconds"),
            cols.ocr_confidence: f"{ocr_confidence:.2f}",
        }

        try:
            if existing_row is not None:
                self._write_row(sheet, existing_row, row_values)
                return SheetUpdateResult(
                    spreadsheet_id=self._settings.spreadsheet_id,
                    row_number=existing_row,
                    created_new_row=False,
                )

            assert self._next_row_number is not None  # set by _ensure_row_cache
            next_row = self._next_row_number
            self._write_row(sheet, next_row, row_values)
            self._row_cache[filename] = next_row
            self._next_row_number += 1
            return SheetUpdateResult(
                spreadsheet_id=self._settings.spreadsheet_id,
                row_number=next_row,
                created_new_row=True,
            )
        except HttpError as exc:
            raise SheetsApiError(f"Failed to write sheet row for {filename}: {exc}") from exc

    def _ensure_row_cache(self) -> None:
        if self._next_row_number is not None:
            return  # already primed this session

        cols = self._settings.columns
        col = cols.filename
        range_ = f"{self._settings.worksheet_name}!{col}{self._settings.header_row + 1}:{col}"
        try:
            result = (
                self._sheets()
                .spreadsheets()
                .values()
                .get(spreadsheetId=self._settings.spreadsheet_id, range=range_)
                .execute()
            )
        except HttpError as exc:
            raise SheetsApiError(f"Failed to read sheet column {col}: {exc}") from exc

        values = result.get("values", [])
        for offset, row in enumerate(values):
            if row and row[0]:
                self._row_cache[row[0]] = self._settings.header_row + 1 + offset
        self._next_row_number = self._settings.header_row + 1 + len(values)
        logger.info("sheets.row_cache.primed", known_rows=len(self._row_cache))

    def _write_row(self, sheet: str, row_number: int, values_by_column: dict[str, str]) -> None:
        data = [
            {"range": f"{sheet}!{col}{row_number}", "values": [[value]]}
            for col, value in values_by_column.items()
        ]
        self._sheets().spreadsheets().values().batchUpdate(
            spreadsheetId=self._settings.spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute()

    @google_api_retry()
    def ensure_header_row(self) -> None:
        cols = self._settings.columns
        header_values = {
            cols.date: "Date",
            cols.device_id: "Device ID",
            cols.filename: "Filename",
            cols.drive_link: "Drive Link",
            cols.status: "Status",
            cols.uploaded_at: "Uploaded At",
            cols.ocr_confidence: "OCR Confidence",
        }
        try:
            self._write_row(self._settings.worksheet_name, self._settings.header_row, header_values)
        except HttpError as exc:
            raise SheetsApiError(f"Failed to write header row: {exc}") from exc
