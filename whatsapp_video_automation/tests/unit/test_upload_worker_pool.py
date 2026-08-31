"""Verifies the worker pool's retry-with-backoff behavior without touching
Drive/OCR — `_processor` is a stub whose `.process` result is scripted per
call, so we can assert retries happen exactly `retry_count` times and stop
as soon as a terminal (non-retryable) status is reached.

A retried job is rescheduled via `loop.call_later` rather than an in-worker
`asyncio.sleep` (see `upload_worker_pool.py` for why), which means
`queue.join()` alone is no longer a reliable "all retries finished" signal
for a job that failed and is still waiting out its backoff — `task_done()`
fires as soon as the *attempt* returns, before the delayed re-queue puts it
back. Tests that exercise retries poll `processor.call_count` instead.

A real `JobsRepository` (backed by the `database` fixture) is used rather
than a stub, so `test_backoff_window_is_persisted_as_queued_not_failed`
below can assert against the actual DB row — this is the regression test
for a real bug the concurrency stress test caught: the pool used to update
only the in-memory job + the (no-op in tests, Qt-signal-only in production)
event sink when scheduling a retry, never writing the QUEUED status to the
database. If the app closed during that backoff window, the job would sit
in the DB looking permanently FAILED and never be picked up again by
`PipelineOrchestrator`'s startup requeue.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from instacore_sync.core.config import UploadSettings
from instacore_sync.db.database import Database
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob
from instacore_sync.services.upload.upload_queue import UploadQueue
from instacore_sync.services.upload.upload_worker_pool import UploadWorkerPool


class _ScriptedProcessor:
    """Returns a pre-scripted status for each successive call to `.process`.

    Mirrors the one bit of real `VideoProcessor.process` behavior the pool
    depends on: incrementing `job.attempt_count` on every attempt.
    """

    def __init__(self, statuses: list[JobStatus]) -> None:
        self._statuses = list(statuses)
        self.call_count = 0

    def process(self, job: VideoJob, progress_callback=None) -> VideoJob:
        self.call_count += 1
        job.attempt_count += 1
        status = self._statuses[min(self.call_count - 1, len(self._statuses) - 1)]
        job.status = status
        return job


def _job() -> VideoJob:
    return VideoJob(source_path=Path("clip.mp4"), original_filename="clip.mp4")


async def _wait_for_call_count(processor: _ScriptedProcessor, expected: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while processor.call_count < expected:
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(
                f"Timed out waiting for call_count >= {expected} (got {processor.call_count})"
            )
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_successful_job_is_processed_once(database: Database) -> None:
    processor = _ScriptedProcessor([JobStatus.COMPLETED])
    settings = UploadSettings(max_concurrent=1, retry_count=3, retry_backoff_seconds=0.01)
    queue = UploadQueue()
    pool = UploadWorkerPool(settings, queue, processor, JobsRepository(database))

    pool.start()
    await queue.put(_job())
    await asyncio.wait_for(queue.join(), timeout=2.0)
    await pool.stop()

    assert processor.call_count == 1


@pytest.mark.asyncio
async def test_failed_job_retries_then_succeeds(database: Database) -> None:
    processor = _ScriptedProcessor([JobStatus.FAILED, JobStatus.FAILED, JobStatus.COMPLETED])
    settings = UploadSettings(max_concurrent=1, retry_count=5, retry_backoff_seconds=0.01)
    queue = UploadQueue()
    pool = UploadWorkerPool(settings, queue, processor, JobsRepository(database))

    pool.start()
    await queue.put(_job())
    await _wait_for_call_count(processor, 3)
    await pool.stop()

    assert processor.call_count == 3


@pytest.mark.asyncio
async def test_failed_job_stops_after_retry_count_exhausted(database: Database) -> None:
    processor = _ScriptedProcessor([JobStatus.FAILED])
    settings = UploadSettings(max_concurrent=1, retry_count=3, retry_backoff_seconds=0.01)
    queue = UploadQueue()
    pool = UploadWorkerPool(settings, queue, processor, JobsRepository(database))

    pool.start()
    await queue.put(_job())
    await _wait_for_call_count(processor, 3)
    await pool.stop()

    assert processor.call_count == 3  # exactly retry_count attempts, then gives up


@pytest.mark.asyncio
async def test_needs_review_status_is_not_retried(database: Database) -> None:
    processor = _ScriptedProcessor([JobStatus.NEEDS_REVIEW])
    settings = UploadSettings(max_concurrent=1, retry_count=5, retry_backoff_seconds=0.01)
    queue = UploadQueue()
    pool = UploadWorkerPool(settings, queue, processor, JobsRepository(database))

    pool.start()
    await queue.put(_job())
    await asyncio.wait_for(queue.join(), timeout=2.0)
    await pool.stop()

    assert processor.call_count == 1


@pytest.mark.asyncio
async def test_backoff_window_is_persisted_as_queued_not_failed(database: Database) -> None:
    """Regression test for the bug `test_stress_concurrency.py` caught:
    while a failed job is waiting out its backoff before a retry, the
    database row must show QUEUED (resumable on restart), not still show
    the stale terminal FAILED status from the attempt that just failed."""
    processor = _ScriptedProcessor([JobStatus.FAILED, JobStatus.COMPLETED])
    settings = UploadSettings(max_concurrent=1, retry_count=5, retry_backoff_seconds=1.0)
    queue = UploadQueue()
    jobs_repo = JobsRepository(database)
    pool = UploadWorkerPool(settings, queue, processor, jobs_repo)

    job = _job()
    pool.start()
    await queue.put(job)
    await _wait_for_call_count(processor, 1)  # the first (failing) attempt has returned
    await asyncio.sleep(0.1)  # let the pool's post-attempt bookkeeping run

    persisted = jobs_repo.get(job.job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.QUEUED  # not FAILED — still mid-backoff, will retry

    await pool.stop()


@pytest.mark.asyncio
async def test_retry_does_not_hold_worker_slot_during_backoff(database: Database) -> None:
    """The regression this whole redesign targets: while one job is in its
    backoff window, the worker that failed it must be free to pick up a
    different, independent job from the queue — not sleep-blocked on the
    first job's retry."""
    slow_processor = _ScriptedProcessor([JobStatus.FAILED, JobStatus.COMPLETED])
    fast_processor_calls: list[str] = []

    class _RoutingProcessor:
        """Dispatches to a different scripted outcome per job filename, so
        one job (the "flaky" one) fails+retries while another (the "clean"
        one) should complete immediately even though it's queued right
        after the flaky one and the pool has only one worker."""

        def process(self, job: VideoJob, progress_callback=None) -> VideoJob:
            if job.original_filename == "flaky.mp4":
                return slow_processor.process(job, progress_callback)
            fast_processor_calls.append(job.original_filename)
            job.attempt_count += 1
            job.status = JobStatus.COMPLETED
            return job

    settings = UploadSettings(max_concurrent=1, retry_count=5, retry_backoff_seconds=1.0)
    queue = UploadQueue()
    pool = UploadWorkerPool(settings, queue, _RoutingProcessor(), JobsRepository(database))

    pool.start()
    await queue.put(VideoJob(source_path=Path("flaky.mp4"), original_filename="flaky.mp4"))
    await queue.put(VideoJob(source_path=Path("clean.mp4"), original_filename="clean.mp4"))

    # The flaky job's backoff is 1s; if the worker were blocked sleeping
    # through it, "clean.mp4" would not be processed within a much shorter
    # window. With the fix, the single worker fails flaky.mp4 once,
    # schedules its retry, and immediately moves on to clean.mp4.
    await asyncio.wait_for(_wait_for_processed(fast_processor_calls, "clean.mp4"), timeout=0.5)
    await pool.stop()

    assert "clean.mp4" in fast_processor_calls


async def _wait_for_processed(calls: list[str], name: str) -> None:
    while name not in calls:
        await asyncio.sleep(0.01)
