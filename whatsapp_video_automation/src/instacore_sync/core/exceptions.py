"""Typed exception hierarchy used across the application.

Keeping these distinct (rather than raising bare `Exception`/`ValueError`)
lets the pipeline orchestrator decide, per failure class, whether to retry,
route the video to Needs Review, or abort the whole run.
"""

from __future__ import annotations


class InstacoreSyncError(Exception):
    """Base class for all application-specific errors."""


class ConfigurationError(InstacoreSyncError):
    """Raised when settings are missing, malformed, or contradictory."""


class DeviceIdNotFoundError(InstacoreSyncError):
    """Raised when OCR could not confidently extract a Device ID from a video."""

    def __init__(self, video_path: str, best_confidence: float = 0.0) -> None:
        self.video_path = video_path
        self.best_confidence = best_confidence
        super().__init__(
            f"Could not extract a Device ID from {video_path!r} "
            f"(best OCR confidence={best_confidence:.2f})"
        )


class VideoReadError(InstacoreSyncError):
    """Raised when a video file cannot be opened or decoded."""


class OcrEngineError(InstacoreSyncError):
    """Raised when an OCR engine fails to run (not a low-confidence result)."""


class DriveAuthError(InstacoreSyncError):
    """Raised when Google Drive/Sheets OAuth credentials are missing or invalid."""


class DriveApiError(InstacoreSyncError):
    """Raised when a Google Drive API call fails after retries are exhausted."""


class SheetsApiError(InstacoreSyncError):
    """Raised when a Google Sheets API call fails after retries are exhausted."""


class DuplicateVideoError(InstacoreSyncError):
    """Raised when a video's SHA-256 hash matches one already uploaded."""

    def __init__(self, file_hash: str, original_filename: str | None = None) -> None:
        self.file_hash = file_hash
        self.original_filename = original_filename
        super().__init__(
            f"Video with hash {file_hash[:12]}... was already uploaded"
            + (f" as {original_filename!r}" if original_filename else "")
        )


class UploadError(InstacoreSyncError):
    """Raised when an upload permanently fails after exhausting retries."""


class FileNotStableError(InstacoreSyncError):
    """Raised when a file never stops changing size within the wait window."""


class RepositoryError(InstacoreSyncError):
    """Raised on unexpected SQLite/repository failures."""
