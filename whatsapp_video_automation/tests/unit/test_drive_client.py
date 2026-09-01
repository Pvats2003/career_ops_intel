"""Unit tests for `DriveClient` against a mocked `googleapiclient` service —
no network access or real Google credentials required. We inject the fake
service directly via the private `_service` attribute to skip OAuth
entirely, which is the intended seam for testing this class."""

from __future__ import annotations

import itertools
import json
import threading
from concurrent.futures import ThreadPoolExecutor
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


def test_find_duplicate_by_hash_finds_a_match(client: DriveClient) -> None:
    sha = "a" * 64
    client._service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "existing-file", "name": "someone_elses_upload.mp4", "webViewLink": "https://drive/x"}]
    }

    match = client.find_duplicate_by_hash(sha)

    assert match is not None
    assert match.file_id == "existing-file"
    assert match.web_view_link == "https://drive/x"
    call = client._service.files.return_value.list.call_args
    assert sha in call.kwargs["q"]
    assert "properties has" in call.kwargs["q"]


def test_find_duplicate_by_hash_returns_none_when_no_match(client: DriveClient) -> None:
    client._service.files.return_value.list.return_value.execute.return_value = {"files": []}
    assert client.find_duplicate_by_hash("b" * 64) is None


def test_find_duplicate_by_hash_rejects_non_hex_input(client: DriveClient) -> None:
    """Defense in depth: this value is interpolated into a Drive `q=`
    query string, so it must be validated as a plain SHA-256 hex digest
    before ever reaching query construction — same discipline as the rest
    of this codebase applies to any value that reaches a Drive/Sheets API
    call built from a filename or other loosely-trusted input."""
    with pytest.raises(ValueError):
        client.find_duplicate_by_hash("'; DROP everything --")


def test_upload_file_tags_the_file_with_its_sha256_property(client: DriveClient, tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 10)
    fake_request = MagicMock()
    fake_request.next_chunk.return_value = (None, {"id": "file-9", "webViewLink": "https://drive/file-9"})
    client._service.files.return_value.create.return_value = fake_request

    client.upload_file(video, "folder-1", sha256="c" * 64)

    create_kwargs = client._service.files.return_value.create.call_args.kwargs
    assert create_kwargs["body"]["properties"] == {"sha256": "c" * 64}


def test_upload_file_without_hash_sets_no_properties(client: DriveClient, tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 10)
    fake_request = MagicMock()
    fake_request.next_chunk.return_value = (None, {"id": "file-9", "webViewLink": "https://drive/file-9"})
    client._service.files.return_value.create.return_value = fake_request

    client.upload_file(video, "folder-1")

    create_kwargs = client._service.files.return_value.create.call_args.kwargs
    assert "properties" not in create_kwargs["body"]


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


def test_find_or_create_folder_retries_a_transient_error_end_to_end(client: DriveClient) -> None:
    """End-to-end regression test for the google_api_retry predicate fix:
    _find_or_create_folder catches HttpError and re-raises DriveApiError
    (so callers get a typed exception), which used to defeat
    @google_api_retry() entirely — every transient failure looked
    permanent to tenacity because it only ever saw the wrapper. A single
    transient 500 here must be absorbed by a second attempt, not surfaced
    to the caller."""
    client._service.files.return_value.list.return_value.execute.side_effect = [
        _http_error(500),
        {"files": []},
        {"files": []},  # post-create reconciliation re-list
    ]
    client._service.files.return_value.create.return_value.execute.return_value = {"id": "new-folder-id"}

    folder_id = client._find_or_create_folder("IC-188", "date-folder-id")

    assert folder_id == "new-folder-id"
    assert client._service.files.return_value.list.return_value.execute.call_count == 3


# -- multi-writer folder-race reconciliation --------------------------------------


def test_find_or_create_folder_resolves_pre_existing_duplicates_deterministically(client: DriveClient) -> None:
    """Two folders with the same name/parent already exist (a race already
    happened, e.g. before this app version's reconciliation logic
    existed). Must deterministically settle on the older one and clean up
    the newer, empty duplicate rather than either creating a third or
    picking arbitrarily (which would make different processes disagree)."""
    client._service.files.return_value.list.return_value.execute.side_effect = [
        {"files": [
            {"id": "newer-dup", "name": "IC-188", "createdTime": "2026-01-01T10:00:05Z"},
            {"id": "older-original", "name": "IC-188", "createdTime": "2026-01-01T10:00:00Z"},
        ]},
        {"files": []},  # children-of-newer-dup check: empty, safe to trash
    ]

    folder_id = client._find_or_create_folder("IC-188", "date-folder-id")

    assert folder_id == "older-original"
    client._service.files.return_value.create.assert_not_called()
    client._service.files.return_value.update.assert_called_once_with(
        fileId="newer-dup", body={"trashed": True}, supportsAllDrives=True
    )


def test_find_or_create_folder_reconciles_race_detected_after_own_create(client: DriveClient) -> None:
    """This call sees no folder, creates one — but a concurrent process
    beat it to the same name/parent in the meantime. The post-create
    re-list surfaces both; since the other process's folder is older, this
    call must adopt it and trash the one it just created (safe: nothing
    has been uploaded into it yet)."""
    client._service.files.return_value.list.return_value.execute.side_effect = [
        {"files": []},  # initial check: nothing exists yet
        {"files": [  # re-list after our own create() below
            {"id": "ours-just-created", "name": "IC-188", "createdTime": "2026-01-01T10:00:05Z"},
            {"id": "theirs-won-the-race", "name": "IC-188", "createdTime": "2026-01-01T10:00:01Z"},
        ]},
        {"files": []},  # children-of-ours-just-created check: empty
    ]
    client._service.files.return_value.create.return_value.execute.return_value = {"id": "ours-just-created"}

    folder_id = client._find_or_create_folder("IC-188", "date-folder-id")

    assert folder_id == "theirs-won-the-race"
    client._service.files.return_value.update.assert_called_once_with(
        fileId="ours-just-created", body={"trashed": True}, supportsAllDrives=True
    )


def test_duplicate_folder_with_children_is_never_trashed(client: DriveClient) -> None:
    """Defense in depth: even though only just-created (empty) folders are
    ever supposed to reach the trash path, a non-empty loser must still be
    left alone rather than risking someone's uploaded video."""
    client._service.files.return_value.list.return_value.execute.side_effect = [
        {"files": [
            {"id": "newer-dup-with-files", "name": "IC-188", "createdTime": "2026-01-01T10:00:05Z"},
            {"id": "older-original", "name": "IC-188", "createdTime": "2026-01-01T10:00:00Z"},
        ]},
        {"files": [{"id": "some-video.mp4"}]},  # children check: NOT empty
    ]

    folder_id = client._find_or_create_folder("IC-188", "date-folder-id")

    assert folder_id == "older-original"
    client._service.files.return_value.update.assert_not_called()


class _FakeSharedDrive:
    """Stands in for Drive's actual folder-creation semantics closely
    enough to exercise real reconciliation under real concurrency: `list`
    and `create` are lock-protected so they behave like independent
    processes hitting the same real API, `create` never deduplicates on
    its own (mirroring that Drive truly does allow two folders with an
    identical name/parent), and `createdTime` reflects true creation
    order so the reconciliation tie-break is meaningful.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        self.folders: dict[str, dict] = {}

    def list_by_name(self, name: str, parent_id: str) -> list[dict]:
        with self._lock:
            return [
                {"id": fid, "name": f["name"], "createdTime": f["createdTime"]}
                for fid, f in self.folders.items()
                if f["name"] == name and f["parent"] == parent_id and not f["trashed"]
            ]

    def create(self, name: str, parent_id: str) -> str:
        with self._lock:
            n = next(self._counter)
            folder_id = f"folder-{n}"
            self.folders[folder_id] = {
                "name": name,
                "parent": parent_id,
                "createdTime": f"{n:010d}",  # monotonic w/ true creation order
                "trashed": False,
            }
            return folder_id

    def trash(self, folder_id: str) -> None:
        with self._lock:
            self.folders[folder_id]["trashed"] = True

    def live_folders_named(self, name: str, parent_id: str) -> list[str]:
        with self._lock:
            return [
                fid
                for fid, f in self.folders.items()
                if f["name"] == name and f["parent"] == parent_id and not f["trashed"]
            ]


def _wire_fake_shared_drive(client: DriveClient, backend: _FakeSharedDrive, parent_id: str, folder_name: str) -> None:
    service = client._service

    def _list_side_effect(**kwargs):
        q = kwargs.get("q", "")
        request = MagicMock()
        if "name = '" in q:  # the name+parent folder lookup in _list_folders_by_name
            files = backend.list_by_name(folder_name, parent_id)
            request.execute.side_effect = lambda: {"files": files}
        else:  # a duplicate-cleanup children-of-folder check — nothing was ever uploaded
            request.execute.side_effect = lambda: {"files": []}
        return request

    def _create_side_effect(**kwargs):
        body = kwargs["body"]
        new_id = backend.create(body["name"], body["parents"][0])
        request = MagicMock()
        request.execute.side_effect = lambda: {"id": new_id}
        return request

    def _update_side_effect(**kwargs):
        if kwargs.get("body", {}).get("trashed"):
            backend.trash(kwargs["fileId"])
        request = MagicMock()
        request.execute.side_effect = lambda: {}
        return request

    service.files.return_value.list.side_effect = _list_side_effect
    service.files.return_value.create.side_effect = _create_side_effect
    service.files.return_value.update.side_effect = _update_side_effect


def test_concurrent_folder_creation_from_independent_clients_converges_to_one_folder() -> None:
    """The scenario this reconciliation logic exists for: many independent
    app processes (every team member's own copy, 500-strong) all racing to
    get-or-create the *same* "today/IC-188" folder around the same moment
    a device's first video of the day arrives. Real Drive has no atomic
    check-then-create, so without reconciliation this would scatter that
    IC's videos across as many duplicate folders as there were racing
    processes. Every independent client here must end up agreeing on
    exactly one folder id, and Drive itself must be left with exactly one
    live (non-trashed) folder of that name."""
    settings = DriveSettings(root_folder_id="root-123", make_public_link=False)
    backend = _FakeSharedDrive()
    parent_id = "date-folder-id"
    folder_name = "IC-188"

    clients = [DriveClient(settings, _FakeFolderCache(), credentials_provider=lambda: None) for _ in range(15)]

    def _get_or_create(index: int) -> str:
        # `_service` is thread-local (each real worker thread gets its own
        # googleapiclient Resource — see DriveClient._drive), so the mock
        # must be wired up from the same thread that then uses it, not from
        # the main thread that constructed the client.
        client = clients[index]
        client._service = MagicMock()
        _wire_fake_shared_drive(client, backend, parent_id, folder_name)
        return client._find_or_create_folder(folder_name, parent_id)

    with ThreadPoolExecutor(max_workers=15) as pool:
        resolved_ids = list(pool.map(_get_or_create, range(15)))

    assert len(set(resolved_ids)) == 1, f"clients disagreed on the canonical folder: {set(resolved_ids)}"
    assert backend.live_folders_named(folder_name, parent_id) == list(set(resolved_ids))


def test_drive_resource_is_thread_local_not_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    """`googleapiclient`'s Resource is backed by an httplib2.Http instance,
    which is not thread-safe. One DriveClient is shared across every upload
    worker thread, so `_drive()` must hand each thread its own Resource
    instead of racing many threads over one shared object — regression
    test for that fix."""
    built_count = 0

    def _fake_build(*_args, **_kwargs):
        nonlocal built_count
        built_count += 1
        return MagicMock()

    monkeypatch.setattr("instacore_sync.services.drive.drive_client.build", _fake_build)

    settings = DriveSettings(root_folder_id="root-123")
    client = DriveClient(settings, _FakeFolderCache(), credentials_provider=lambda: None)

    seen_ids: set[int] = set()

    def _use_from_thread() -> None:
        seen_ids.add(id(client._drive()))
        # Calling again from the same thread must reuse that thread's
        # Resource, not build a fresh one every time.
        seen_ids.add(id(client._drive()))

    threads = [threading.Thread(target=_use_from_thread) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert built_count == 8, "expected exactly one Resource built per thread, not shared/rebuilt"
    assert len(seen_ids) == 8, "each thread must see its own distinct Resource object"
