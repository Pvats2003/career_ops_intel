"""Unit tests for `SheetsClient` against a mocked `googleapiclient` service."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from instacore_sync.core.config import SheetsSettings
from instacore_sync.core.exceptions import SheetsApiError
from instacore_sync.services.sheets.sheets_client import SheetsClient


@pytest.fixture
def client() -> SheetsClient:
    settings = SheetsSettings(spreadsheet_id="sheet-123", worksheet_name="Uploads", header_row=1)
    c = SheetsClient(settings, credentials_provider=lambda: None)
    c._service = MagicMock()
    return c


class _FakeSharedSpreadsheet:
    """Stands in for the real Sheets backend's `values.append` server-side
    row assignment: a lock-protected row counter that hands out a distinct,
    strictly increasing row number per call, no matter how many independent
    `SheetsClient` instances (simulating independent app processes, each
    with its own empty in-memory cache — exactly the shared-destination
    deployment) call it concurrently. If `SheetsClient` ever regresses to
    computing "next row" from its own local view instead of trusting what
    this returns, two clients racing here would compute the same row and
    this fake would not be what catches it — but the row list below would:
    every appended row is distinct and none is silently overwritten.
    """

    def __init__(self, header_row: int) -> None:
        self._lock = threading.Lock()
        self._next_row = header_row + 1
        self.rows: dict[int, list[str]] = {}

    def append(self, row: list[str]) -> int:
        with self._lock:
            row_number = self._next_row
            self._next_row += 1
        self.rows[row_number] = row
        return row_number


def _wire_fake_shared_backend(client: SheetsClient, backend: _FakeSharedSpreadsheet) -> None:
    """Point a `SheetsClient`'s mocked service at a shared fake backend so
    multiple `SheetsClient` instances can be driven concurrently against
    the *same* simulated spreadsheet state, mirroring 500 independent app
    processes writing into one real Google Sheet."""
    client._service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": []
    }

    def _append_side_effect(**kwargs):
        # Captured fresh per call (own local `row`, own local closure) so
        # concurrent calls on the same mock from different threads can
        # never see each other's row — unlike stashing kwargs on the mock's
        # shared `call_args` and reading it back later from `.execute()`.
        row = kwargs["body"]["values"][0]

        def _execute():
            row_number = backend.append(row)
            return {"updates": {"updatedRange": f"Uploads!A{row_number}:G{row_number}"}}

        request = MagicMock()
        request.execute.side_effect = _execute
        return request

    client._service.spreadsheets.return_value.values.return_value.append.side_effect = _append_side_effect


def _values_get_mock(client: SheetsClient, values: list[list[str]]) -> None:
    client._service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": values
    }


def _values_append_mock(client: SheetsClient, updated_range: str) -> None:
    client._service.spreadsheets.return_value.values.return_value.append.return_value.execute.return_value = {
        "updates": {"updatedRange": updated_range}
    }


def test_upsert_row_creates_new_row_using_atomic_append(client: SheetsClient) -> None:
    """New rows must go through values.append (Sheets picks the row
    server-side) rather than a client-computed row number — see
    sheets_client.py's module docstring for why: a client-computed "next
    row" races when this sheet is a shared destination many independent
    app instances write to concurrently, since each computes its own view
    of "next" and a second write can clobber the first's row."""
    _values_get_mock(client, values=[["existing.mp4"], ["other.mp4"]])
    _values_append_mock(client, updated_range="Uploads!A4:G4")

    result = client.upsert_row(
        date_label="31 Aug",
        device_id="IC-188",
        filename="new_video.mp4",
        drive_link="https://drive/1",
        status="completed",
        ocr_confidence=0.91,
    )

    assert result.created_new_row is True
    assert result.row_number == 4  # taken from Sheets' own response, not computed locally
    client._service.spreadsheets.return_value.values.return_value.append.assert_called_once()
    append_kwargs = client._service.spreadsheets.return_value.values.return_value.append.call_args.kwargs
    assert append_kwargs["insertDataOption"] == "INSERT_ROWS"
    assert append_kwargs["valueInputOption"] == "USER_ENTERED"
    # batchUpdate (the in-place-update path) must NOT be used for a new row.
    client._service.spreadsheets.return_value.values.return_value.batchUpdate.assert_not_called()
    # Only one lookup call for the whole cache-priming read, not a
    # per-filename `values.get`.
    client._service.spreadsheets.return_value.values.return_value.get.assert_called_once()


def test_append_row_builds_contiguous_row_with_gaps_for_unmapped_columns(client: SheetsClient) -> None:
    _values_get_mock(client, values=[])
    _values_append_mock(client, updated_range="Uploads!A2:G2")

    client.upsert_row(
        date_label="31 Aug",
        device_id="IC-188",
        filename="clip.mp4",
        drive_link="https://drive/1",
        status="completed",
        ocr_confidence=0.91,
    )

    append_kwargs = client._service.spreadsheets.return_value.values.return_value.append.call_args.kwargs
    row = append_kwargs["body"]["values"][0]
    assert len(row) == 7  # columns A..G, default mapping
    assert row[0] == "31 Aug"  # column A: date
    assert row[1] == "IC-188"  # column B: device_id
    assert row[2] == "clip.mp4"  # column C: filename


def test_append_row_raises_when_updated_range_is_unparseable(client: SheetsClient) -> None:
    _values_get_mock(client, values=[])
    _values_append_mock(client, updated_range="")

    with pytest.raises(SheetsApiError):
        client.upsert_row(
            date_label="31 Aug",
            device_id="IC-188",
            filename="clip.mp4",
            drive_link="https://drive/1",
            status="completed",
            ocr_confidence=0.91,
        )


def test_upsert_row_updates_existing_row_in_place(client: SheetsClient) -> None:
    _values_get_mock(client, values=[["video_a.mp4"], ["target.mp4"], ["video_c.mp4"]])

    result = client.upsert_row(
        date_label="31 Aug",
        device_id="IC-551",
        filename="target.mp4",
        drive_link="https://drive/2",
        status="completed",
        ocr_confidence=0.88,
    )

    assert result.created_new_row is False
    assert result.row_number == 3  # header_row(1) + 1 + offset(1, zero-indexed second row)
    client._service.spreadsheets.return_value.values.return_value.append.assert_not_called()


def test_row_cache_is_primed_once_and_reused_across_calls(client: SheetsClient) -> None:
    _values_get_mock(client, values=[["a.mp4"], ["b.mp4"]])
    _values_append_mock(client, updated_range="Uploads!A4:G4")

    client.upsert_row(
        date_label="31 Aug", device_id="IC-1", filename="c.mp4",
        drive_link="https://drive/c", status="completed", ocr_confidence=0.9,
    )
    _values_append_mock(client, updated_range="Uploads!A5:G5")
    client.upsert_row(
        date_label="31 Aug", device_id="IC-2", filename="d.mp4",
        drive_link="https://drive/d", status="completed", ocr_confidence=0.9,
    )

    # Two new rows appended (c.mp4 then d.mp4) without a second lookup call —
    # this is the "cache row indexes" optimization: only the very first
    # upsert in the session pays for a `values.get`.
    assert client._service.spreadsheets.return_value.values.return_value.get.call_count == 1
    assert client._row_cache["c.mp4"] == 4
    assert client._row_cache["d.mp4"] == 5


def test_invalidate_cache_forces_a_fresh_lookup(client: SheetsClient) -> None:
    _values_get_mock(client, values=[["a.mp4"]])
    _values_append_mock(client, updated_range="Uploads!A3:G3")
    client.upsert_row(
        date_label="31 Aug", device_id="IC-1", filename="b.mp4",
        drive_link="https://drive/b", status="completed", ocr_confidence=0.9,
    )
    assert client._service.spreadsheets.return_value.values.return_value.get.call_count == 1

    client.invalidate_cache()
    _values_get_mock(client, values=[["a.mp4"], ["b.mp4"], ["c.mp4"]])
    _values_append_mock(client, updated_range="Uploads!A5:G5")
    client.upsert_row(
        date_label="31 Aug", device_id="IC-2", filename="d.mp4",
        drive_link="https://drive/d", status="completed", ocr_confidence=0.9,
    )
    assert client._service.spreadsheets.return_value.values.return_value.get.call_count == 2
    assert client._row_cache["d.mp4"] == 5


def test_upsert_row_sanitizes_formula_injection_in_filename(client: SheetsClient) -> None:
    _values_get_mock(client, values=[])
    _values_append_mock(client, updated_range="Uploads!A2:G2")

    client.upsert_row(
        date_label="31 Aug",
        device_id="IC-188",
        filename='=HYPERLINK("http://evil.example","click")_IC-188.mp4',
        drive_link="https://drive/1",
        status="completed",
        ocr_confidence=0.9,
    )

    append_kwargs = client._service.spreadsheets.return_value.values.return_value.append.call_args.kwargs
    row = append_kwargs["body"]["values"][0]
    filename_value = row[2]  # column C
    assert filename_value.startswith("'=")  # forced to literal text, not a formula


def test_ensure_header_row_writes_expected_columns(client: SheetsClient) -> None:
    client.ensure_header_row()
    call = client._service.spreadsheets.return_value.values.return_value.batchUpdate.call_args
    data = call.kwargs["body"]["data"]
    ranges = {entry["range"] for entry in data}
    assert "Uploads!A1" in ranges  # date column
    assert "Uploads!B1" in ranges  # device_id column


def test_concurrent_new_rows_from_independent_clients_never_collide() -> None:
    """The scenario this whole redesign targets: many independent app
    processes (500 team members, each running their own copy) writing new
    rows into the *same* shared Google Sheet around the same moment. Each
    `SheetsClient` here stands in for one such process — its own instance,
    its own empty row cache, no shared Python state between them — driven
    concurrently against one shared fake backend that mimics Sheets'
    server-side row assignment. If new-row placement were still computed
    client-side, two clients would be liable to compute the same "next
    row" and one would silently overwrite the other's entry; every row
    below must be distinct and every filename must be recoverable.
    """
    settings = SheetsSettings(spreadsheet_id="shared-sheet", worksheet_name="Uploads", header_row=1)
    backend = _FakeSharedSpreadsheet(header_row=1)

    clients = []
    for _ in range(20):
        c = SheetsClient(settings, credentials_provider=lambda: None)
        c._service = MagicMock()
        _wire_fake_shared_backend(c, backend)
        clients.append(c)

    def _upsert(index: int) -> int:
        result = clients[index].upsert_row(
            date_label="1 Sep",
            device_id="IC-1",
            filename=f"video_{index}.mp4",
            drive_link=f"https://drive/{index}",
            status="completed",
            ocr_confidence=0.9,
        )
        return result.row_number

    with ThreadPoolExecutor(max_workers=20) as pool:
        row_numbers = list(pool.map(_upsert, range(20)))

    assert len(set(row_numbers)) == 20, "two independent processes were assigned the same row"
    assert len(backend.rows) == 20, "a row was silently overwritten by a concurrent writer"
    recovered_filenames = {row[2] for row in backend.rows.values()}  # column C
    assert recovered_filenames == {f"video_{i}.mp4" for i in range(20)}
