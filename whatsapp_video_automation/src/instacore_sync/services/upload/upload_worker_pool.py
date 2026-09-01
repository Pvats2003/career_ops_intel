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
import random
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from functools import partial

from instacore_sync.core.config import UploadSettings
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob
from instacore_sync.services.pipeline.events import NullEventSink, PipelineEventSink
from instacore_sync.services.pipeline.video_processor import VideoProcessor
from instacore_sync.services.upload.upload_queue import UploadQueue

logger = get_logger(__name__)

# Caps the job-level retry backoff the same way utils.retry's
# google_api_retry/network_retry cap the single-API-call layer (both use
# wait_exponential_jitter(..., max=60.0)) — an unbounded exponential here
# would otherwise grow to hours for a job stuck near retry_count.
_MAX_JOB_RETRY_BACKOFF_SECONDS = 60.0


class UploadWorkerPool:
    def __init__(
        self,
        settings: UploadSettings,
        queue: UploadQueue,
        processor: VideoProcessor,
        jobs_repo: JobsRepository,
        event_sink: PipelineEventSink | None = None,
    ) -> None:
        self._settings = settings
        self._queue = queue
        self._processor = processor
        self._jobs_repo = jobs_repo
        self._events = event_sink or NullEventSink()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent, thread_name_prefix="upload-worker"
        )
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._active_count = 0
        self._active_lock = asyncio.Lock()
        # Set = "go", cleared = "paused". Workers gate on this *before*
        # pulling their next job, so pausing is graceful: whatever's already
        # in flight finishes normally, nothing new starts until resumed.
        self._resume_event = asyncio.Event()
        self._resume_event.set()

    @property
    def active_count(self) -> int:
        return self._active_count

    @property
    def is_paused(self) -> bool:
        return not self._resume_event.is_set()

    @property
    def is_running(self) -> bool:
        """Whether `start()` has been called and `stop()` hasn't — the
        Health Check page's "Background Workers" row."""
        return self._running

    def pause(self) -> None:
        if self._resume_event.is_set():
            self._resume_event.clear()
            logger.info("upload_pool.paused")

    def resume(self) -> None:
        if not self._resume_event.is_set():
            self._resume_event.set()
            logger.info("upload_pool.resumed")

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
                await self._resume_event.wait()
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
        """Run one processing attempt; on a retryable failure, schedule a
        delayed re-queue instead of blocking this worker through the
        backoff delay.

        The previous implementation retried in a loop with
        `await asyncio.sleep(backoff)` *inside* the worker — that held the
        worker's queue slot for the entire backoff window, so a burst of
        failures (e.g. a brief internet outage affecting many uploads at
        once) could tie up most/all of the pool in sleeping retries while
        newly-queued, perfectly-uploadable videos sat waiting behind them.
        Scheduling the retry via `loop.call_later` and returning
        immediately frees the worker to pick up the next queued job right
        away; the failed job re-enters the queue as a fresh `get()` once
        its backoff elapses.
        """
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

        fn = partial(self._processor.process, job, progress_callback)
        job = await loop.run_in_executor(self._executor, fn)

        if job.status != JobStatus.FAILED:
            return  # COMPLETED / DUPLICATE / NEEDS_REVIEW are all terminal

        if job.permanent_failure:
            # Classified by VideoProcessor as unrecoverable (e.g. a 403
            # permission-denied or 404 not-found on the Drive folder/Sheet)
            # — no number of retries will ever succeed, so don't repeat
            # OCR/hashing/upload work for nothing before landing on FAILED.
            logger.error(
                "upload_pool.permanent_failure",
                job_id=job.job_id,
                filename=job.original_filename,
                attempts=job.attempt_count,
                error=job.last_error,
            )
            self._events.on_job_updated(job)
            return

        if job.attempt_count >= self._settings.retry_count:
            logger.error(
                "upload_pool.retries_exhausted",
                job_id=job.job_id,
                filename=job.original_filename,
                attempts=job.attempt_count,
                error=job.last_error,
            )
            self._events.on_job_updated(job)
            return

        backoff = self._next_backoff_seconds(job.attempt_count)
        logger.warning(
            "upload_pool.retrying",
            job_id=job.job_id,
            attempt=job.attempt_count,
            backoff_seconds=backoff,
            error=job.last_error,
        )
        job.status = JobStatus.QUEUED
        # Must be a real DB write, not just the event-sink notification:
        # `on_job_updated` (the Qt signal bus in production, a no-op by
        # default in tests) only tells the UI something changed — it does
        # not persist anything. Without this line the `jobs` table kept
        # showing the job's *previous* terminal FAILED status for the
        # entire backoff window even though it was correctly about to be
        # retried in memory; if the app closed or crashed during that
        # window, PipelineOrchestrator's startup requeue (which only looks
        # at non-terminal DB statuses) would never pick it back up, quietly
        # losing the retry. Caught by test_stress_concurrency.py's random-
        # failure batch test.
        self._jobs_repo.upsert(job)
        self._events.on_job_updated(job)
        loop.call_later(backoff, self._requeue_after_backoff, job)

    def _next_backoff_seconds(self, attempt_count: int) -> float:
        """Exponential backoff with jitter, capped at
        `_MAX_JOB_RETRY_BACKOFF_SECONDS` — mirrors the shape
        `utils.retry`'s `google_api_retry`/`network_retry` already use at
        the single-API-call layer. Without jitter here, a shared-side
        outage (Drive/Sheets briefly unavailable) failing uploads across
        many independent installs at roughly the same moment would have
        every install's job-level retry wait the exact same deterministic
        sequence and re-converge in lockstep waves against the same
        endpoint when it recovers — the same thundering-herd pattern the
        API-call layer already avoids, just one layer up.
        """
        capped = min(
            self._settings.retry_backoff_seconds * (2 ** (attempt_count - 1)),
            _MAX_JOB_RETRY_BACKOFF_SECONDS,
        )
        return random.uniform(capped * 0.5, capped)

    def _requeue_after_backoff(self, job: VideoJob) -> None:
        if not self._running:
            # Pool was stopped while this job was waiting out its backoff;
            # it's already persisted as QUEUED (see above), so
            # PipelineOrchestrator's startup requeue picks it up on the
            # next launch.
            return
        self._queue.put_nowait(job)
