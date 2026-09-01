"""End-to-end `VideoProcessor` runs against genuinely broken video files —
corrupted bytes, a zero-byte file — using the *real* `DeviceIdExtractor` /
`FrameExtractor` / OpenCV stack (not a stub), so this actually exercises
what happens when `cv2.VideoCapture` fails to open a file, which is exactly
the class of input Task 11's stress-testing requirement calls out
(corrupted videos, tiny videos) and that a WhatsApp forward can plausibly
deliver (a truncated download, a 0-byte placeholder before content arrives).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from instacore_sync.core.config import AppSettings
from instacore_sync.db.database import Database
from instacore_sync.db.repositories.hashes_repository import HashesRepository
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob
from instacore_sync.services.dedup.dedup_service import DedupService
from instacore_sync.services.hashing.hash_service import HashService
from instacore_sync.services.ocr.device_id_extractor import DeviceIdExtractor
from instacore_sync.services.pipeline import video_processor as video_processor_module
from instacore_sync.services.pipeline.video_processor import VideoProcessor


class _NeverCalledDrive:
    def get_or_create_device_folder(self, date_label: str, device_id: str) -> str:
        raise AssertionError("Drive must never be reached for a video OCR can't even open")

    def upload_file(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Drive must never be reached for a video OCR can't even open")

    def find_duplicate_by_hash(self, sha256: str):
        # The cross-process dedup check legitimately runs at the hashing
        # step, before OCR — a corrupted file can still be hashed, and
        # checking dedup first avoids wasting an OCR pass on a video
        # that's already a known duplicate. Only upload/folder creation
        # (the calls above) must never be reached for a video OCR can't
        # open.
        return None


class _NeverCalledSheets:
    def upsert_row(self, **kwargs):  # noqa: ANN003
        raise AssertionError("Sheets must never be reached for a video OCR can't even open")


@pytest.fixture(autouse=True)
def _fast_stability_check(monkeypatch):
    """Skip the real 1.5s file-stability wait — these test files are
    written once up front, not streamed incrementally, so there's nothing
    to actually wait for."""

    def _instant_stable(path: Path, **_kwargs) -> int:
        return path.stat().st_size

    monkeypatch.setattr(video_processor_module, "wait_until_stable", _instant_stable)


def _real_processor(tmp_path: Path, database: Database) -> VideoProcessor:
    settings = AppSettings()
    settings.processed_folder = str(tmp_path / "Processed")
    settings.needs_review_folder = str(tmp_path / "NeedsReview")
    settings.failed_folder = str(tmp_path / "Failed")
    # Bound the OCR pass so a broken file can't make this test slow even if
    # some code path doesn't fail as fast as expected.
    settings.ocr.max_seconds_scanned = 1.0
    settings.ocr.full_scan_on_low_confidence = False

    jobs_repo = JobsRepository(database)
    logs_repo = LogsRepository(database)
    dedup = DedupService(HashService(), HashesRepository(database))
    ocr = DeviceIdExtractor(settings.ocr)  # the REAL extractor, real OpenCV underneath

    return VideoProcessor(
        settings, ocr, dedup, _NeverCalledDrive(), _NeverCalledSheets(), jobs_repo, logs_repo
    )


def test_corrupted_video_routes_to_needs_review_not_a_crash(tmp_path: Path, database: Database) -> None:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    corrupted = watch_dir / "corrupted.mp4"
    corrupted.write_bytes(b"this is not a real mp4 container, just garbage bytes" * 50)

    processor = _real_processor(tmp_path, database)
    job = VideoJob(source_path=corrupted, original_filename="corrupted.mp4")

    result = processor.process(job)

    assert result.status == JobStatus.NEEDS_REVIEW
    assert result.source_path.parent == Path(processor._settings.needs_review_folder)
    assert result.source_path.exists()


def test_zero_byte_video_routes_to_needs_review_not_a_crash(tmp_path: Path, database: Database) -> None:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    empty = watch_dir / "empty.mp4"
    empty.write_bytes(b"")

    processor = _real_processor(tmp_path, database)
    job = VideoJob(source_path=empty, original_filename="empty.mp4")

    result = processor.process(job)

    assert result.status == JobStatus.NEEDS_REVIEW
    assert result.source_path.exists()


def test_processing_a_broken_video_never_raises_out_of_process(tmp_path: Path, database: Database) -> None:
    """The literal 'never stop processing' requirement: whatever happens
    inside, `.process()` must always return a job, never propagate an
    exception the caller (the upload worker pool) would have to handle."""
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    garbage = watch_dir / "garbage.mp4"
    garbage.write_bytes(bytes(range(256)) * 20)

    processor = _real_processor(tmp_path, database)
    job = VideoJob(source_path=garbage, original_filename="garbage.mp4")

    result = processor.process(job)  # must not raise

    assert result.status in (JobStatus.NEEDS_REVIEW, JobStatus.FAILED)
