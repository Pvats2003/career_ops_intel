"""Verifies the worker pool's retry-with-backoff behavior without touching
Drive/OCR — `_processor` is a stub whose `.process` result is scripted per
call, so we can assert retries happen exactly `retry_count` times and stop
as soon as a terminal (non-retryable) status is reached."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from instacore_sync.core.config import UploadSettings
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob
from instacore_sync.services.upload.upload_queue import UploadQueue
from instacore_sync.services.upload.upload_worker_pool import UploadWorkerPool


class _ScriptedProcessor:
    """Returns a pre-scripted status for each successive call to `.process`."""

    def __init__(self, statuses: list[JobStatus]) -> None:
        self._statuses = list(statuses)
        self.call_count = 0

    def process(self, job: VideoJob, progress_callback=None) -> VideoJob:
        self.call_count += 1
        status = self._statuses[min(self.call_count - 1, len(self._statuses) - 1)]
        job.status = status
        return job


def _job() -> VideoJob:
    return VideoJob(source_path=Path("clip.mp4"), original_filename="clip.mp4")


@pytest.mark.asyncio
async def test_successful_job_is_processed_once() -> None:
    processor = _ScriptedProcessor([JobStatus.COMPLETED])
    settings = UploadSettings(max_concurrent=1, retry_count=3, retry_backoff_seconds=0.01)
    queue = UploadQueue()
    pool = UploadWorkerPool(settings, queue, processor)

    pool.start()
    await queue.put(_job())
    await asyncio.wait_for(queue.join(), timeout=2.0)
    await pool.stop()

    assert processor.call_count == 1


@pytest.mark.asyncio
async def test_failed_job_retries_then_succeeds() -> None:
    processor = _ScriptedProcessor([JobStatus.FAILED, JobStatus.FAILED, JobStatus.COMPLETED])
    settings = UploadSettings(max_concurrent=1, retry_count=5, retry_backoff_seconds=0.01)
    queue = UploadQueue()
    pool = UploadWorkerPool(settings, queue, processor)

    pool.start()
    await queue.put(_job())
    await asyncio.wait_for(queue.join(), timeout=5.0)
    await pool.stop()

    assert processor.call_count == 3


@pytest.mark.asyncio
async def test_failed_job_stops_after_retry_count_exhausted() -> None:
    processor = _ScriptedProcessor([JobStatus.FAILED])
    settings = UploadSettings(max_concurrent=1, retry_count=3, retry_backoff_seconds=0.01)
    queue = UploadQueue()
    pool = UploadWorkerPool(settings, queue, processor)

    pool.start()
    await queue.put(_job())
    await asyncio.wait_for(queue.join(), timeout=5.0)
    await pool.stop()

    assert processor.call_count == 3  # exactly retry_count attempts, then gives up


@pytest.mark.asyncio
async def test_needs_review_status_is_not_retried() -> None:
    processor = _ScriptedProcessor([JobStatus.NEEDS_REVIEW])
    settings = UploadSettings(max_concurrent=1, retry_count=5, retry_backoff_seconds=0.01)
    queue = UploadQueue()
    pool = UploadWorkerPool(settings, queue, processor)

    pool.start()
    await queue.put(_job())
    await asyncio.wait_for(queue.join(), timeout=2.0)
    await pool.stop()

    assert processor.call_count == 1
