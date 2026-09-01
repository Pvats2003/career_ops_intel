"""Google Sheets integration: find-or-create a row per uploaded video.

A row is identified by filename (unique per upload). If a row for the
filename already exists (e.g. a retry after the app crashed mid-run) it is
updated in place instead of appended, so re-processing never creates
duplicate rows.

Row lookups are served from an in-memory `filename -> row number` cache
built from a single read the first time it's needed, instead of one
`values.get` API call per upload — at 200-500 uploads/day that's the
difference between 200-500 lookup calls and effectively one. The cache is
process-lifetime (rebuilt fresh on every app restart) and reflects only
what *this* process has seen; call `invalidate_cache()` (wired to a future
"Resync Sheet" action) if the sheet was edited by hand mid-session.

New-row placement deliberately does **not** use a client-computed "next
empty row" — see `_append_row` for why: when this same spreadsheet is a
shared destination for many independent app instances (e.g. every member
of a team, each running their own copy against the same tracking sheet),
two processes computing "next row" from their own local view can compute
the *same* row number and one silently overwrites the other's log entry.
`values.append` delegates that decision to Sheets itself, which serializes
it server-side — the one part of this class that must be safe under
concurrent writers from other processes, not just other threads in this
one.
"""

from __future__ import annotations

import re
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

# Matches the row number out of a values.append response's updatedRange,
# e.g. "Uploads!A5:G5" or "'My Sheet'!A5:G5" -> "5".
_ROW_FROM_RANGE_RE = re.compile(r"![A-Z]+(\d+)")


def _column_letter_to_index(letter: str) -> int:
    """'A' -> 0, 'B' -> 1, ..., 'Z' -> 25, 'AA' -> 26, ..."""
    index = 0
    for ch in letter.strip().upper():
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


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
        self._cache_primed = False

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
        self._cache_primed = False

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

            row_number = self._append_row(sheet, row_values)
            self._row_cache[filename] = row_number
            return SheetUpdateResult(
                spreadsheet_id=self._settings.spreadsheet_id,
                row_number=row_number,
                created_new_row=True,
            )
        except HttpError as exc:
            raise SheetsApiError(f"Failed to write sheet row for {filename}: {exc}") from exc

    def _ensure_row_cache(self) -> None:
        if self._cache_primed:
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
        self._cache_primed = True
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

    def _append_row(self, sheet: str, values_by_column: dict[str, str]) -> int:
        """Atomically place a brand-new row via Sheets' native append.

        `values.append` finds "the next row after the table" and writes
        there *as a single operation Sheets itself serializes* — unlike our
        old approach of reading the sheet once, computing "next row = N"
        locally, and writing to row N, which is safe for a single process
        but not for many independent processes sharing one destination
        sheet (a shared team tracker, for instance): two processes could
        both compute N, and the second write would silently clobber the
        first's row instead of landing on N+1. Handing row placement to
        Sheets itself removes that race entirely, at the cost of needing to
        parse the row Sheets actually chose out of its response instead of
        knowing it upfront.

        The row is built as one contiguous array from column A through the
        rightmost configured column (arbitrary/gapped/reordered column
        mapping is user-configurable via Settings -> Google Sheets), with
        unmapped columns left as empty strings — `values.append` writes a
        whole row per call, it can't target the same scattered per-column
        ranges `_write_row`'s batchUpdate uses for in-place updates.
        """
        width = max(_column_letter_to_index(col) for col in values_by_column) + 1
        row = [""] * width
        for col, value in values_by_column.items():
            row[_column_letter_to_index(col)] = value

        range_ = f"{sheet}!A{self._settings.header_row + 1}"
        response = (
            self._sheets()
            .spreadsheets()
            .values()
            .append(
                spreadsheetId=self._settings.spreadsheet_id,
                range=range_,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            )
            .execute()
        )
        updated_range = response.get("updates", {}).get("updatedRange", "")
        match = _ROW_FROM_RANGE_RE.search(updated_range)
        if not match:
            raise SheetsApiError(
                f"Could not determine which row Sheets appended to (updatedRange={updated_range!r})"
            )
        return int(match.group(1))

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
