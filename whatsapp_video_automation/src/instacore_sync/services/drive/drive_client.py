"""Google Drive integration: folder discovery/creation, resumable upload, sharing.

Supports both a normal "My Drive" folder tree and a Shared Drive (set
`shared_drive_id` in settings) by passing `supportsAllDrives=True` and
`includeItemsFromAllDrives=True` on every call, and `corpora="drive"` +
`driveId=...` on list calls when a shared drive is configured.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from instacore_sync.core.config import DriveSettings
from instacore_sync.core.constants import DRIVE_CHUNK_ALIGNMENT_BYTES
from instacore_sync.core.exceptions import DriveApiError
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.db.repositories.settings_repository import DriveFolderCacheRepository
from instacore_sync.domain.models import DriveHashMatch, UploadResult
from instacore_sync.utils.google_api_errors import is_not_found_error
from instacore_sync.utils.retry import google_api_retry

logger = get_logger(__name__)

_FOLDER_MIME = "application/vnd.google-apps.folder"
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

ProgressCallback = Callable[[int, int], None]  # (bytes_uploaded, total_bytes)


class DriveClient:
    def __init__(
        self,
        settings: DriveSettings,
        folder_cache: DriveFolderCacheRepository,
        credentials_provider: Callable[[], Credentials],
    ) -> None:
        self._settings = settings
        self._folder_cache = folder_cache
        self._credentials_provider = credentials_provider
        self._service: Resource | None = None

    def _drive(self) -> Resource:
        if self._service is None:
            self._service = build(
                "drive", "v3", credentials=self._credentials_provider(), cache_discovery=False
            )
        return self._service

    # -- Health check -----------------------------------------------------------

    @google_api_retry()
    def verify_root_folder_accessible(self, folder_id: str) -> str:
        """Read-only check for the Health Check page: does the configured
        root folder exist and can this account see it? Returns the
        folder's name on success. Deliberately a plain metadata `get`
        (never creates/lists anything) so running a health check has no
        side effects."""
        try:
            response = (
                self._drive()
                .files()
                .get(fileId=folder_id, fields="id, name, mimeType", supportsAllDrives=True)
                .execute()
            )
        except HttpError as exc:
            raise DriveApiError(f"Root folder {folder_id!r} is not accessible: {exc}") from exc
        if response.get("mimeType") != _FOLDER_MIME:
            raise DriveApiError(f"{folder_id!r} exists but is not a folder")
        return response.get("name", folder_id)

    @google_api_retry()
    def trash_file(self, file_id: str) -> None:
        """Trashes a single file — used by the first-run wizard's "Test
        Upload" step to clean up the small connectivity-check file it
        uploads, so onboarding doesn't leave litter behind in the user's
        actual Drive folder."""
        try:
            self._drive().files().update(
                fileId=file_id, body={"trashed": True}, supportsAllDrives=True
            ).execute()
        except HttpError as exc:
            raise DriveApiError(f"Failed to trash file {file_id}: {exc}") from exc

    # -- Folder discovery/creation ------------------------------------------------

    def get_or_create_date_folder(self, date_label: str) -> str:
        """Find (or create) the top-level `date_label` folder under the configured root."""
        cache_key = date_label
        cached = self._folder_cache.get(cache_key)
        if cached and self._cached_folder_still_exists(cached):
            return cached
        if cached:
            self._evict_stale_cache_entry(cache_key, cached)

        parent_id = self._settings.root_folder_id
        folder_id = self._find_or_create_folder(date_label, parent_id)
        self._folder_cache.set(cache_key, folder_id, parent_id)
        return folder_id

    def get_or_create_device_folder(self, date_label: str, device_id: str) -> str:
        """Find (or create) the `IC-xxx` folder inside a date folder."""
        cache_key = f"{date_label}/{device_id}"
        cached = self._folder_cache.get(cache_key)
        if cached and self._cached_folder_still_exists(cached):
            return cached
        if cached:
            self._evict_stale_cache_entry(cache_key, cached)

        date_folder_id = self.get_or_create_date_folder(date_label)
        folder_id = self._find_or_create_folder(device_id, date_folder_id)
        self._folder_cache.set(cache_key, folder_id, date_folder_id)
        return folder_id

    def _cached_folder_still_exists(self, folder_id: str) -> bool:
        """Cheap existence check for a cached folder id.

        A cached Drive folder id can go stale if someone manually renames,
        moves, or deletes the folder in Drive during the day — without
        this check, every upload for that IC would silently keep failing
        with a 404 on `files.create` until the app restarts and the cache
        (which is DB-persisted, not just in-memory) happens to be cleared.
        We don't cache a "not found" result here on purpose: it's one
        cheap `files.get` call per cache *hit* that would otherwise have
        gone stale, versus a full failed upload attempt.
        """
        try:
            self._drive().files().get(fileId=folder_id, fields="id", supportsAllDrives=True).execute()
            return True
        except HttpError as exc:
            # Only a definitive 404 evicts the entry — any other error
            # (network blip, auth hiccup) must not evict a possibly-still-
            # valid cache entry over a transient failure; let the normal
            # upload retry path handle those instead.
            return not is_not_found_error(exc)

    def _evict_stale_cache_entry(self, cache_key: str, stale_folder_id: str) -> None:
        logger.warning("drive.folder_cache.stale_entry_evicted", cache_key=cache_key, folder_id=stale_folder_id)
        self._folder_cache.delete(cache_key)

    @google_api_retry()
    def _find_or_create_folder(self, name: str, parent_id: str) -> str:
        """Find (or create) a folder named `name` directly under `parent_id`.

        Google Drive has no atomic "create if not exists" for folders —
        `files.list` then `files.create` is inherently a check-then-act
        race. That race is invisible with a single operator's one process,
        but with a shared destination written to by many independent app
        instances at once (every team member's own copy, all pointed at
        the same root folder), two processes can both list "31 Aug/IC-188",
        both see nothing, and both create it — Drive happily allows two
        folders with the identical name/parent, silently scattering that
        IC's videos across both for the rest of the day.

        We can't prevent the race, but we can make it self-healing: after
        creating, re-list for the same name/parent. If more than one now
        exists, every process computes the *same* deterministic winner
        (oldest `createdTime`, tie-broken by id) — so all concurrent
        callers converge on one folder without needing to coordinate. A
        process that just lost the race trashes the folder it *itself*
        just created a moment ago (which by construction cannot yet
        contain any files: nothing is uploaded until this method returns
        a folder id to upload into) rather than ever touching a folder
        another process created, so this never risks deleting content.
        """
        try:
            existing = self._list_folders_by_name(name, parent_id)
            if len(existing) == 1:
                return existing[0]["id"]
            if len(existing) > 1:
                return self._resolve_duplicate_folders(existing, name, parent_id)

            metadata = {"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]}
            created = (
                self._drive()
                .files()
                .create(body=metadata, fields="id, name, createdTime", supportsAllDrives=True)
                .execute()
            )
            new_id = created["id"]
            logger.info("drive.folder.created", name=name, parent=parent_id, id=new_id)

            # Reconcile: another process may have created the same folder
            # in the window between our list() above and this create().
            after_create = self._list_folders_by_name(name, parent_id)
            if len(after_create) > 1:
                return self._resolve_duplicate_folders(after_create, name, parent_id)
            return new_id
        except HttpError as exc:
            raise DriveApiError(f"Failed to find/create Drive folder {name!r}: {exc}") from exc

    def _list_folders_by_name(self, name: str, parent_id: str) -> list[dict]:
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"name = '{escaped}' and mimeType = '{_FOLDER_MIME}' "
            f"and '{parent_id}' in parents and trashed = false"
        )
        list_kwargs: dict[str, object] = {
            "q": query,
            "fields": "files(id, name, createdTime)",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
            # Deterministic ordering means "first result" is a meaningful,
            # stable choice rather than whatever order the API feels like
            # returning today.
            "orderBy": "createdTime,name",
        }
        if self._settings.shared_drive_id:
            list_kwargs["corpora"] = "drive"
            list_kwargs["driveId"] = self._settings.shared_drive_id

        response = self._drive().files().list(**list_kwargs).execute()
        return response.get("files", [])

    def _resolve_duplicate_folders(self, folders: list[dict], name: str, parent_id: str) -> str:
        canonical = min(folders, key=lambda f: (f.get("createdTime") or "", f["id"]))
        losers = [f for f in folders if f["id"] != canonical["id"]]
        logger.warning(
            "drive.folder.duplicate_detected",
            name=name,
            parent=parent_id,
            canonical_id=canonical["id"],
            duplicate_count=len(losers),
        )
        for loser in losers:
            self._trash_empty_duplicate_folder(loser["id"], name)
        return canonical["id"]

    def _trash_empty_duplicate_folder(self, folder_id: str, name: str) -> None:
        """Best-effort cleanup of a losing duplicate folder.

        Only ever called on a folder id this exact call chain just created
        moments ago (see `_find_or_create_folder`) and that therefore has
        had no chance to receive an upload yet. Still checks for children
        before trashing as defense in depth — if this assumption is ever
        wrong (e.g. a future caller path changes), we must never destroy
        someone's uploaded video by deleting the folder it landed in; we
        simply leave a rare, harmless duplicate folder behind instead.
        """
        try:
            children = (
                self._drive()
                .files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="files(id)",
                    pageSize=1,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            if children.get("files"):
                logger.warning("drive.folder.duplicate_not_empty_left_in_place", folder_id=folder_id, name=name)
                return
            self._drive().files().update(fileId=folder_id, body={"trashed": True}, supportsAllDrives=True).execute()
            logger.info("drive.folder.duplicate_trashed", folder_id=folder_id, name=name)
        except HttpError as exc:
            logger.warning("drive.folder.duplicate_cleanup_failed", folder_id=folder_id, error=str(exc))

    # -- Cross-process dedup ----------------------------------------------------

    @google_api_retry()
    def find_duplicate_by_hash(self, sha256: str) -> DriveHashMatch | None:
        """Ask Drive itself whether a file with this SHA-256 already
        exists — the authoritative dedup check when the destination is
        shared by many independent app instances (every team member's own
        copy). The local `uploaded_hashes` SQLite table only knows what
        *this* process has uploaded; if the same video is forwarded to two
        different people, their two processes' local indexes are both
        empty for it right up until one of them finishes uploading, so a
        purely local check can't catch this. Every upload tags its file
        with a custom `sha256` property (see `upload_file`); Drive indexes
        custom properties for search, so this is one `files.list` call —
        no coordination service or backend needed, and it works for any
        file this account can see anywhere in Drive, not just under the
        configured root, so it also catches the (accidental) case of a
        video someone already uploaded to a different date/device folder.
        """
        if not _SHA256_HEX_RE.match(sha256):
            raise ValueError(f"Not a valid SHA-256 hex digest: {sha256!r}")

        list_kwargs: dict[str, object] = {
            "q": f"properties has {{ key='sha256' and value='{sha256}' }} and trashed = false",
            "fields": "files(id, name, webViewLink)",
            "pageSize": 1,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if self._settings.shared_drive_id:
            list_kwargs["corpora"] = "drive"
            list_kwargs["driveId"] = self._settings.shared_drive_id

        try:
            response = self._drive().files().list(**list_kwargs).execute()
        except HttpError as exc:
            raise DriveApiError(f"Failed to search Drive for duplicate hash {sha256[:12]}...: {exc}") from exc

        files = response.get("files", [])
        if not files:
            return None
        match = files[0]
        return DriveHashMatch(
            file_id=match["id"],
            name=match.get("name", ""),
            web_view_link=match.get("webViewLink") or self.build_view_link(match["id"]),
        )

    # -- Upload ---------------------------------------------------------------

    def upload_file(
        self,
        file_path: Path,
        folder_id: str,
        *,
        chunk_size_mb: int = 8,
        progress_callback: ProgressCallback | None = None,
        sha256: str | None = None,
    ) -> UploadResult:
        started = time.monotonic()
        total_bytes = file_path.stat().st_size
        chunk_size = max(DRIVE_CHUNK_ALIGNMENT_BYTES, int(chunk_size_mb * 1024 * 1024))

        metadata: dict[str, object] = {"name": file_path.name, "parents": [folder_id]}
        if sha256:
            # Custom property, not a rename/content change — this is what
            # `find_duplicate_by_hash` searches on to give every other
            # process sharing this destination a real, Drive-native way to
            # discover "someone already uploaded this exact video".
            metadata["properties"] = {"sha256": sha256}
        media = MediaFileUpload(str(file_path), chunksize=chunk_size, resumable=True)

        try:
            request = (
                self._drive()
                .files()
                .create(
                    body=metadata,
                    media_body=media,
                    fields="id, webViewLink",
                    supportsAllDrives=True,
                )
            )
            response = None
            while response is None:
                status, response = self._next_chunk_with_retry(request)
                if status is not None and progress_callback is not None:
                    progress_callback(int(status.resumable_progress), total_bytes)

            if progress_callback is not None:
                progress_callback(total_bytes, total_bytes)

            file_id = response["id"]
            web_link = response.get("webViewLink") or self.build_view_link(file_id)

            if self._settings.make_public_link:
                self.set_anyone_with_link(file_id)

            return UploadResult(
                file_id=file_id,
                web_view_link=web_link,
                folder_id=folder_id,
                bytes_uploaded=total_bytes,
                duration_seconds=time.monotonic() - started,
            )
        except HttpError as exc:
            raise DriveApiError(f"Upload failed for {file_path.name}: {exc}") from exc
        except OSError as exc:
            raise DriveApiError(f"Local file error while uploading {file_path.name}: {exc}") from exc

    @google_api_retry(max_attempts=6)
    def _next_chunk_with_retry(self, request):  # type: ignore[no-untyped-def]
        return request.next_chunk()

    @google_api_retry()
    def set_anyone_with_link(self, file_id: str) -> None:
        try:
            self._drive().permissions().create(
                fileId=file_id,
                body={"role": "reader", "type": "anyone"},
                supportsAllDrives=True,
            ).execute()
        except HttpError as exc:
            raise DriveApiError(f"Failed to set link-sharing permission on {file_id}: {exc}") from exc

    @staticmethod
    def build_view_link(file_id: str) -> str:
        return f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"
