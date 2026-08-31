"""Processes a single `VideoJob` end to end.

This is the synchronous, blocking, single-video workflow:
    stabilize -> hash -> dedup check -> OCR device ID -> Drive folders ->
    upload -> sheet row -> move to Processed/NeedsReview/Failed -> record.

It is deliberately synchronous (no asyncio inside) so it can run unmodified
either directly (tests, CLI) or inside a thread-pool executor driven by the
async `UploadWorkerPool` (see upload_worker_pool.py). One `VideoProcessor`
instance is safe to share across worker threads — it holds no per-job state.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from instacore_sync.core.config import AppSettings
from instacore_sync.core.exceptions import (
    DriveApiError,
    FileNotStableError,
    InstacoreSyncError,
    SheetsApiError,
    VideoReadError,
)
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import UploadLogEntry, VideoJob
from instacore_sync.services.dedup.dedup_service import DedupService
from instacore_sync.services.drive.drive_client import DriveClient
from instacore_sync.services.ocr.device_id_extractor import DeviceIdExtractor
from instacore_sync.services.pipeline.events import NullEventSink, PipelineEventSink
from instacore_sync.services.sheets.sheets_client import SheetsClient
from instacore_sync.utils.file_utils import move_to_folder, wait_until_stable

logger = get_logger(__name__)


class VideoProcessor:
    def __init__(
        self,
        settings: AppSettings,
        device_id_extractor: DeviceIdExtractor,
        dedup_service: DedupService,
        drive_client: DriveClient,
        sheets_client: SheetsClient,
        jobs_repo: JobsRepository,
        logs_repo: LogsRepository,
        event_sink: PipelineEventSink | None = None,
    ) -> None:
        self._settings = settings
        self._ocr = device_id_extractor
        self._dedup = dedup_service
        self._drive = drive_client
        self._sheets = sheets_client
        self._jobs_repo = jobs_repo
        self._logs_repo = logs_repo
        self._events = event_sink or NullEventSink()

    def process(self, job: VideoJob, progress_callback=None) -> VideoJob:  # noqa: ANN001
        job.started_at = datetime.now()
        job.attempt_count += 1
        try:
            self._stabilize(job)
            self._hash_and_dedup_check(job)
            if job.status == JobStatus.DUPLICATE:
                return self._finalize(job)

            self._extract_device_id(job)
            if job.status == JobStatus.NEEDS_REVIEW:
                return self._finalize(job)

            self._upload(job, progress_callback)
            self._update_sheet(job)

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            destination = Path(self._settings.processed_folder)
            job.source_path = move_to_folder(job.source_path, destination)
            return self._finalize(job)

        except FileNotStableError as exc:
            return self._fail(job, str(exc), route_to_failed=True)
        except VideoReadError as exc:
            return self._fail(job, str(exc), route_to_needs_review=True)
        except (DriveApiError, SheetsApiError) as exc:
            return self._fail(job, str(exc), route_to_failed=True)
        except InstacoreSyncError as exc:
            return self._fail(job, str(exc), route_to_failed=True)
        except Exception as exc:  # noqa: BLE001 - never let one video crash the pipeline
            logger.exception("pipeline.unexpected_error", job_id=job.job_id)
            return self._fail(job, f"Unexpected error: {exc}", route_to_failed=True)

    # -- steps ---------------------------------------------------------------

    def _stabilize(self, job: VideoJob) -> None:
        job.status = JobStatus.QUEUED
        self._save(job)
        size = wait_until_stable(job.source_path)
        job.file_size_bytes = size

    def _hash_and_dedup_check(self, job: VideoJob) -> None:
        job.status = JobStatus.HASHING
        self._save(job)
        file_hash = self._dedup.compute_hash(job.source_path)
        job.file_hash_sha256 = file_hash

        if not self._settings.uploads.duplicate_check:
            return

        duplicate = self._dedup.find_duplicate(file_hash)
        if duplicate is not None:
            job.status = JobStatus.DUPLICATE
            job.drive_link = duplicate.drive_link
            job.last_error = f"Duplicate of {duplicate.original_filename}"
            destination = Path(self._settings.processed_folder)
            job.source_path = move_to_folder(job.source_path, destination)

    def _extract_device_id(self, job: VideoJob) -> None:
        job.status = JobStatus.EXTRACTING
        self._save(job)
        extraction = self._ocr.extract(job.source_path)
        job.ocr_confidence = extraction.confidence
        job.ocr_engine_used = extraction.engine_used

        if not extraction.succeeded or extraction.confidence < self._settings.ocr.min_confidence:
            job.device_id = extraction.device_id
            job.mark_needs_review(
                f"OCR confidence {extraction.confidence:.2f} below threshold "
                f"{self._settings.ocr.min_confidence:.2f}"
                if extraction.device_id
                else "No Device ID pattern found in the opening frames"
            )
            destination = Path(self._settings.needs_review_folder)
            job.source_path = move_to_folder(job.source_path, destination)
            return

        job.device_id = extraction.device_id

    def _upload(self, job: VideoJob, progress_callback) -> None:  # noqa: ANN001
        job.status = JobStatus.UPLOADING
        self._save(job)

        date_label = datetime.now().strftime(self._settings.drive.date_folder_format)
        folder_id = self._drive.get_or_create_device_folder(date_label, job.device_id or "Unsorted")
        job.drive_folder_id = folder_id

        def _on_progress(uploaded: int, total: int) -> None:
            job.bytes_uploaded = uploaded
            if progress_callback:
                progress_callback(job, uploaded, total)

        result = self._drive.upload_file(
            job.source_path,
            folder_id,
            chunk_size_mb=self._settings.uploads.chunk_size_mb,
            progress_callback=_on_progress,
        )
        job.drive_file_id = result.file_id
        job.drive_link = result.web_view_link
        job.bytes_uploaded = result.bytes_uploaded

        if job.file_hash_sha256:
            self._dedup.record_upload(
                job.file_hash_sha256, job.job_id, job.original_filename, result.file_id, result.web_view_link
            )

    def _update_sheet(self, job: VideoJob) -> None:
        job.status = JobStatus.UPDATING_SHEET
        self._save(job)
        if not self._settings.sheets.spreadsheet_id:
            logger.warning("pipeline.sheets_skipped_not_configured", job_id=job.job_id)
            return

        date_label = datetime.now().strftime(self._settings.drive.date_folder_format)
        result = self._sheets.upsert_row(
            date_label=date_label,
            device_id=job.device_id or "UNKNOWN",
            filename=job.original_filename,
            drive_link=job.drive_link or "",
            status=JobStatus.COMPLETED.value,
            ocr_confidence=job.ocr_confidence,
        )
        job.sheet_row_number = result.row_number

    # -- finalization ---------------------------------------------------------

    def _fail(
        self,
        job: VideoJob,
        error: str,
        *,
        route_to_failed: bool = False,
        route_to_needs_review: bool = False,
    ) -> VideoJob:
        job.mark_failed(error) if route_to_failed else job.mark_needs_review(error)
        try:
            if job.source_path.exists():
                destination = Path(
                    self._settings.needs_review_folder
                    if route_to_needs_review
                    else self._settings.failed_folder
                )
                job.source_path = move_to_folder(job.source_path, destination)
        except OSError:
            logger.warning("pipeline.move_on_failure_failed", job_id=job.job_id)
        return self._finalize(job)

    def _finalize(self, job: VideoJob) -> VideoJob:
        job.completed_at = job.completed_at or datetime.now()
        self._save(job)
        entry = UploadLogEntry(
            job_id=job.job_id,
            filename=job.original_filename,
            device_id=job.device_id,
            status=job.status,
            ocr_confidence=job.ocr_confidence,
            ocr_engine_used=job.ocr_engine_used.value if job.ocr_engine_used else None,
            file_hash_sha256=job.file_hash_sha256,
            drive_link=job.drive_link,
            error_message=job.last_error,
            completed_at=job.completed_at,
        )
        self._logs_repo.append(entry)
        self._events.on_log_entry(entry)
        return job

    def _save(self, job: VideoJob) -> None:
        self._jobs_repo.upsert(job)
        self._events.on_job_updated(job)
