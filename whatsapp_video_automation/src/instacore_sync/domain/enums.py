"""Enumerations shared by the domain, DB, services, and UI layers."""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """Lifecycle state of a single video as it moves through the pipeline."""

    DISCOVERED = "discovered"          # seen by the folder watcher, not yet stable
    QUEUED = "queued"                  # stable on disk, waiting for a worker
    EXTRACTING = "extracting"          # frame extraction + OCR in progress
    HASHING = "hashing"                # SHA-256 computation in progress
    DUPLICATE = "duplicate"            # hash matched a prior upload, skipped
    UPLOADING = "uploading"            # Drive upload in progress
    UPDATING_SHEET = "updating_sheet"  # writing the row to Google Sheets
    COMPLETED = "completed"            # fully processed and moved to Processed/
    NEEDS_REVIEW = "needs_review"      # OCR could not confidently read a Device ID
    FAILED = "failed"                  # unrecoverable error after retries


class OcrEngineName(StrEnum):
    TESSERACT = "tesseract"
    PADDLEOCR = "paddleocr"
    AUTO = "auto"  # run every configured engine, keep the highest-confidence result


class OcrEngineStatus(StrEnum):
    UNKNOWN = "unknown"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class GoogleAuthStatus(StrEnum):
    SIGNED_OUT = "signed_out"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    ERROR = "error"


class WatcherStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
