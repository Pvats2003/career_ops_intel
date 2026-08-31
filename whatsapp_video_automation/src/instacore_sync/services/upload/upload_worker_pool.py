"""Bounded-concurrency async worker pool that drains `UploadQueue`.

`VideoProcessor.process` is synchronous and CPU/IO-bound (OpenCV, OCR,
Google API calls), so each worker offloads it to a shared
`ThreadPoolExecutor` via `loop.run_in_executor` — this is what gives us
"10-20 simultaneous uploads" without blocking the asyncio event loop or the
Qt UI thread. Failures are retried with exponential backoff up to
`retry_count`; only truly exhausted jobs are reported as FAILED.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from functools import partial

from instacore_sync.core.config import UploadSettings
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob
from instacore_sync.services.pipeline.events import NullEventSink, PipelineEventSink
from instacore_sync.services.pipeline.video_processor import VideoProcessor
from instacore_sync.services.upload.upload_queue import UploadQueue

logger = get_logger(__name__)

# Statuses VideoProcessor can leave a job in that should NOT be retried —
# they are either terminal-success, or require a human, not a re-run.
_NON_RETRYABLE = frozenset({JobStatus.COMPLETED, JobStatus.DUPLICATE, JobStatus.NEEDS_REVIEW})


class UploadWorkerPool:
    def __init__(
        self,
        settings: UploadSettings,
        queue: UploadQueue,
        processor: VideoProcessor,
        event_sink: PipelineEventSink | None = None,
    ) -> None:
        self._settings = settings
        self._queue = queue
        self._processor = processor
        self._events = event_sink or NullEventSink()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent, thread_name_prefix="upload-worker"
        )
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._active_count = 0
        self._active_lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return self._active_count

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._tasks = [
            loop.create_task(self._worker_loop(i)) for i in range(self._settings.max_concurrent)
        ]
        logger.info("upload_pool.started", workers=self._settings.max_concurrent)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("upload_pool.stopped")

    async def _worker_loop(self, worker_index: int) -> None:
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                job = await self._queue.get()
            except asyncio.CancelledError:
                break

            async with self._active_lock:
                self._active_count += 1
            try:
                await self._process_with_retry(loop, job)
            finally:
                async with self._active_lock:
                    self._active_count -= 1
                self._queue.task_done()

    async def _process_with_retry(self, loop: asyncio.AbstractEventLoop, job: VideoJob) -> None:
        last_speed_sample = (time.monotonic(), 0)

        def progress_callback(j: VideoJob, uploaded: int, total: int) -> None:
            nonlocal last_speed_sample
            now, prev_bytes = last_speed_sample
            elapsed = time.monotonic() - now
            if elapsed >= 0.5:
                delta = uploaded - prev_bytes
                j.upload_speed_bps = delta / elapsed if elapsed > 0 else 0.0
                last_speed_sample = (time.monotonic(), uploaded)
            j.bytes_uploaded = uploaded
            self._events.on_job_updated(j)

        for attempt in range(1, self._settings.retry_count + 1):
            fn = partial(self._processor.process, job, progress_callback)
            job = await loop.run_in_executor(self._executor, fn)

            if job.status in _NON_RETRYABLE:
                return
            if job.status != JobStatus.FAILED:
                return  # unexpected but not a retryable failure state

            if attempt >= self._settings.retry_count:
                logger.error(
                    "upload_pool.retries_exhausted",
                    job_id=job.job_id,
                    filename=job.original_filename,
                    error=job.last_error,
                )
                self._events.on_job_updated(job)
                return

            backoff = self._settings.retry_backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "upload_pool.retrying",
                job_id=job.job_id,
                attempt=attempt,
                backoff_seconds=backoff,
                error=job.last_error,
            )
            job.status = JobStatus.QUEUED
            self._events.on_job_updated(job)
            await asyncio.sleep(backoff)
