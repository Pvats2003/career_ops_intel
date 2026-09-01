"""Tests the manual controls added to `PipelineOrchestrator`: pause/resume
uploads and the Queue view's per-job Retry action.

Uses a real orchestrator (real asyncio worker pool, real watcher on an
empty temp folder, real SQLite-backed repositories) with Drive/Sheets/auth
faked out, so this exercises the actual thread-safety-sensitive code paths
(the worker pool's pause gate, job re-enqueue) rather than a mocked
approximation of them.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from instacore_sync.core.config import AppSettings
from instacore_sync.core.exceptions import DriveAuthError
from instacore_sync.db.database import Database
from instacore_sync.db.repositories.hashes_repository import HashesRepository
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob
from instacore_sync.services.dedup.dedup_service import DedupService
from instacore_sync.services.hashing.hash_service import HashService
from instacore_sync.services.ocr.engine_factory import OcrEngineFactory
from instacore_sync.services.pipeline.pipeline_orchestrator import PipelineOrchestrator


class _StubGoogleAuth:
    status = "signed_out"
    account_email = None

    def get_credentials(self, *, interactive: bool = False):
        raise DriveAuthError("no credentials configured in this test")


@pytest.fixture
def orchestrator(tmp_path: Path, database: Database):
    settings = AppSettings()
    settings.watch_folder = str(tmp_path / "watch")  # left empty — nothing to discover
    settings.processed_folder = str(tmp_path / "Processed")
    settings.needs_review_folder = str(tmp_path / "NeedsReview")
    settings.failed_folder = str(tmp_path / "Failed")
    settings.app.jobs_retention_days = 0  # skip pruning for this test

    jobs_repo = JobsRepository(database)
    logs_repo = LogsRepository(database)
    dedup = DedupService(HashService(), HashesRepository(database))
    ocr_factory = OcrEngineFactory(settings.ocr)

    return PipelineOrchestrator(
        settings, jobs_repo, logs_repo, dedup, ocr_factory,
        _StubGoogleAuth(), MagicMock(), MagicMock(),
    )


@pytest.mark.asyncio
async def test_pause_prevents_new_jobs_from_starting(orchestrator: PipelineOrchestrator) -> None:
    await orchestrator.start()
    try:
        orchestrator.pause_uploads()
        assert orchestrator.is_paused is True

        job = VideoJob(source_path=Path("/tmp/does-not-matter.mp4"), original_filename="clip.mp4")
        orchestrator._jobs_repo.upsert(job)
        orchestrator._enqueue(job)

        await asyncio.sleep(0.05)  # give the (paused) pool a chance to misbehave, if it would

        # Still queued, not picked up — the worker pool must not have
        # pulled it off the queue while paused.
        assert orchestrator._queue.waiting_count == 1
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_resume_allows_worker_to_continue(orchestrator: PipelineOrchestrator) -> None:
    await orchestrator.start()
    try:
        orchestrator.pause_uploads()
        job = VideoJob(source_path=Path("/tmp/does-not-matter.mp4"), original_filename="clip.mp4")
        orchestrator._enqueue(job)
        await asyncio.sleep(0.05)
        assert orchestrator._queue.waiting_count == 1

        orchestrator.resume_uploads()
        assert orchestrator.is_paused is False

        deadline = asyncio.get_event_loop().time() + 2.0
        while orchestrator._queue.waiting_count > 0 and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.02)

        # The worker picked it up (it'll fail fast since source_path
        # doesn't exist — that's fine, we're only testing that pausing
        # doesn't permanently strand queued work).
        assert orchestrator._queue.waiting_count == 0
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_retry_job_reenqueues_failed_job_with_reset_state(orchestrator: PipelineOrchestrator) -> None:
    await orchestrator.start()
    try:
        orchestrator.pause_uploads()  # keep it from being picked up mid-assertion

        video = Path(orchestrator._settings.failed_folder) / "clip.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"data")

        job = VideoJob(source_path=video, original_filename="clip.mp4", status=JobStatus.FAILED)
        job.attempt_count = 3
        job.last_error = "boom"
        orchestrator._jobs_repo.upsert(job)

        result = orchestrator.retry_job(job.job_id)

        assert result is True
        assert orchestrator._queue.waiting_count == 1
        refetched = orchestrator._jobs_repo.get(job.job_id)
        assert refetched is not None
        assert refetched.status == JobStatus.QUEUED
        assert refetched.attempt_count == 0
        assert refetched.last_error is None
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_retry_job_returns_false_for_unknown_job(orchestrator: PipelineOrchestrator) -> None:
    await orchestrator.start()
    try:
        assert orchestrator.retry_job("does-not-exist") is False
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_retry_job_returns_false_when_source_file_missing(orchestrator: PipelineOrchestrator) -> None:
    await orchestrator.start()
    try:
        job = VideoJob(
            source_path=Path("/tmp/definitely-does-not-exist-anywhere.mp4"),
            original_filename="ghost.mp4",
            status=JobStatus.FAILED,
        )
        orchestrator._jobs_repo.upsert(job)

        assert orchestrator.retry_job(job.job_id) is False
        assert orchestrator._queue.waiting_count == 0
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_retry_job_rejects_completed_job(orchestrator: PipelineOrchestrator) -> None:
    await orchestrator.start()
    try:
        job = VideoJob(
            source_path=Path("/tmp/whatever.mp4"), original_filename="done.mp4", status=JobStatus.COMPLETED
        )
        orchestrator._jobs_repo.upsert(job)

        assert orchestrator.retry_job(job.job_id) is False
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_resolve_needs_review_applies_manual_device_id_and_requeues(
    orchestrator: PipelineOrchestrator,
) -> None:
    await orchestrator.start()
    try:
        orchestrator.pause_uploads()

        video = Path(orchestrator._settings.needs_review_folder) / "unclear.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"data")

        job = VideoJob(
            source_path=video,
            original_filename="unclear.mp4",
            status=JobStatus.NEEDS_REVIEW,
            ocr_confidence=0.2,
            last_error="low confidence",
        )
        orchestrator._jobs_repo.upsert(job)

        result = orchestrator.resolve_needs_review(job.job_id, "IC-188")

        assert result is True
        refetched = orchestrator._jobs_repo.get(job.job_id)
        assert refetched is not None
        assert refetched.device_id == "IC-188"
        assert refetched.manually_confirmed is True
        assert refetched.status == JobStatus.QUEUED
        assert refetched.last_error is None
        assert orchestrator._queue.waiting_count == 1
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_resolve_needs_review_rejects_invalid_device_id(orchestrator: PipelineOrchestrator) -> None:
    await orchestrator.start()
    try:
        video = Path(orchestrator._settings.needs_review_folder) / "unclear.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"data")
        job = VideoJob(source_path=video, original_filename="unclear.mp4", status=JobStatus.NEEDS_REVIEW)
        orchestrator._jobs_repo.upsert(job)

        assert orchestrator.resolve_needs_review(job.job_id, "../../etc/passwd") is False
        refetched = orchestrator._jobs_repo.get(job.job_id)
        assert refetched is not None
        assert refetched.device_id is None
        assert refetched.status == JobStatus.NEEDS_REVIEW  # untouched
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_resolve_needs_review_rejects_non_needs_review_job(orchestrator: PipelineOrchestrator) -> None:
    await orchestrator.start()
    try:
        job = VideoJob(
            source_path=Path("/tmp/whatever.mp4"), original_filename="done.mp4", status=JobStatus.COMPLETED
        )
        orchestrator._jobs_repo.upsert(job)

        assert orchestrator.resolve_needs_review(job.job_id, "IC-188") is False
    finally:
        await orchestrator.stop()


class _HangingIfInteractiveGoogleAuth:
    """Stands in for the real GoogleAuthService: a non-interactive call
    fails fast (no stored token in this test); an interactive call raises
    loudly instead of actually hanging (a real `flow.run_local_server(...)`
    would block on a browser that never arrives, which we don't want to
    reproduce in a fast test suite) — either way, this fails the test the
    moment the interactive path is reached from automatic code. This is
    the regression test for a real startup-hang bug: `PipelineOrchestrator
    .start()` used to call the *interactive* path unconditionally, so any
    of 500 installs without a valid stored token would never get past
    `start()` — the folder watcher and upload pool would simply never
    start, with no error, no timeout, nothing in the UI to explain why
    videos just weren't being picked up.
    """

    status = "signed_out"
    account_email = None

    def __init__(self) -> None:
        self.interactive_calls = 0
        self.non_interactive_calls = 0

    def get_credentials(self, *, interactive: bool = False):
        if interactive:
            self.interactive_calls += 1
            raise AssertionError(
                "get_credentials(interactive=True) must never be called from an "
                "automatic/background code path — only an explicit user action"
            )
        self.non_interactive_calls += 1
        raise DriveAuthError("no stored token in this test")


@pytest.fixture
def orchestrator_with_hanging_auth(tmp_path: Path, database: Database):
    settings = AppSettings()
    settings.watch_folder = str(tmp_path / "watch")
    settings.processed_folder = str(tmp_path / "Processed")
    settings.needs_review_folder = str(tmp_path / "NeedsReview")
    settings.failed_folder = str(tmp_path / "Failed")
    settings.app.jobs_retention_days = 0

    jobs_repo = JobsRepository(database)
    logs_repo = LogsRepository(database)
    dedup = DedupService(HashService(), HashesRepository(database))
    ocr_factory = OcrEngineFactory(settings.ocr)
    google_auth = _HangingIfInteractiveGoogleAuth()

    orchestrator = PipelineOrchestrator(
        settings, jobs_repo, logs_repo, dedup, ocr_factory, google_auth, MagicMock(), MagicMock()
    )
    return orchestrator, google_auth


@pytest.mark.asyncio
async def test_start_never_attempts_interactive_sign_in(orchestrator_with_hanging_auth) -> None:
    orchestrator, google_auth = orchestrator_with_hanging_auth
    try:
        await asyncio.wait_for(orchestrator.start(), timeout=2.0)  # must not hang
    finally:
        await orchestrator.stop()

    assert google_auth.non_interactive_calls == 1
    assert google_auth.interactive_calls == 0


class _RecordingGoogleAuth:
    """Records exactly which mode `get_credentials` was called with, and
    always fails (no real OAuth in this test) — but as a plain
    DriveAuthError rather than raising loudly, since this fake is used to
    verify `sign_in_interactively` correctly uses the interactive path and
    reports (rather than propagates) the eventual failure."""

    status = "signed_out"
    account_email = None

    def __init__(self) -> None:
        self.calls: list[bool] = []

    def get_credentials(self, *, interactive: bool = False):
        self.calls.append(interactive)
        raise DriveAuthError("no real OAuth in this test")


@pytest.fixture
def orchestrator_with_recording_auth(tmp_path: Path, database: Database):
    settings = AppSettings()
    settings.watch_folder = str(tmp_path / "watch")
    settings.processed_folder = str(tmp_path / "Processed")
    settings.needs_review_folder = str(tmp_path / "NeedsReview")
    settings.failed_folder = str(tmp_path / "Failed")
    settings.app.jobs_retention_days = 0

    jobs_repo = JobsRepository(database)
    logs_repo = LogsRepository(database)
    dedup = DedupService(HashService(), HashesRepository(database))
    ocr_factory = OcrEngineFactory(settings.ocr)
    google_auth = _RecordingGoogleAuth()

    orchestrator = PipelineOrchestrator(
        settings, jobs_repo, logs_repo, dedup, ocr_factory, google_auth, MagicMock(), MagicMock()
    )
    return orchestrator, google_auth


@pytest.mark.asyncio
async def test_sign_in_interactively_uses_the_interactive_path(orchestrator_with_recording_auth) -> None:
    """The one path allowed to call interactive=True — verifies it's wired
    through, and that a failure there is reported rather than raised out
    of the orchestrator (this runs from a UI button click, not something
    with a try/except wrapped around it by the caller)."""
    orchestrator, google_auth = orchestrator_with_recording_auth
    try:
        await orchestrator.start()
        assert google_auth.calls == [False]  # start()'s own probe: always silent

        await orchestrator.sign_in_interactively()  # must not raise, even though it fails

        assert google_auth.calls == [False, True]
    finally:
        await orchestrator.stop()
