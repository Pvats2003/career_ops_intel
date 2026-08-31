"""Core domain models (Pydantic) shared across services, workers, and UI.

These are transport/value objects, not ORM rows — the DB layer maps to/from
them explicitly so persistence concerns never leak into business logic.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from instacore_sync.domain.enums import JobStatus, OcrEngineName


class DeviceIdExtraction(BaseModel):
    """Result of running the OCR pipeline against a video's opening frames."""

    model_config = ConfigDict(frozen=True)

    device_id: str | None = None
    confidence: float = 0.0
    engine_used: OcrEngineName | None = None
    frame_timestamp_seconds: float | None = None
    frames_examined: int = 0
    raw_text: str | None = None
    full_scan_performed: bool = False

    @property
    def succeeded(self) -> bool:
        return self.device_id is not None


class VideoJob(BaseModel):
    """A single video moving through discovery -> OCR -> upload -> sheet update."""

    model_config = ConfigDict(frozen=False, arbitrary_types_allowed=True)

    job_id: str = Field(default_factory=lambda: uuid4().hex)
    source_path: Path
    original_filename: str
    status: JobStatus = JobStatus.DISCOVERED

    file_size_bytes: int = 0
    file_hash_sha256: str | None = None

    device_id: str | None = None
    ocr_confidence: float = 0.0
    ocr_engine_used: OcrEngineName | None = None
    ocr_raw_text: str | None = None
    # True once an operator has manually picked the Device ID on the Needs
    # Review screen — tells VideoProcessor to trust it and skip re-running
    # OCR, which would otherwise just reproduce the same low-confidence
    # guess that sent the video to Needs Review in the first place.
    manually_confirmed: bool = False

    drive_file_id: str | None = None
    drive_link: str | None = None
    drive_folder_id: str | None = None

    sheet_row_number: int | None = None

    attempt_count: int = 0
    last_error: str | None = None

    bytes_uploaded: int = 0
    upload_speed_bps: float = 0.0

    # Timing for the current processing attempt only — not persisted to the
    # `jobs` table (they're only meaningful for the terminal `UploadLogEntry`
    # a completed attempt produces, not as ongoing job state to restore
    # across a restart).
    ocr_duration_seconds: float | None = None
    upload_duration_seconds: float | None = None

    discovered_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def mark_failed(self, error: str) -> None:
        self.status = JobStatus.FAILED
        self.last_error = error

    def mark_needs_review(self, reason: str) -> None:
        self.status = JobStatus.NEEDS_REVIEW
        self.last_error = reason

    @property
    def progress_fraction(self) -> float:
        if self.file_size_bytes <= 0:
            return 0.0
        return min(1.0, self.bytes_uploaded / self.file_size_bytes)


class UploadResult(BaseModel):
    """Outcome of uploading a single file to Google Drive."""

    model_config = ConfigDict(frozen=True)

    file_id: str
    web_view_link: str
    folder_id: str
    bytes_uploaded: int
    duration_seconds: float


class SheetUpdateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    spreadsheet_id: str
    row_number: int
    created_new_row: bool


class DailyStats(BaseModel):
    """Rolled-up counters the dashboard polls to render at-a-glance stats."""

    date: str
    waiting: int = 0
    uploading: int = 0
    completed: int = 0
    failed: int = 0
    needs_review: int = 0
    duplicates_skipped: int = 0
    avg_ocr_confidence: float = 0.0
    total_bytes_uploaded: int = 0
    current_transfer_speed_bps: float = 0.0
    estimated_seconds_remaining: float | None = None


class UploadLogEntry(BaseModel):
    """A row persisted to SQLite for auditing/search/CSV export."""

    model_config = ConfigDict(frozen=False)

    log_id: str = Field(default_factory=lambda: uuid4().hex)
    job_id: str
    filename: str
    device_id: str | None
    status: JobStatus
    ocr_confidence: float
    ocr_engine_used: str | None
    file_hash_sha256: str | None
    drive_link: str | None
    error_message: str | None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None
    ocr_duration_seconds: float | None = None
    upload_duration_seconds: float | None = None
    total_duration_seconds: float | None = None
    # Full traceback text, populated only for a truly unexpected exception
    # (not for the classified, already-descriptive error types) — for
    # after-the-fact debugging without needing to dig through the rotating
    # developer log file for the matching timestamp.
    stack_trace: str | None = None
