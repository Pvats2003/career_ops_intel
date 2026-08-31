"""Unit tests for `DriveClient` against a mocked `googleapiclient` service —
no network access or real Google credentials required. We inject the fake
service directly via the private `_service` attribute to skip OAuth
entirely, which is the intended seam for testing this class."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from instacore_sync.core.config import DriveSettings
from instacore_sync.services.drive.drive_client import DriveClient


class _FakeFolderCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, folder_id: str, parent_folder_id=None) -> None:
        self._store[key] = folder_id

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


def _http_error(status: int) -> HttpError:
    resp = MagicMock()
    resp.status = status
    return HttpError(resp, json.dumps({"error": {"errors": [{"reason": "notFound"}]}}).encode())


@pytest.fixture
def client() -> DriveClient:
    settings = DriveSettings(root_folder_id="root-123", make_public_link=True)
    c = DriveClient(settings, _FakeFolderCache(), credentials_provider=lambda: None)
    c._service = MagicMock()
    return c


def test_find_or_create_folder_reuses_existing(client: DriveClient) -> None:
    client._service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "existing-folder-id", "name": "31 Aug"}]
    }

    folder_id = client._find_or_create_folder("31 Aug", "root-123")

    assert folder_id == "existing-folder-id"
    client._service.files.return_value.create.assert_not_called()


def test_find_or_create_folder_creates_when_missing(client: DriveClient) -> None:
    client._service.files.return_value.list.return_value.execute.return_value = {"files": []}
    client._service.files.return_value.create.return_value.execute.return_value = {"id": "new-folder-id"}

    folder_id = client._find_or_create_folder("IC-188", "date-folder-id")

    assert folder_id == "new-folder-id"
    client._service.files.return_value.create.assert_called_once()


def test_get_or_create_date_folder_uses_cache(client: DriveClient) -> None:
    client._folder_cache.set("31 Aug", "cached-id")
    folder_id = client.get_or_create_date_folder("31 Aug")
    assert folder_id == "cached-id"
    client._service.files.return_value.list.assert_not_called()


def test_get_or_create_date_folder_evicts_stale_cache_entry_on_404(client: DriveClient) -> None:
    """Regression test: a cached folder id that Drive now reports as
    missing (someone renamed/deleted/moved it out from under the app) must
    not keep failing every upload for the rest of the day — it should be
    evicted and re-resolved once, transparently."""
    client._folder_cache.set("31 Aug", "stale-id")
    client._service.files.return_value.get.return_value.execute.side_effect = _http_error(404)
    client._service.files.return_value.list.return_value.execute.return_value = {"files": []}
    client._service.files.return_value.create.return_value.execute.return_value = {"id": "fresh-id"}

    folder_id = client.get_or_create_date_folder("31 Aug")

    assert folder_id == "fresh-id"
    assert client._folder_cache.get("31 Aug") == "fresh-id"


def test_cached_folder_existence_check_is_not_fooled_by_transient_errors(client: DriveClient) -> None:
    """A network blip or transient 500 while checking cache validity must
    not evict a perfectly good cache entry — only a definitive 404 should."""
    client._folder_cache.set("31 Aug", "cached-id")
    client._service.files.return_value.get.return_value.execute.side_effect = _http_error(500)

    folder_id = client.get_or_create_date_folder("31 Aug")

    assert folder_id == "cached-id"
    client._service.files.return_value.list.assert_not_called()


def test_upload_file_returns_link_and_sets_permission(client: DriveClient, tmp_path: Path) -> None:
    video = tmp_path / "IC-188.mp4"
    video.write_bytes(b"x" * 1024)

    fake_request = MagicMock()
    fake_request.next_chunk.return_value = (None, {"id": "file-1", "webViewLink": "https://drive/file-1"})
    client._service.files.return_value.create.return_value = fake_request

    progress_events: list[tuple[int, int]] = []
    result = client.upload_file(
        video, "folder-1", chunk_size_mb=1, progress_callback=lambda u, t: progress_events.append((u, t))
    )

    assert result.file_id == "file-1"
    assert result.web_view_link == "https://drive/file-1"
    client._service.permissions.return_value.create.assert_called_once()
    assert progress_events[-1] == (1024, 1024)


def test_upload_file_skips_permission_when_disabled(tmp_path: Path) -> None:
    settings = DriveSettings(root_folder_id="root", make_public_link=False)
    client = DriveClient(settings, _FakeFolderCache(), credentials_provider=lambda: None)
    client._service = MagicMock()

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")
    fake_request = MagicMock()
    fake_request.next_chunk.return_value = (None, {"id": "file-2", "webViewLink": "https://drive/file-2"})
    client._service.files.return_value.create.return_value = fake_request

    client.upload_file(video, "folder-1")

    client._service.permissions.return_value.create.assert_not_called()


def test_build_view_link_format() -> None:
    assert DriveClient.build_view_link("abc123") == "https://drive.google.com/file/d/abc123/view?usp=drivesdk"
