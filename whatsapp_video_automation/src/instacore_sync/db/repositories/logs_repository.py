"""Persistence + search/export for the durable `upload_logs` audit trail."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from instacore_sync.core.exceptions import RepositoryError
from instacore_sync.db.database import Database
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import UploadLogEntry


def _row_to_entry(row: sqlite3.Row) -> UploadLogEntry:
    return UploadLogEntry(
        log_id=row["log_id"],
        job_id=row["job_id"],
        filename=row["filename"],
        device_id=row["device_id"],
        status=JobStatus(row["status"]),
        ocr_confidence=row["ocr_confidence"],
        ocr_engine_used=row["ocr_engine_used"],
        file_hash_sha256=row["file_hash_sha256"],
        drive_link=row["drive_link"],
        error_message=row["error_message"],
        created_at=datetime.fromisoformat(row["created_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        ocr_duration_seconds=row["ocr_duration_seconds"],
        upload_duration_seconds=row["upload_duration_seconds"],
        total_duration_seconds=row["total_duration_seconds"],
        stack_trace=row["stack_trace"],
    )


class LogsRepository:
    """Append-only log of every job that reaches a terminal status."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, entry: UploadLogEntry) -> None:
        try:
            with self._db.write_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO upload_logs (
                        log_id, job_id, filename, device_id, status, ocr_confidence,
                        ocr_engine_used, file_hash_sha256, drive_link, error_message,
                        created_at, completed_at, ocr_duration_seconds, upload_duration_seconds,
                        total_duration_seconds, stack_trace
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.log_id,
                        entry.job_id,
                        entry.filename,
                        entry.device_id,
                        entry.status.value,
                        entry.ocr_confidence,
                        entry.ocr_engine_used,
                        entry.file_hash_sha256,
                        entry.drive_link,
                        entry.error_message,
                        entry.created_at.isoformat(),
                        entry.completed_at.isoformat() if entry.completed_at else None,
                        entry.ocr_duration_seconds,
                        entry.upload_duration_seconds,
                        entry.total_duration_seconds,
                        entry.stack_trace,
                    ),
                )
        except sqlite3.Error as exc:
            raise RepositoryError(f"Failed to append log entry {entry.log_id}: {exc}") from exc

    def search(
        self,
        *,
        device_id: str | None = None,
        filename_contains: str | None = None,
        status: JobStatus | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[UploadLogEntry]:
        clauses: list[str] = []
        params: list[object] = []

        if device_id:
            clauses.append("device_id LIKE ?")
            params.append(f"%{device_id}%")
        if filename_contains:
            clauses.append("filename LIKE ?")
            params.append(f"%{filename_contains}%")
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from.isoformat())
        if date_to:
            clauses.append("created_at <= ?")
            params.append(date_to.isoformat())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM upload_logs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._db.read_cursor() as cur:
            rows = cur.execute(query, tuple(params)).fetchall()
        return [_row_to_entry(r) for r in rows]

    def export_csv(self, destination: Path, entries: list[UploadLogEntry] | None = None) -> Path:
        rows = entries if entries is not None else self.search(limit=100_000)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "log_id", "job_id", "filename", "device_id", "status",
                    "ocr_confidence", "ocr_engine_used", "file_hash_sha256",
                    "drive_link", "error_message", "created_at", "completed_at",
                    "ocr_duration_seconds", "upload_duration_seconds", "total_duration_seconds",
                ]
            )
            for e in rows:
                writer.writerow(
                    [
                        e.log_id, e.job_id, e.filename, e.device_id, e.status.value,
                        f"{e.ocr_confidence:.3f}", e.ocr_engine_used, e.file_hash_sha256,
                        e.drive_link, e.error_message,
                        e.created_at.isoformat(), e.completed_at.isoformat() if e.completed_at else "",
                        e.ocr_duration_seconds if e.ocr_duration_seconds is not None else "",
                        e.upload_duration_seconds if e.upload_duration_seconds is not None else "",
                        e.total_duration_seconds if e.total_duration_seconds is not None else "",
                    ]
                )
        return destination

    def today_stats_rows(self, day_start_iso: str) -> list[UploadLogEntry]:
        with self._db.read_cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM upload_logs WHERE created_at >= ? ORDER BY created_at DESC",
                (day_start_iso,),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]
