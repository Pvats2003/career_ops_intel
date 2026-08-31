"""Prevents uploading the same video twice, even across renames/restarts.

Two videos are considered duplicates if their SHA-256 digests match. The
authoritative record lives in `uploaded_hashes` (populated only after a
successful Drive upload), so a video that failed partway through is *not*
treated as a duplicate on retry.
"""

from __future__ import annotations

from pathlib import Path

from instacore_sync.core.logging_setup import get_logger
from instacore_sync.db.repositories.hashes_repository import HashesRepository, UploadedHashRecord
from instacore_sync.services.hashing.hash_service import HashService

logger = get_logger(__name__)


class DedupService:
    def __init__(self, hash_service: HashService, hashes_repo: HashesRepository) -> None:
        self._hash_service = hash_service
        self._repo = hashes_repo

    def compute_hash(self, path: Path) -> str:
        return self._hash_service.sha256_of_file(path)

    def find_duplicate(self, file_hash_sha256: str) -> UploadedHashRecord | None:
        record = self._repo.get(file_hash_sha256)
        if record is not None:
            logger.info(
                "dedup.duplicate_found",
                hash=file_hash_sha256[:12],
                original_filename=record.original_filename,
            )
        return record

    def record_upload(
        self,
        file_hash_sha256: str,
        job_id: str,
        original_filename: str,
        drive_file_id: str,
        drive_link: str,
    ) -> None:
        self._repo.record(file_hash_sha256, job_id, original_filename, drive_file_id, drive_link)
