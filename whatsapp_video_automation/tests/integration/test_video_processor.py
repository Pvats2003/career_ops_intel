"""End-to-end (in-process) tests of `VideoProcessor` with every external
dependency (OCR, Drive, Sheets) faked out, but a real SQLite DB and real
filesystem moves — this is the closest thing to an integration test that
still runs in milliseconds with zero network/OS-service dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest

from instacore_sync.core.config import AppSettings
from instacore_sync.db.database import Database
from instacore_sync.db.repositories.hashes_repository import HashesRepository
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.domain.enums import JobStatus, OcrEngineName
from instacore_sync.domain.models import DeviceIdExtraction, UploadResult, VideoJob
from instacore_sync.services.dedup.dedup_service import DedupService
from instacore_sync.services.hashing.hash_service import HashService
from instacore_sync.services.pipeline import video_processor as video_processor_module
from instacore_sync.services.pipeline.video_processor import VideoProcessor


class _StubOcr:
    def __init__(self, extraction: DeviceIdExtraction) -> None:
        self._extraction = extraction

    def extract(self, video_path: Path) -> DeviceIdExtraction:
        return self._extraction


class _StubDrive:
    def __init__(self) -> None:
        self.uploaded: list[tuple[Path, str]] = []

    def get_or_create_device_folder(self, date_label: str, device_id: str) -> str:
        return f"folder-{date_label}-{device_id}"

    def upload_file(self, path: Path, folder_id: str, *, chunk_size_mb: int, progress_callback=None):
        if progress_callback:
            progress_callback(path.stat().st_size, path.stat().st_size)
        self.uploaded.append((path, folder_id))
        return UploadResult(
            file_id="fake-file-id",
            web_view_link="https://drive.google.com/file/d/fake-file-id/view",
            folder_id=folder_id,
            bytes_uploaded=path.stat().st_size,
            duration_seconds=0.01,
        )


class _StubSheets:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def upsert_row(self, **kwargs):
        from instacore_sync.domain.models import SheetUpdateResult

        self.rows.append(kwargs)
        return SheetUpdateResult(spreadsheet_id="sheet-1", row_number=len(self.rows) + 1, created_new_row=True)


@pytest.fixture(autouse=True)
def _fast_stability_check(monkeypatch):
    """Skip the real 1.5s file-stability wait; the test files aren't being
    written to incrementally so there's nothing to actually wait for."""

    def _instant_stable(path: Path, **_kwargs) -> int:
        return path.stat().st_size

    monkeypatch.setattr(video_processor_module, "wait_until_stable", _instant_stable)


def _make_processor(
    tmp_path: Path, database: Database, ocr: _StubOcr, drive: _StubDrive, sheets: _StubSheets
) -> VideoProcessor:
    settings = AppSettings()
    settings.processed_folder = str(tmp_path / "Processed")
    settings.needs_review_folder = str(tmp_path / "NeedsReview")
    settings.failed_folder = str(tmp_path / "Failed")
    settings.sheets.spreadsheet_id = "sheet-1"

    jobs_repo = JobsRepository(database)
    logs_repo = LogsRepository(database)
    dedup_service = DedupService(HashService(), HashesRepository(database))

    return VideoProcessor(settings, ocr, dedup_service, drive, sheets, jobs_repo, logs_repo)


def _video_job(tmp_path: Path, name: str = "IC-188_clip.mp4") -> VideoJob:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir(exist_ok=True)
    video_path = watch_dir / name
    video_path.write_bytes(b"fake mp4 bytes" * 100)
    return VideoJob(source_path=video_path, original_filename=name)


def test_happy_path_completes_and_moves_to_processed(tmp_path: Path, database: Database) -> None:
    ocr = _StubOcr(
        DeviceIdExtraction(device_id="IC-188", confidence=0.95, engine_used=OcrEngineName.TESSERACT)
    )
    drive = _StubDrive()
    sheets = _StubSheets()
    processor = _make_processor(tmp_path, database, ocr, drive, sheets)

    job = processor.process(_video_job(tmp_path))

    assert job.status == JobStatus.COMPLETED
    assert job.device_id == "IC-188"
    assert job.drive_link == "https://drive.google.com/file/d/fake-file-id/view"
    assert job.source_path.parent == Path(processor._settings.processed_folder)
    assert job.source_path.exists()
    assert len(drive.uploaded) == 1
    assert len(sheets.rows) == 1


def test_low_confidence_routes_to_needs_review(tmp_path: Path, database: Database) -> None:
    ocr = _StubOcr(DeviceIdExtraction(device_id="IC-9", confidence=0.10, engine_used=OcrEngineName.TESSERACT))
    drive = _StubDrive()
    sheets = _StubSheets()
    processor = _make_processor(tmp_path, database, ocr, drive, sheets)

    job = processor.process(_video_job(tmp_path))

    assert job.status == JobStatus.NEEDS_REVIEW
    assert job.source_path.parent == Path(processor._settings.needs_review_folder)
    assert len(drive.uploaded) == 0  # never reaches the upload step
    assert len(sheets.rows) == 0


def test_no_device_id_found_routes_to_needs_review(tmp_path: Path, database: Database) -> None:
    ocr = _StubOcr(DeviceIdExtraction(device_id=None, confidence=0.0))
    processor = _make_processor(tmp_path, database, ocr, _StubDrive(), _StubSheets())

    job = processor.process(_video_job(tmp_path))

    assert job.status == JobStatus.NEEDS_REVIEW
    assert "No Device ID pattern" in (job.last_error or "")


def test_duplicate_video_is_skipped_without_uploading(tmp_path: Path, database: Database) -> None:
    ocr = _StubOcr(DeviceIdExtraction(device_id="IC-188", confidence=0.95, engine_used=OcrEngineName.TESSERACT))
    drive = _StubDrive()
    sheets = _StubSheets()
    processor = _make_processor(tmp_path, database, ocr, drive, sheets)

    first_job = _video_job(tmp_path, "first.mp4")
    second_job = _video_job(tmp_path, "second.mp4")
    second_job.source_path.write_bytes(first_job.source_path.read_bytes())  # identical content -> same hash

    processed_first = processor.process(first_job)
    assert processed_first.status == JobStatus.COMPLETED
    assert len(drive.uploaded) == 1

    processed_second = processor.process(second_job)
    assert processed_second.status == JobStatus.DUPLICATE
    assert len(drive.uploaded) == 1  # not uploaded again
