"""Wires the folder watcher, OCR/hash/dedup services, Drive/Sheets clients,
and the async upload worker pool into one coherent runtime.

Lifecycle:
  1. `start()` probes OCR engine + Google auth status, starts the folder
     watcher, and starts the async worker pool — all reported through the
     `PipelineEventSink`.
  2. The watcher calls `_on_video_discovered` from its own background
     thread; that method is synchronous and thread-safe, and schedules the
     new job onto the asyncio queue via `call_soon_threadsafe`.
  3. Worker-pool coroutines drain the queue with bounded concurrency.
  4. `stop()` tears everything down in reverse order.

This class intentionally owns no Qt code — see `workers/pipeline_thread.py`
for the thread that runs this orchestrator's asyncio loop and bridges its
event sink to Qt signals.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from instacore_sync.core.config import AppSettings
from instacore_sync.core.exceptions import DriveAuthError
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.domain.enums import GoogleAuthStatus, JobStatus, OcrEngineName, WatcherStatus
from instacore_sync.domain.models import DailyStats, VideoJob
from instacore_sync.services.dedup.dedup_service import DedupService
from instacore_sync.services.drive.drive_auth import GoogleAuthService
from instacore_sync.services.drive.drive_client import DriveClient
from instacore_sync.services.ocr.device_id_extractor import DeviceIdExtractor
from instacore_sync.services.ocr.engine_factory import OcrEngineFactory
from instacore_sync.services.pipeline.events import NullEventSink, PipelineEventSink
from instacore_sync.services.pipeline.video_processor import VideoProcessor
from instacore_sync.services.sheets.sheets_client import SheetsClient
from instacore_sync.services.upload.upload_queue import UploadQueue
from instacore_sync.services.upload.upload_worker_pool import UploadWorkerPool
from instacore_sync.services.watcher.folder_watcher import FolderWatcher
from instacore_sync.utils.file_utils import is_video_file
from instacore_sync.utils.text_sanitize import is_valid_device_id

logger = get_logger(__name__)


class PipelineOrchestrator:
    def __init__(
        self,
        settings: AppSettings,
        jobs_repo: JobsRepository,
        logs_repo: LogsRepository,
        dedup_service: DedupService,
        ocr_engine_factory: OcrEngineFactory,
        google_auth: GoogleAuthService,
        drive_client: DriveClient,
        sheets_client: SheetsClient,
        event_sink: PipelineEventSink | None = None,
    ) -> None:
        self._settings = settings
        self._jobs_repo = jobs_repo
        self._logs_repo = logs_repo
        self._dedup = dedup_service
        self._ocr_engine_factory = ocr_engine_factory
        self._google_auth = google_auth
        self._drive = drive_client
        self._sheets = sheets_client
        self._events = event_sink or NullEventSink()

        self._device_id_extractor = DeviceIdExtractor(settings.ocr, engine_factory=ocr_engine_factory)
        self._processor = VideoProcessor(
            settings,
            self._device_id_extractor,
            dedup_service,
            drive_client,
            sheets_client,
            jobs_repo,
            logs_repo,
            event_sink=self._events,
        )
        self._queue = UploadQueue()
        self._worker_pool = UploadWorkerPool(
            settings.uploads, self._queue, self._processor, jobs_repo, self._events
        )
        self._watcher: FolderWatcher | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._events.on_log_message("INFO", "Pipeline starting...")

        await self._probe_ocr_engines()
        await self._probe_google_auth()
        await self._requeue_incomplete_jobs()
        await self._prune_old_jobs()

        self._worker_pool.start()

        self._watcher = FolderWatcher(Path(self._settings.watch_folder), self._on_video_discovered)
        self._events.on_watcher_status(WatcherStatus.STARTING)
        try:
            self._watcher.start()
            self._events.on_watcher_status(WatcherStatus.RUNNING)
        except OSError as exc:
            self._events.on_watcher_status(WatcherStatus.ERROR)
            self._events.on_log_message("ERROR", f"Could not watch folder: {exc}")

        self._running = True
        self._events.on_log_message("INFO", "Pipeline started.")

    async def stop(self) -> None:
        self._running = False
        if self._watcher is not None:
            self._watcher.stop()
            self._events.on_watcher_status(WatcherStatus.STOPPED)
        await self._worker_pool.stop()
        self._events.on_log_message("INFO", "Pipeline stopped.")

    # -- discovery -> queue bridge (called from the watcher's own thread) ------

    def _on_video_discovered(self, path: Path) -> None:
        if not is_video_file(path):
            return
        job = VideoJob(source_path=path, original_filename=path.name, status=JobStatus.DISCOVERED)
        self._jobs_repo.upsert(job)
        self._events.on_job_updated(job)
        logger.info("pipeline.video_discovered", filename=path.name)

        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._enqueue, job)

    def _enqueue(self, job: VideoJob) -> None:
        job.status = JobStatus.QUEUED
        self._jobs_repo.upsert(job)
        self._events.on_job_updated(job)
        self._queue.put_nowait(job)

    async def _requeue_incomplete_jobs(self) -> None:
        """Resume jobs left mid-flight by a previous crash/close."""
        for job in self._jobs_repo.list_active():
            if job.source_path.exists():
                job.attempt_count = 0
                self._enqueue(job)
            else:
                job.mark_failed("Source file no longer exists after restart")
                self._jobs_repo.upsert(job)
                self._events.on_job_updated(job)

    async def _prune_old_jobs(self) -> None:
        """Keep the `jobs` working table from growing forever.

        At 150-500 videos/day, an app left running continuously for months
        would otherwise accumulate tens of thousands of COMPLETED rows it
        never needs again (the durable record already lives in
        `upload_logs`). Runs once per app start, off the hot path.
        """
        retention_days = self._settings.app.jobs_retention_days
        if retention_days <= 0:
            return  # 0/negative disables pruning entirely
        cutoff = datetime.now() - timedelta(days=retention_days)
        loop = asyncio.get_running_loop()
        deleted = await loop.run_in_executor(None, self._jobs_repo.prune_terminal_jobs_older_than, cutoff)
        if deleted:
            logger.info("pipeline.old_jobs_pruned", count=deleted, retention_days=retention_days)

    # -- manual controls (Queue view's Retry button, top bar Pause/Resume) -----

    def pause_uploads(self) -> None:
        self._worker_pool.pause()
        self._events.on_pause_state_changed(True)

    def resume_uploads(self) -> None:
        self._worker_pool.resume()
        self._events.on_pause_state_changed(False)

    @property
    def is_paused(self) -> bool:
        return self._worker_pool.is_paused

    def retry_job(self, job_id: str) -> bool:
        """Re-queue a FAILED or NEEDS_REVIEW job on demand.

        Returns False (and does nothing) if the job can't be found, isn't
        in a retryable state, or its source file no longer exists on disk
        (e.g. a user manually deleted it from the Failed/NeedsReview
        folder) — callers should surface that to the user rather than
        silently queuing a job that can only fail again immediately.
        """
        job = self._jobs_repo.get(job_id)
        if job is None or job.status not in (JobStatus.FAILED, JobStatus.NEEDS_REVIEW):
            return False
        if not job.source_path.exists():
            logger.warning("pipeline.retry_job_missing_file", job_id=job_id, path=str(job.source_path))
            return False

        job.attempt_count = 0
        job.last_error = None
        self._enqueue(job)
        logger.info("pipeline.job_retried_manually", job_id=job_id, filename=job.original_filename)
        return True

    def resolve_needs_review(self, job_id: str, manual_device_id: str) -> bool:
        """Apply an operator's manually-chosen Device ID (Needs Review
        screen) and re-queue straight to upload, skipping OCR entirely.

        Returns False without making any change if the job isn't (still) in
        Needs Review, its file is gone, or `manual_device_id` doesn't match
        the configured pattern — the same validation `VideoProcessor`
        itself applies before ever creating a Drive folder, checked here
        too so the UI can reject an obviously bad entry immediately rather
        than silently queuing a job that will just bounce back.
        """
        job = self._jobs_repo.get(job_id)
        if job is None or job.status != JobStatus.NEEDS_REVIEW:
            return False
        if not job.source_path.exists():
            logger.warning("pipeline.resolve_needs_review_missing_file", job_id=job_id)
            return False
        if not is_valid_device_id(manual_device_id, self._settings.ocr.device_id_pattern):
            return False

        job.device_id = manual_device_id
        job.manually_confirmed = True
        job.ocr_confidence = 1.0
        job.attempt_count = 0
        job.last_error = None
        self._enqueue(job)
        logger.info(
            "pipeline.needs_review_resolved_manually",
            job_id=job_id,
            filename=job.original_filename,
            device_id=manual_device_id,
        )
        return True

    # -- status probing ---------------------------------------------------------

    async def _probe_ocr_engines(self) -> None:
        loop = asyncio.get_running_loop()
        for engine in self._ocr_engine_factory.engines_for(OcrEngineName.AUTO):
            status = await loop.run_in_executor(None, engine.status)
            self._events.on_ocr_engine_status(engine.name.value, status)

    async def _probe_google_auth(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._google_auth.get_credentials)
            self._events.on_auth_status(self._google_auth.status, self._google_auth.account_email)
        except DriveAuthError as exc:
            self._events.on_auth_status(GoogleAuthStatus.ERROR, None)
            self._events.on_log_message("WARNING", f"Google sign-in not completed yet: {exc}")

    # -- stats -----------------------------------------------------------------

    def compute_daily_stats(self) -> DailyStats:
        counts = self._jobs_repo.counts_by_status()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_logs = self._logs_repo.today_stats_rows(today_start.isoformat())

        completed_today = [e for e in today_logs if e.status == JobStatus.COMPLETED]
        confidences = [e.ocr_confidence for e in today_logs if e.ocr_confidence > 0]

        active_jobs = self._jobs_repo.list_by_status(JobStatus.UPLOADING)
        current_speed = sum(j.upload_speed_bps for j in active_jobs)
        remaining_bytes = sum(max(0, j.file_size_bytes - j.bytes_uploaded) for j in active_jobs)
        eta = (remaining_bytes / current_speed) if current_speed > 0 else None

        completed_jobs_today = self._jobs_repo.list_by_status(JobStatus.COMPLETED)
        total_bytes_today = sum(j.file_size_bytes for j in completed_jobs_today) + sum(
            j.bytes_uploaded for j in active_jobs
        )

        return DailyStats(
            date=today_start.strftime("%Y-%m-%d"),
            waiting=counts.get(JobStatus.QUEUED, 0) + counts.get(JobStatus.DISCOVERED, 0),
            uploading=counts.get(JobStatus.UPLOADING, 0)
            + counts.get(JobStatus.EXTRACTING, 0)
            + counts.get(JobStatus.HASHING, 0)
            + counts.get(JobStatus.UPDATING_SHEET, 0),
            completed=len(completed_today),
            failed=counts.get(JobStatus.FAILED, 0),
            needs_review=counts.get(JobStatus.NEEDS_REVIEW, 0),
            duplicates_skipped=len([e for e in today_logs if e.status == JobStatus.DUPLICATE]),
            avg_ocr_confidence=(sum(confidences) / len(confidences)) if confidences else 0.0,
            total_bytes_uploaded=total_bytes_today,
            current_transfer_speed_bps=current_speed,
            estimated_seconds_remaining=eta,
        )
