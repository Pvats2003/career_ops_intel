"""Stress/concurrency test: drives a batch of videos through a real
`PipelineOrchestrator` + `UploadWorkerPool` (real asyncio concurrency, real
SQLite-backed repositories, real folder-move semantics) with fast fakes for
OCR/Drive/Sheets, verifying every job reaches a correct terminal state with
none lost, duplicated, or stuck — under load and under injected random
transient failures.

This is a scaled-down proxy for the product requirement to validate
"200-500 videos/day, 10-20 concurrent uploads, random failures": generating
and encoding 500 real video files and driving them through real network
calls isn't something a fast, deterministic test suite should do, but the
exact same orchestrator/queue/worker-pool code path that would run at that
scale runs here — a batch size in the tens with induced concurrency and
randomness stresses the same races (double-processing, lost jobs, deadlock
between paused/retrying workers) that would only show up intermittently at
full scale, just faster and more reliably.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

import pytest

from instacore_sync.core.config import AppSettings
from instacore_sync.core.exceptions import DriveApiError, DriveAuthError
from instacore_sync.db.database import Database
from instacore_sync.db.repositories.hashes_repository import HashesRepository
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.domain.enums import JobStatus, OcrEngineName
from instacore_sync.domain.models import UploadResult, VideoJob
from instacore_sync.services.dedup.dedup_service import DedupService
from instacore_sync.services.hashing.hash_service import HashService
from instacore_sync.services.ocr.engine_factory import OcrEngineFactory
from instacore_sync.services.pipeline import video_processor as video_processor_module
from instacore_sync.services.pipeline.pipeline_orchestrator import PipelineOrchestrator

_BATCH_SIZE = 60  # scaled proxy for "200-500/day" — see module docstring


@pytest.fixture(autouse=True)
def _fast_stability_check(monkeypatch):
    """Skip the real 1.5s per-file stability wait — these test files are
    written once up front, not streamed incrementally, so waiting for them
    to "stop changing size" would only add deadweight time to this already
    concurrency-heavy test."""

    def _instant_stable(path: Path, **_kwargs) -> int:
        return path.stat().st_size

    monkeypatch.setattr(video_processor_module, "wait_until_stable", _instant_stable)


class _StubGoogleAuth:
    status = "signed_out"
    account_email = None

    def get_credentials(self):
        raise DriveAuthError("no credentials configured in this test")


class _FlakyDrive:
    """Fails a configurable fraction of upload calls with a transient-style
    error (simulating "no internet" / a Drive API timeout mid-batch), then
    succeeds — models exactly the "random failures" + "Google API timeout"
    stress scenarios from the product spec."""

    def __init__(self, failure_rate: float, seed: int = 0) -> None:
        self._failure_rate = failure_rate
        self._rng = random.Random(seed)
        self.upload_attempts = 0
        self.successful_uploads = 0

    def get_or_create_device_folder(self, date_label: str, device_id: str) -> str:
        return f"folder-{date_label}-{device_id}"

    def upload_file(self, path: Path, folder_id: str, *, chunk_size_mb: int, progress_callback=None):
        self.upload_attempts += 1
        if self._rng.random() < self._failure_rate:
            raise DriveApiError("simulated network interruption / Drive API timeout")
        if progress_callback:
            progress_callback(path.stat().st_size, path.stat().st_size)
        self.successful_uploads += 1
        return UploadResult(
            file_id=f"file-{self.upload_attempts}",
            web_view_link=f"https://drive.google.com/file/d/file-{self.upload_attempts}/view",
            folder_id=folder_id,
            bytes_uploaded=path.stat().st_size,
            duration_seconds=0.001,
        )


class _FastSheets:
    def __init__(self) -> None:
        self.rows = 0

    def upsert_row(self, **kwargs):  # noqa: ANN003
        from instacore_sync.domain.models import SheetUpdateResult

        self.rows += 1
        return SheetUpdateResult(spreadsheet_id="sheet-1", row_number=self.rows, created_new_row=True)


class _FastOcr:
    """Stands in for `DeviceIdExtractor` itself (not just an engine) — this
    test's whole point is queue/worker-pool concurrency, not OCR frame
    decoding, and the synthetic "video" files below are just distinct
    byte content, not valid mp4 containers `cv2.VideoCapture` could open.
    Real OCR-against-real-video correctness is covered by
    test_device_id_extractor.py and test_video_processor_bad_files.py."""

    def extract(self, video_path: Path):
        from instacore_sync.domain.models import DeviceIdExtraction

        return DeviceIdExtraction(device_id="IC-1", confidence=0.99, engine_used=OcrEngineName.TESSERACT)


@pytest.fixture
def orchestrator_factory(tmp_path: Path, database: Database):
    def _build(
        failure_rate: float, retry_count: int = 6, retry_backoff_seconds: float = 0.02
    ) -> tuple[PipelineOrchestrator, _FlakyDrive]:
        settings = AppSettings()
        settings.watch_folder = str(tmp_path / "watch")
        settings.processed_folder = str(tmp_path / "Processed")
        settings.needs_review_folder = str(tmp_path / "NeedsReview")
        settings.failed_folder = str(tmp_path / "Failed")
        settings.app.jobs_retention_days = 0
        settings.uploads.max_concurrent = 12  # the product's real default
        settings.uploads.retry_count = retry_count
        settings.uploads.retry_backoff_seconds = retry_backoff_seconds
        settings.ocr.min_confidence = 0.5

        jobs_repo = JobsRepository(database)
        logs_repo = LogsRepository(database)
        dedup = DedupService(HashService(), HashesRepository(database))
        drive = _FlakyDrive(failure_rate=failure_rate)
        ocr_engine_factory = OcrEngineFactory(settings.ocr)  # real, but never actually invoked below

        orchestrator = PipelineOrchestrator(
            settings, jobs_repo, logs_repo, dedup, ocr_engine_factory,
            _StubGoogleAuth(), drive, _FastSheets(),
        )
        orchestrator._device_id_extractor = _FastOcr()
        orchestrator._processor._ocr = _FastOcr()
        return orchestrator, drive

    return _build


def _make_batch(tmp_path: Path, count: int) -> list[Path]:
    # Deliberately NOT inside settings.watch_folder: the orchestrator's
    # start() launches a real FolderWatcher on that directory, and if these
    # files appeared there after start(), the watcher would independently
    # rediscover and enqueue them a second time — a real race, not a test
    # artifact. Jobs are enqueued directly (see the tests below), so the
    # files only need to exist somewhere stable on disk.
    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir(exist_ok=True)
    paths = []
    for i in range(count):
        p = incoming_dir / f"clip_{i:04d}.mp4"
        p.write_bytes(f"unique content for clip {i}".encode() * 20)  # distinct hash per file
        paths.append(p)
    return paths


@pytest.mark.asyncio
async def test_batch_of_videos_all_reach_a_terminal_state_with_none_lost(
    tmp_path: Path, orchestrator_factory
) -> None:
    orchestrator, drive = orchestrator_factory(failure_rate=0.0)
    await orchestrator.start()
    try:
        paths = _make_batch(tmp_path, _BATCH_SIZE)
        for path in paths:
            job = VideoJob(source_path=path, original_filename=path.name)
            orchestrator._jobs_repo.upsert(job)
            orchestrator._enqueue(job)

        deadline = asyncio.get_event_loop().time() + 15.0
        while orchestrator._queue.waiting_count > 0 or orchestrator._worker_pool.active_count > 0:
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail("Batch did not drain within the timeout — a job is stuck")
            await asyncio.sleep(0.05)

        completed = orchestrator._jobs_repo.list_by_status(JobStatus.COMPLETED)
        assert len(completed) == _BATCH_SIZE, (
            f"expected all {_BATCH_SIZE} jobs COMPLETED, got {len(completed)} "
            f"(counts: {orchestrator._jobs_repo.counts_by_status()})"
        )
        # Every source file actually landed in Processed/, none left behind
        # or double-moved.
        processed_files = list(Path(orchestrator._settings.processed_folder).glob("*.mp4"))
        assert len(processed_files) == _BATCH_SIZE
        assert drive.successful_uploads == _BATCH_SIZE
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_batch_with_random_transient_failures_all_eventually_complete(
    tmp_path: Path, orchestrator_factory
) -> None:
    """~20% of upload attempts fail transiently (simulating flaky
    internet / Google API timeouts) — every job must still reach COMPLETED
    via the retry-with-backoff path, and the worker pool must not
    deadlock or strand jobs while others are mid-backoff (the exact
    regression `upload_worker_pool.py`'s redesign targets)."""
    # Two things have to both stay bounded here, not just retry_count:
    #   1. P(a job fails every attempt) = failure_rate**retry_count must be
    #      negligible across 30 independent jobs, or this test is flaky by
    #      construction regardless of correct code.
    #   2. Backoff is exponential (base * 2**(attempt-1)) and — deliberately
    #      — uncapped in `upload_worker_pool.py` (see the audit report's
    #      Future Recommendations): a job needing several consecutive
    #      retries costs cumulative wait time that grows fast even at a
    #      "keep it fast" base. An earlier version of this test used
    #      base=0.02s/retry_count=12 (worst backoff alone ~=41s) and was
    #      genuinely flaky under this sandbox's variable scheduling load —
    #      not a pipeline bug, a test-parameter bug (conflating "will
    #      eventually succeed" with "will succeed inside an arbitrary short
    #      deadline"). base=0.01s/retry_count=8 keeps worst-case cumulative
    #      backoff for one job at ~0.01*(2**8-1) ~= 2.55s, comfortably
    #      inside the deadline below even under heavy scheduling jitter.
    # At failure_rate=0.20, retry_count=8: exhaustion probability is
    # 0.20**8 ~= 2.6e-6 (~7.7e-5, i.e. ~0.008%, across 30 jobs) — genuinely
    # negligible.
    orchestrator, drive = orchestrator_factory(
        failure_rate=0.20, retry_count=8, retry_backoff_seconds=0.01
    )
    await orchestrator.start()
    try:
        paths = _make_batch(tmp_path, 30)
        for path in paths:
            job = VideoJob(source_path=path, original_filename=path.name)
            orchestrator._jobs_repo.upsert(job)
            orchestrator._enqueue(job)

        deadline = asyncio.get_event_loop().time() + 30.0
        while True:
            counts = orchestrator._jobs_repo.counts_by_status()
            terminal = counts.get(JobStatus.COMPLETED, 0) + counts.get(JobStatus.FAILED, 0)
            if terminal >= 30:
                break
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail(f"Batch did not settle within the timeout (counts: {counts})")
            await asyncio.sleep(0.05)

        counts = orchestrator._jobs_repo.counts_by_status()
        assert counts.get(JobStatus.COMPLETED, 0) == 30, f"counts: {counts}"
        assert drive.upload_attempts > drive.successful_uploads  # retries genuinely happened
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_duplicate_content_in_the_same_batch_uploads_only_once(
    tmp_path: Path, orchestrator_factory
) -> None:
    orchestrator, drive = orchestrator_factory(failure_rate=0.0)
    await orchestrator.start()
    try:
        incoming_dir = tmp_path / "incoming"  # see _make_batch's comment on why not watch_folder
        incoming_dir.mkdir(exist_ok=True)
        shared_content = b"identical bytes across three separately-named files" * 20

        jobs = []
        for name in ("a.mp4", "b.mp4", "c.mp4"):
            path = incoming_dir / name
            path.write_bytes(shared_content)
            job = VideoJob(source_path=path, original_filename=name)
            orchestrator._jobs_repo.upsert(job)
            orchestrator._enqueue(job)
            jobs.append(job)

        # NOT "queue empty and no active worker" — a job that lost the
        # dedup race gets routed through the retry/backoff path (see
        # DedupService.claim_for_upload), which means it's briefly neither
        # queued nor active while it waits out its backoff. Poll DB status
        # instead, the same fix test_upload_worker_pool.py needed for the
        # same underlying reason.
        deadline = asyncio.get_event_loop().time() + 10.0
        while True:
            counts = orchestrator._jobs_repo.counts_by_status()
            terminal = counts.get(JobStatus.COMPLETED, 0) + counts.get(JobStatus.DUPLICATE, 0)
            if terminal >= 3:
                break
            if asyncio.get_event_loop().time() > deadline:
                pytest.fail(f"Batch did not settle within the timeout (counts: {counts})")
            await asyncio.sleep(0.02)

        counts = orchestrator._jobs_repo.counts_by_status()
        assert counts.get(JobStatus.COMPLETED, 0) == 1
        assert counts.get(JobStatus.DUPLICATE, 0) == 2
        assert drive.successful_uploads == 1  # only the first upload actually hit Drive
    finally:
        await orchestrator.stop()
