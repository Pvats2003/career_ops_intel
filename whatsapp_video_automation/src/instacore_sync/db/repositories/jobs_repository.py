"""CRUD + queries for the `jobs` working table."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from instacore_sync.core.exceptions import RepositoryError
from instacore_sync.db.database import Database
from instacore_sync.domain.enums import JobStatus, OcrEngineName
from instacore_sync.domain.models import VideoJob


def _row_to_job(row: sqlite3.Row) -> VideoJob:
    return VideoJob(
        job_id=row["job_id"],
        source_path=Path(row["source_path"]),
        original_filename=row["original_filename"],
        status=JobStatus(row["status"]),
        file_size_bytes=row["file_size_bytes"],
        file_hash_sha256=row["file_hash_sha256"],
        device_id=row["device_id"],
        ocr_confidence=row["ocr_confidence"],
        ocr_engine_used=OcrEngineName(row["ocr_engine_used"]) if row["ocr_engine_used"] else None,
        drive_file_id=row["drive_file_id"],
        drive_link=row["drive_link"],
        drive_folder_id=row["drive_folder_id"],
        sheet_row_number=row["sheet_row_number"],
        attempt_count=row["attempt_count"],
        last_error=row["last_error"],
        bytes_uploaded=row["bytes_uploaded"],
        upload_speed_bps=row["upload_speed_bps"],
        discovered_at=datetime.fromisoformat(row["discovered_at"]),
        started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        ocr_raw_text=row["ocr_raw_text"],
        manually_confirmed=bool(row["manually_confirmed"]),
    )


class JobsRepository:
    """Persistence for `VideoJob` — the live working state of the pipeline."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, job: VideoJob) -> None:
        try:
            with self._db.write_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO jobs (
                        job_id, source_path, original_filename, status, file_size_bytes,
                        file_hash_sha256, device_id, ocr_confidence, ocr_engine_used,
                        drive_file_id, drive_link, drive_folder_id, sheet_row_number,
                        attempt_count, last_error, bytes_uploaded, upload_speed_bps,
                        discovered_at, started_at, completed_at, ocr_raw_text, manually_confirmed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        source_path=excluded.source_path,
                        original_filename=excluded.original_filename,
                        status=excluded.status,
                        file_size_bytes=excluded.file_size_bytes,
                        file_hash_sha256=excluded.file_hash_sha256,
                        device_id=excluded.device_id,
                        ocr_confidence=excluded.ocr_confidence,
                        ocr_engine_used=excluded.ocr_engine_used,
                        drive_file_id=excluded.drive_file_id,
                        drive_link=excluded.drive_link,
                        drive_folder_id=excluded.drive_folder_id,
                        sheet_row_number=excluded.sheet_row_number,
                        attempt_count=excluded.attempt_count,
                        last_error=excluded.last_error,
                        bytes_uploaded=excluded.bytes_uploaded,
                        upload_speed_bps=excluded.upload_speed_bps,
                        started_at=excluded.started_at,
                        completed_at=excluded.completed_at,
                        ocr_raw_text=excluded.ocr_raw_text,
                        manually_confirmed=excluded.manually_confirmed
                    """,
                    (
                        job.job_id,
                        str(job.source_path),
                        job.original_filename,
                        job.status.value,
                        job.file_size_bytes,
                        job.file_hash_sha256,
                        job.device_id,
                        job.ocr_confidence,
                        job.ocr_engine_used.value if job.ocr_engine_used else None,
                        job.drive_file_id,
                        job.drive_link,
                        job.drive_folder_id,
                        job.sheet_row_number,
                        job.attempt_count,
                        job.last_error,
                        job.bytes_uploaded,
                        job.upload_speed_bps,
                        job.discovered_at.isoformat(),
                        job.started_at.isoformat() if job.started_at else None,
                        job.completed_at.isoformat() if job.completed_at else None,
                        job.ocr_raw_text,
                        int(job.manually_confirmed),
                    ),
                )
        except sqlite3.Error as exc:
            raise RepositoryError(f"Failed to upsert job {job.job_id}: {exc}") from exc

    def get(self, job_id: str) -> VideoJob | None:
        with self._db.read_cursor() as cur:
            row = cur.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def find_by_hash(self, file_hash_sha256: str) -> VideoJob | None:
        with self._db.read_cursor() as cur:
            row = cur.execute(
                "SELECT * FROM jobs WHERE file_hash_sha256 = ? ORDER BY discovered_at DESC LIMIT 1",
                (file_hash_sha256,),
            ).fetchone()
        return _row_to_job(row) if row else None

    def list_by_status(self, *statuses: JobStatus) -> list[VideoJob]:
        placeholders = ",".join("?" for _ in statuses)
        with self._db.read_cursor() as cur:
            rows = cur.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY discovered_at ASC",
                tuple(s.value for s in statuses),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def list_active(self) -> list[VideoJob]:
        return self.list_by_status(
            JobStatus.DISCOVERED,
            JobStatus.QUEUED,
            JobStatus.EXTRACTING,
            JobStatus.HASHING,
            JobStatus.UPLOADING,
            JobStatus.UPDATING_SHEET,
        )

    def counts_by_status(self) -> dict[JobStatus, int]:
        with self._db.read_cursor() as cur:
            rows = cur.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {JobStatus(r["status"]): r["n"] for r in rows}

    def delete(self, job_id: str) -> None:
        with self._db.write_cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

    def prune_terminal_jobs_older_than(self, cutoff: datetime, *, batch_limit: int = 5000) -> int:
        """Delete COMPLETED/DUPLICATE rows discovered before `cutoff`.

        Only touches the live working table — `upload_logs` (the durable,
        searchable/exportable audit trail) is never pruned by this. FAILED
        and NEEDS_REVIEW rows are deliberately excluded so nothing a human
        still needs to act on ever disappears on its own. `batch_limit`
        bounds a single call's work so pruning a very large backlog (e.g.
        first upgrade to a version with pruning, after months of unpruned
        growth) can't itself become a multi-second startup stall.
        """
        try:
            with self._db.write_cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM jobs
                    WHERE job_id IN (
                        SELECT job_id FROM jobs
                        WHERE status IN (?, ?) AND discovered_at < ?
                        LIMIT ?
                    )
                    """,
                    (
                        JobStatus.COMPLETED.value,
                        JobStatus.DUPLICATE.value,
                        cutoff.isoformat(),
                        batch_limit,
                    ),
                )
                return cur.rowcount if cur.rowcount is not None else 0
        except sqlite3.Error as exc:
            raise RepositoryError(f"Failed to prune old jobs: {exc}") from exc
