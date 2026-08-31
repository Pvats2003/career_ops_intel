"""Unit tests for `SheetsClient` against a mocked `googleapiclient` service."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from instacore_sync.core.config import SheetsSettings
from instacore_sync.services.sheets.sheets_client import SheetsClient


@pytest.fixture
def client() -> SheetsClient:
    settings = SheetsSettings(spreadsheet_id="sheet-123", worksheet_name="Uploads", header_row=1)
    c = SheetsClient(settings, credentials_provider=lambda: None)
    c._service = MagicMock()
    return c


def _values_get_mock(client: SheetsClient, values: list[list[str]]) -> None:
    client._service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": values
    }


def test_upsert_row_creates_new_row_when_filename_not_found(client: SheetsClient) -> None:
    _values_get_mock(client, values=[["existing.mp4"], ["other.mp4"]])

    result = client.upsert_row(
        date_label="31 Aug",
        device_id="IC-188",
        filename="new_video.mp4",
        drive_link="https://drive/1",
        status="completed",
        ocr_confidence=0.91,
    )

    assert result.created_new_row is True
    assert result.row_number == 4  # header_row(1) + 1 + 2 existing rows
    client._service.spreadsheets.return_value.values.return_value.batchUpdate.assert_called_once()
    # Only one lookup call for the whole cache-priming read, not a
    # per-filename `values.get`.
    client._service.spreadsheets.return_value.values.return_value.get.assert_called_once()


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


def test_row_cache_is_primed_once_and_reused_across_calls(client: SheetsClient) -> None:
    _values_get_mock(client, values=[["a.mp4"], ["b.mp4"]])

    client.upsert_row(
        date_label="31 Aug", device_id="IC-1", filename="c.mp4",
        drive_link="https://drive/c", status="completed", ocr_confidence=0.9,
    )
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
    client.upsert_row(
        date_label="31 Aug", device_id="IC-1", filename="b.mp4",
        drive_link="https://drive/b", status="completed", ocr_confidence=0.9,
    )
    assert client._service.spreadsheets.return_value.values.return_value.get.call_count == 1

    client.invalidate_cache()
    _values_get_mock(client, values=[["a.mp4"], ["b.mp4"], ["c.mp4"]])
    client.upsert_row(
        date_label="31 Aug", device_id="IC-2", filename="d.mp4",
        drive_link="https://drive/d", status="completed", ocr_confidence=0.9,
    )
    assert client._service.spreadsheets.return_value.values.return_value.get.call_count == 2
    assert client._row_cache["d.mp4"] == 5


def test_upsert_row_sanitizes_formula_injection_in_filename(client: SheetsClient) -> None:
    _values_get_mock(client, values=[])

    client.upsert_row(
        date_label="31 Aug",
        device_id="IC-188",
        filename='=HYPERLINK("http://evil.example","click")_IC-188.mp4',
        drive_link="https://drive/1",
        status="completed",
        ocr_confidence=0.9,
    )

    call = client._service.spreadsheets.return_value.values.return_value.batchUpdate.call_args
    data = call.kwargs["body"]["data"]
    filename_entry = next(entry for entry in data if entry["range"] == "Uploads!C2")
    written_value = filename_entry["values"][0][0]
    assert written_value.startswith("'=")  # forced to literal text, not a formula


def test_ensure_header_row_writes_expected_columns(client: SheetsClient) -> None:
    client.ensure_header_row()
    call = client._service.spreadsheets.return_value.values.return_value.batchUpdate.call_args
    data = call.kwargs["body"]["data"]
    ranges = {entry["range"] for entry in data}
    assert "Uploads!A1" in ranges  # date column
    assert "Uploads!B1" in ranges  # device_id column
