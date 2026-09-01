"""Persistence for the SHA-256 dedup index (`uploaded_hashes` table)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from instacore_sync.core.exceptions import RepositoryError
from instacore_sync.db.database import Database


@dataclass(frozen=True, slots=True)
class UploadedHashRecord:
    file_hash_sha256: str
    job_id: str
    original_filename: str
    drive_file_id: str
    drive_link: str
    uploaded_at: datetime


class HashesRepository:
    """Fast existence checks so we never upload the same video twice."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def exists(self, file_hash_sha256: str) -> bool:
        with self._db.read_cursor() as cur:
            row = cur.execute(
                "SELECT 1 FROM uploaded_hashes WHERE file_hash_sha256 = ?",
                (file_hash_sha256,),
            ).fetchone()
        return row is not None

    def get(self, file_hash_sha256: str) -> UploadedHashRecord | None:
        with self._db.read_cursor() as cur:
            row = cur.execute(
                "SELECT * FROM uploaded_hashes WHERE file_hash_sha256 = ?",
                (file_hash_sha256,),
            ).fetchone()
        if row is None:
            return None
        return UploadedHashRecord(
            file_hash_sha256=row["file_hash_sha256"],
            job_id=row["job_id"],
            original_filename=row["original_filename"],
            drive_file_id=row["drive_file_id"],
            drive_link=row["drive_link"],
            uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
        )

    def record(
        self,
        file_hash_sha256: str,
        job_id: str,
        original_filename: str,
        drive_file_id: str,
        drive_link: str,
    ) -> None:
        try:
            with self._db.write_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO uploaded_hashes
                        (file_hash_sha256, job_id, original_filename, drive_file_id, drive_link, uploaded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(file_hash_sha256) DO NOTHING
                    """,
                    (
                        file_hash_sha256,
                        job_id,
                        original_filename,
                        drive_file_id,
                        drive_link,
                        datetime.now().isoformat(),
                    ),
                )
        except sqlite3.Error as exc:
            raise RepositoryError(f"Failed to record hash {file_hash_sha256}: {exc}") from exc

    def count(self) -> int:
        with self._db.read_cursor() as cur:
            row = cur.execute("SELECT COUNT(*) AS n FROM uploaded_hashes").fetchone()
        return int(row["n"])
