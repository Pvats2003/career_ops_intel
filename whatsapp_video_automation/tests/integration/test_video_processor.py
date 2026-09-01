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
        self.call_count = 0

    def extract(self, video_path: Path) -> DeviceIdExtraction:
        self.call_count += 1
        return self._extraction


class _StubDrive:
    def __init__(self) -> None:
        self.uploaded: list[tuple[Path, str]] = []

    def get_or_create_device_folder(self, date_label: str, device_id: str) -> str:
        return f"folder-{date_label}-{device_id}"

    def find_duplicate_by_hash(self, sha256: str):
        return None  # no cross-process duplicate in these single-process tests

    def upload_file(
        self, path: Path, folder_id: str, *, chunk_size_mb: int, progress_callback=None, sha256: str | None = None
    ):
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


class _RemoteDuplicateDrive(_StubDrive):
    """Simulates a *different* process already having uploaded this exact
    video into the shared destination: this process's own local
    `uploaded_hashes` table has never heard of it (empty), but Drive
    itself reports a match via the custom `sha256` property every upload
    is tagged with."""

    def __init__(self, existing_file_id: str, existing_name: str, existing_link: str) -> None:
        super().__init__()
        self._existing_file_id = existing_file_id
        self._existing_name = existing_name
        self._existing_link = existing_link
        self.find_duplicate_by_hash_calls = 0

    def find_duplicate_by_hash(self, sha256: str):
        from instacore_sync.domain.models import DriveHashMatch

        self.find_duplicate_by_hash_calls += 1
        return DriveHashMatch(
            file_id=self._existing_file_id, name=self._existing_name, web_view_link=self._existing_link
        )


def test_cross_process_duplicate_is_detected_via_drive_and_skipped(tmp_path: Path, database: Database) -> None:
    """The shared-destination scenario: this process's local dedup index
    has never seen this hash (a different team member's app instance
    uploaded it), so only Drive's own record of it — found through the
    cross-process check — can catch it. Must skip the upload exactly like
    a locally-known duplicate would, and must not hit OCR/upload at all."""
    ocr = _StubOcr(DeviceIdExtraction(device_id="IC-188", confidence=0.95, engine_used=OcrEngineName.TESSERACT))
    drive = _RemoteDuplicateDrive(
        existing_file_id="remote-file-1",
        existing_name="uploaded_by_someone_else.mp4",
        existing_link="https://drive.google.com/file/d/remote-file-1/view",
    )
    sheets = _StubSheets()
    processor = _make_processor(tmp_path, database, ocr, drive, sheets)

    job = processor.process(_video_job(tmp_path, "forwarded_to_me_too.mp4"))

    assert job.status == JobStatus.DUPLICATE
    assert job.drive_link == "https://drive.google.com/file/d/remote-file-1/view"
    assert drive.find_duplicate_by_hash_calls == 1
    assert len(drive.uploaded) == 0  # never re-uploaded
    assert ocr.call_count == 0  # dedup check short-circuits before OCR runs

    # And it's backfilled locally, so a second identical video (or a retry
    # of this one) is caught by the fast local check without another
    # network round trip.
    second = processor.process(_video_job(tmp_path, "same_content_again.mp4"))
    assert second.status == JobStatus.DUPLICATE
    assert drive.find_duplicate_by_hash_calls == 1  # not called again — local cache now has it


class _DriveDownDuringDedupCheck(_StubDrive):
    """The cross-process dedup check itself fails (Drive unreachable) —
    must fail open and let a legitimate upload through rather than
    blocking every video whenever this one extra check has a bad moment."""

    def find_duplicate_by_hash(self, sha256: str):
        from instacore_sync.core.exceptions import DriveApiError

        raise DriveApiError("simulated: Drive unreachable for the dedup check")


def test_remote_dedup_check_failure_fails_open_and_upload_still_proceeds(
    tmp_path: Path, database: Database
) -> None:
    ocr = _StubOcr(DeviceIdExtraction(device_id="IC-188", confidence=0.95, engine_used=OcrEngineName.TESSERACT))
    drive = _DriveDownDuringDedupCheck()
    sheets = _StubSheets()
    processor = _make_processor(tmp_path, database, ocr, drive, sheets)

    job = processor.process(_video_job(tmp_path))

    assert job.status == JobStatus.COMPLETED
    assert len(drive.uploaded) == 1


def test_pattern_invalid_device_id_is_rejected_before_drive_upload(tmp_path: Path, database: Database) -> None:
    """Defense-in-depth: even if something upstream of `_upload` (a bad OCR
    stub, or eventually a manual override) sets a device_id that doesn't
    match the configured pattern, it must never reach Drive/Sheets as a
    folder name / row value — it should route to Needs Review instead."""
    ocr = _StubOcr(
        DeviceIdExtraction(device_id="../../etc/passwd", confidence=0.99, engine_used=OcrEngineName.TESSERACT)
    )
    drive = _StubDrive()
    sheets = _StubSheets()
    processor = _make_processor(tmp_path, database, ocr, drive, sheets)

    job = processor.process(_video_job(tmp_path))

    assert job.status == JobStatus.NEEDS_REVIEW
    assert "does not match the expected pattern" in (job.last_error or "")
    assert len(drive.uploaded) == 0


def test_manually_confirmed_device_id_skips_ocr_and_uploads(tmp_path: Path, database: Database) -> None:
    """The Needs Review screen's manual override sets device_id +
    manually_confirmed on the job before re-queuing it; VideoProcessor must
    trust that choice rather than re-running OCR (which would just
    reproduce the same low-confidence read that sent it to review)."""
    ocr = _StubOcr(DeviceIdExtraction(device_id=None, confidence=0.0))  # would fail if actually called
    drive = _StubDrive()
    sheets = _StubSheets()
    processor = _make_processor(tmp_path, database, ocr, drive, sheets)

    job = _video_job(tmp_path)
    job.device_id = "IC-188"
    job.manually_confirmed = True

    processed = processor.process(job)

    assert processed.status == JobStatus.COMPLETED
    assert processed.device_id == "IC-188"
    assert ocr.call_count == 0  # OCR was never invoked
    assert len(drive.uploaded) == 1
    assert len(sheets.rows) == 1


def test_successful_run_records_ocr_upload_and_total_durations(tmp_path: Path, database: Database) -> None:
    ocr = _StubOcr(
        DeviceIdExtraction(device_id="IC-188", confidence=0.95, engine_used=OcrEngineName.TESSERACT)
    )
    drive = _StubDrive()  # returns duration_seconds=0.01 for every upload
    sheets = _StubSheets()
    processor = _make_processor(tmp_path, database, ocr, drive, sheets)
    logs_repo = LogsRepository(database)

    job = processor.process(_video_job(tmp_path))

    assert job.ocr_duration_seconds is not None and job.ocr_duration_seconds >= 0
    assert job.upload_duration_seconds == pytest.approx(0.01)

    logged = logs_repo.search(limit=10)
    assert len(logged) == 1
    entry = logged[0]
    assert entry.ocr_duration_seconds is not None
    assert entry.upload_duration_seconds == pytest.approx(0.01)
    assert entry.total_duration_seconds is not None and entry.total_duration_seconds >= 0
    assert entry.stack_trace is None  # no error occurred


def test_unexpected_exception_records_stack_trace_in_log(tmp_path: Path, database: Database) -> None:
    class _ExplodingOcr:
        def extract(self, video_path: Path) -> DeviceIdExtraction:
            raise RuntimeError("simulated unexpected OCR crash")

    drive = _StubDrive()
    sheets = _StubSheets()
    processor = _make_processor(tmp_path, database, _ExplodingOcr(), drive, sheets)
    logs_repo = LogsRepository(database)

    job = processor.process(_video_job(tmp_path))

    assert job.status == JobStatus.FAILED
    logged = logs_repo.search(limit=10)
    assert len(logged) == 1
    entry = logged[0]
    assert entry.stack_trace is not None
    assert "RuntimeError" in entry.stack_trace
    assert "simulated unexpected OCR crash" in entry.stack_trace
