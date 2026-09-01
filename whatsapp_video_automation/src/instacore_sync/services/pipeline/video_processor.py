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

import time
import traceback
from datetime import datetime
from pathlib import Path

from instacore_sync.core.config import AppSettings
from instacore_sync.core.exceptions import (
    DriveApiError,
    DuplicateVideoError,
    FileNotStableError,
    InstacoreSyncError,
    SheetsApiError,
    VideoReadError,
)
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.db.repositories.hashes_repository import UploadedHashRecord
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
from instacore_sync.utils.google_api_errors import is_permanent_google_api_error
from instacore_sync.utils.text_sanitize import is_valid_device_id

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
            if job.status == JobStatus.NEEDS_REVIEW:
                return self._finalize(job)

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
            # A permission-denied (403) or not-found (404) folder/sheet
            # will never succeed no matter how many times it's retried —
            # `is_permanent_google_api_error` (checking exc.__cause__, the
            # original HttpError `raise ... from exc` preserved) tells a
            # confirmed-permanent failure apart from one that's merely
            # unclassifiable (e.g. a plain timeout that never reached
            # Google as an HttpError) or transient-but-retry-exhausted —
            # both of the latter must still get the normal job-level retry
            # treatment. Without this, the job-level retry in
            # UploadWorkerPool would repeat OCR/hashing/upload work up to
            # `retry_count` times for a video whose destination
            # permissions were revoked, delaying the FAILED status a human
            # would want to see immediately.
            job.permanent_failure = is_permanent_google_api_error(exc)
            return self._fail(job, str(exc), route_to_failed=True)
        except InstacoreSyncError as exc:
            return self._fail(job, str(exc), route_to_failed=True)
        except Exception as exc:  # noqa: BLE001 - never let one video crash the pipeline
            logger.exception("pipeline.unexpected_error", job_id=job.job_id)
            return self._fail(
                job, f"Unexpected error: {exc}", route_to_failed=True, stack_trace=traceback.format_exc()
            )
        finally:
            # Always release — a no-op if this attempt never claimed the
            # hash (e.g. it was already a confirmed duplicate). Must run
            # regardless of outcome so a failed/retried attempt doesn't
            # permanently block this hash from ever being claimed again.
            if job.file_hash_sha256:
                self._dedup.release_claim(job.file_hash_sha256)

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
        if duplicate is None:
            duplicate = self._find_remote_duplicate(job, file_hash)

        if duplicate is not None:
            job.status = JobStatus.DUPLICATE
            job.drive_link = duplicate.drive_link
            job.last_error = f"Duplicate of {duplicate.original_filename}"
            destination = Path(self._settings.processed_folder)
            job.source_path = move_to_folder(job.source_path, destination)
            return

        # No confirmed duplicate yet, but another concurrent worker may be
        # uploading this exact content *right now* (two identical videos
        # arriving in the same batch) — the DB record above only appears
        # once that upload finishes. Claiming the hash closes that window;
        # losing the claim routes this attempt through the normal
        # retry/backoff path, by which point the DB check will usually
        # catch it as a real duplicate.
        if not self._dedup.claim_for_upload(file_hash):
            raise DuplicateVideoError(file_hash, job.original_filename)

    def _find_remote_duplicate(self, job: VideoJob, file_hash: str) -> UploadedHashRecord | None:
        """Ask Drive itself whether this hash was already uploaded — the
        cross-process check.

        The local check above only knows about uploads *this* process has
        made. When the destination is shared by many independent app
        instances (every team member's own copy pointed at one Drive
        folder/Sheet), the far more common case is that a video forwarded
        to several people gets picked up by several different processes at
        once, each with an empty local index for it. Drive's custom-
        property search (tagged on every upload, see `DriveClient.
        upload_file`) is the shared source of truth those independent
        local caches can't be. A match found this way is backfilled into
        the local `uploaded_hashes` table so this process's *own* local
        check catches it directly next time, without a network round trip.

        Deliberately fails open: a network hiccup here must never fail an
        otherwise-good upload just because the extra dedup check couldn't
        complete — worst case, a preventable duplicate slips through this
        one time (still caught by the same check on every future upload of
        that hash), which is a far smaller cost than losing today's video
        entirely.
        """
        try:
            match = self._drive.find_duplicate_by_hash(file_hash)
        except DriveApiError as exc:
            logger.warning(
                "pipeline.remote_dedup_check_failed", job_id=job.job_id, error=str(exc)
            )
            return None
        if match is None:
            return None

        logger.info(
            "dedup.remote_duplicate_found", job_id=job.job_id, file_id=match.file_id, name=match.name
        )
        self._dedup.record_upload(file_hash, job.job_id, match.name, match.file_id, match.web_view_link)
        return self._dedup.find_duplicate(file_hash)

    def _extract_device_id(self, job: VideoJob) -> None:
        if job.manually_confirmed and job.device_id:
            # An operator already picked this Device ID on the Needs Review
            # screen — re-running OCR here would just reproduce the same
            # low-confidence guess that sent it there in the first place.
            logger.info(
                "pipeline.ocr_skipped_manual_override", job_id=job.job_id, device_id=job.device_id
            )
            return

        job.status = JobStatus.EXTRACTING
        self._save(job)
        ocr_started = time.monotonic()
        extraction = self._ocr.extract(job.source_path)
        job.ocr_duration_seconds = time.monotonic() - ocr_started
        job.ocr_confidence = extraction.confidence
        job.ocr_engine_used = extraction.engine_used
        job.ocr_raw_text = extraction.raw_text

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
        # Defense in depth: every device_id that reaches here should already
        # be regex-valid (the only path that sets it — OCR extraction — is
        # itself pattern-matched), but a manual override from the Needs
        # Review screen is free text typed by a human, and any future code
        # path that sets device_id should not be trusted by default. A bad
        # value here would otherwise become a garbage Drive folder name and
        # a bad Sheet row ("incorrect IC mapping") that's tedious to clean
        # up after the fact — cheaper to catch it before it happens.
        if job.device_id and not is_valid_device_id(job.device_id, self._settings.ocr.device_id_pattern):
            job.mark_needs_review(f"Device ID {job.device_id!r} does not match the expected pattern")
            destination = Path(self._settings.needs_review_folder)
            job.source_path = move_to_folder(job.source_path, destination)
            return

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
            sha256=job.file_hash_sha256,
        )
        job.drive_file_id = result.file_id
        job.drive_link = result.web_view_link
        job.bytes_uploaded = result.bytes_uploaded
        job.upload_duration_seconds = result.duration_seconds

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
        stack_trace: str | None = None,
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
        return self._finalize(job, stack_trace=stack_trace)

    def _finalize(self, job: VideoJob, *, stack_trace: str | None = None) -> VideoJob:
        job.completed_at = job.completed_at or datetime.now()
        self._save(job)
        total_duration = (
            (job.completed_at - job.started_at).total_seconds() if job.started_at else None
        )
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
            ocr_duration_seconds=job.ocr_duration_seconds,
            upload_duration_seconds=job.upload_duration_seconds,
            total_duration_seconds=total_duration,
            stack_trace=stack_trace,
        )
        self._logs_repo.append(entry)
        self._events.on_log_entry(entry)
        return job

    def _save(self, job: VideoJob) -> None:
        self._jobs_repo.upsert(job)
        self._events.on_job_updated(job)
