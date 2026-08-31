"""Google Drive integration: folder discovery/creation, resumable upload, sharing.

Supports both a normal "My Drive" folder tree and a Shared Drive (set
`shared_drive_id` in settings) by passing `supportsAllDrives=True` and
`includeItemsFromAllDrives=True` on every call, and `corpora="drive"` +
`driveId=...` on list calls when a shared drive is configured.
"""

from __future__ import annotations

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
from instacore_sync.domain.models import UploadResult
from instacore_sync.utils.retry import network_retry

logger = get_logger(__name__)

_FOLDER_MIME = "application/vnd.google-apps.folder"

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

    # -- Folder discovery/creation ------------------------------------------------

    def get_or_create_date_folder(self, date_label: str) -> str:
        """Find (or create) the top-level `date_label` folder under the configured root."""
        cache_key = date_label
        cached = self._folder_cache.get(cache_key)
        if cached:
            return cached

        parent_id = self._settings.root_folder_id
        folder_id = self._find_or_create_folder(date_label, parent_id)
        self._folder_cache.set(cache_key, folder_id, parent_id)
        return folder_id

    def get_or_create_device_folder(self, date_label: str, device_id: str) -> str:
        """Find (or create) the `IC-xxx` folder inside a date folder."""
        cache_key = f"{date_label}/{device_id}"
        cached = self._folder_cache.get(cache_key)
        if cached:
            return cached

        date_folder_id = self.get_or_create_date_folder(date_label)
        folder_id = self._find_or_create_folder(device_id, date_folder_id)
        self._folder_cache.set(cache_key, folder_id, date_folder_id)
        return folder_id

    @network_retry(retry_on=(HttpError,))
    def _find_or_create_folder(self, name: str, parent_id: str) -> str:
        escaped = name.replace("'", "\\'")
        query = (
            f"name = '{escaped}' and mimeType = '{_FOLDER_MIME}' "
            f"and '{parent_id}' in parents and trashed = false"
        )
        list_kwargs: dict[str, object] = {
            "q": query,
            "fields": "files(id, name)",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if self._settings.shared_drive_id:
            list_kwargs["corpora"] = "drive"
            list_kwargs["driveId"] = self._settings.shared_drive_id

        try:
            response = self._drive().files().list(**list_kwargs).execute()
            existing = response.get("files", [])
            if existing:
                return existing[0]["id"]

            metadata = {"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]}
            created = (
                self._drive()
                .files()
                .create(body=metadata, fields="id", supportsAllDrives=True)
                .execute()
            )
            logger.info("drive.folder.created", name=name, parent=parent_id, id=created["id"])
            return created["id"]
        except HttpError as exc:
            raise DriveApiError(f"Failed to find/create Drive folder {name!r}: {exc}") from exc

    # -- Upload ---------------------------------------------------------------

    def upload_file(
        self,
        file_path: Path,
        folder_id: str,
        *,
        chunk_size_mb: int = 8,
        progress_callback: ProgressCallback | None = None,
    ) -> UploadResult:
        started = time.monotonic()
        total_bytes = file_path.stat().st_size
        chunk_size = max(DRIVE_CHUNK_ALIGNMENT_BYTES, int(chunk_size_mb * 1024 * 1024))

        metadata = {"name": file_path.name, "parents": [folder_id]}
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

    @network_retry(max_attempts=6, retry_on=(HttpError,))
    def _next_chunk_with_retry(self, request):  # type: ignore[no-untyped-def]
        return request.next_chunk()

    @network_retry(retry_on=(HttpError,))
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
