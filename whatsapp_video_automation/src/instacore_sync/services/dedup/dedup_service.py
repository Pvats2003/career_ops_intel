"""Prevents uploading the same video twice, even across renames/restarts —
and even when two byte-identical videos are being processed *concurrently*.

Two videos are considered duplicates if their SHA-256 digests match. The
authoritative record lives in `uploaded_hashes` (populated only after a
successful Drive upload), so a video that failed partway through is *not*
treated as a duplicate on retry.

That DB check alone isn't sufficient once uploads run concurrently (10-20
at a time, per the product spec): if WhatsApp delivers the same video into
several groups at once, two worker threads can each hash it, both find
`uploaded_hashes` still empty (neither has finished uploading yet), and
both proceed to upload it — a real, observed race under
`tests/integration/test_stress_concurrency.py`'s concurrency stress test,
not just a theoretical one. `claim_for_upload`/`release_claim` close that
window with a small in-memory "who's uploading this hash right now" set:
the second job's claim is rejected, it's routed through the existing
retry/backoff path (see `VideoProcessor`), and by the time it retries the
first upload has normally finished and the DB check alone is enough to
correctly mark it a duplicate.
"""

from __future__ import annotations

import threading
from pathlib import Path

from instacore_sync.core.logging_setup import get_logger
from instacore_sync.db.repositories.hashes_repository import HashesRepository, UploadedHashRecord
from instacore_sync.services.hashing.hash_service import HashService

logger = get_logger(__name__)


class DedupService:
    def __init__(self, hash_service: HashService, hashes_repo: HashesRepository) -> None:
        self._hash_service = hash_service
        self._repo = hashes_repo
        self._in_flight: set[str] = set()
        self._in_flight_lock = threading.Lock()

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

    def claim_for_upload(self, file_hash_sha256: str) -> bool:
        """Atomically claim a hash as "being uploaded by this process right
        now". Returns False if another job already holds the claim — the
        caller should treat that as "so close to a duplicate it isn't
        worth racing", not attempt the upload itself.
        """
        with self._in_flight_lock:
            if file_hash_sha256 in self._in_flight:
                return False
            self._in_flight.add(file_hash_sha256)
            return True

    def release_claim(self, file_hash_sha256: str) -> None:
        """Release a hash claim once its processing attempt has ended
        (success or failure) — safe to call even if this hash was never
        claimed (e.g. it was already a confirmed duplicate)."""
        with self._in_flight_lock:
            self._in_flight.discard(file_hash_sha256)

    def record_upload(
        self,
        file_hash_sha256: str,
        job_id: str,
        original_filename: str,
        drive_file_id: str,
        drive_link: str,
    ) -> None:
        self._repo.record(file_hash_sha256, job_id, original_filename, drive_file_id, drive_link)
