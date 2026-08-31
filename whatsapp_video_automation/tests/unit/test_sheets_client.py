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


def test_next_empty_row_accounts_for_header_row(client: SheetsClient) -> None:
    _values_get_mock(client, values=[])
    assert client._next_empty_row() == 2  # header_row=1 -> data starts at row 2


def test_ensure_header_row_writes_expected_columns(client: SheetsClient) -> None:
    client.ensure_header_row()
    call = client._service.spreadsheets.return_value.values.return_value.batchUpdate.call_args
    data = call.kwargs["body"]["data"]
    ranges = {entry["range"] for entry in data}
    assert "Uploads!A1" in ranges  # date column
    assert "Uploads!B1" in ranges  # device_id column
