from __future__ import annotations

from pathlib import Path

from instacore_sync.db.database import Database
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import UploadLogEntry


def _entry(**overrides) -> UploadLogEntry:
    defaults = {
        "job_id": "job-1",
        "filename": "IC-188_clip.mp4",
        "device_id": "IC-188",
        "status": JobStatus.COMPLETED,
        "ocr_confidence": 0.92,
        "ocr_engine_used": "tesseract",
        "file_hash_sha256": "hash1",
        "drive_link": "https://drive/1",
        "error_message": None,
    }
    defaults.update(overrides)
    return UploadLogEntry(**defaults)


def test_append_and_search_by_device_id(database: Database) -> None:
    repo = LogsRepository(database)
    repo.append(_entry())
    repo.append(_entry(job_id="job-2", filename="IC-551_clip.mp4", device_id="IC-551"))

    results = repo.search(device_id="IC-188")
    assert len(results) == 1
    assert results[0].device_id == "IC-188"


def test_search_by_filename_contains(database: Database) -> None:
    repo = LogsRepository(database)
    repo.append(_entry(filename="morning_batch_1.mp4"))
    repo.append(_entry(job_id="job-2", filename="evening_batch_2.mp4", device_id="IC-99"))

    results = repo.search(filename_contains="morning")
    assert len(results) == 1
    assert results[0].filename == "morning_batch_1.mp4"


def test_search_by_status(database: Database) -> None:
    repo = LogsRepository(database)
    repo.append(_entry(status=JobStatus.COMPLETED))
    repo.append(_entry(job_id="job-2", status=JobStatus.FAILED, error_message="boom"))

    failed = repo.search(status=JobStatus.FAILED)
    assert len(failed) == 1
    assert failed[0].error_message == "boom"


def test_export_csv_writes_header_and_rows(database: Database, tmp_path: Path) -> None:
    repo = LogsRepository(database)
    repo.append(_entry())
    repo.append(_entry(job_id="job-2", filename="another.mp4", device_id="IC-2"))

    destination = tmp_path / "export.csv"
    repo.export_csv(destination)

    content = destination.read_text(encoding="utf-8")
    lines = content.strip().splitlines()
    assert lines[0].startswith("log_id,job_id,filename")
    assert len(lines) == 3  # header + 2 rows
