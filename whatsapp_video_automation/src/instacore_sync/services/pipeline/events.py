"""Event sink interface the pipeline uses to report progress outward.

The pipeline core (orchestrator + worker pool + processor) never imports Qt.
Instead it reports everything through this small protocol; `workers/signals.py`
implements it by emitting Qt signals, and tests can implement it with a
plain recording stub. This keeps the business logic testable headlessly.
"""

from __future__ import annotations

from typing import Protocol

from instacore_sync.domain.enums import GoogleAuthStatus, OcrEngineStatus, WatcherStatus
from instacore_sync.domain.models import DailyStats, UploadLogEntry, VideoJob


class PipelineEventSink(Protocol):
    def on_job_updated(self, job: VideoJob) -> None: ...

    def on_log_entry(self, entry: UploadLogEntry) -> None: ...

    def on_stats_changed(self, stats: DailyStats) -> None: ...

    def on_watcher_status(self, status: WatcherStatus) -> None: ...

    def on_auth_status(self, status: GoogleAuthStatus, account_email: str | None) -> None: ...

    def on_ocr_engine_status(self, engine_name: str, status: OcrEngineStatus) -> None: ...

    def on_log_message(self, level: str, message: str) -> None: ...

    def on_pause_state_changed(self, is_paused: bool) -> None: ...


class NullEventSink:
    """No-op sink — used by default and in unit tests that don't care about events."""

    def on_job_updated(self, job: VideoJob) -> None:
        pass

    def on_log_entry(self, entry: UploadLogEntry) -> None:
        pass

    def on_stats_changed(self, stats: DailyStats) -> None:
        pass

    def on_watcher_status(self, status: WatcherStatus) -> None:
        pass

    def on_auth_status(self, status: GoogleAuthStatus, account_email: str | None) -> None:
        pass

    def on_ocr_engine_status(self, engine_name: str, status: OcrEngineStatus) -> None:
        pass

    def on_log_message(self, level: str, message: str) -> None:
        pass

    def on_pause_state_changed(self, is_paused: bool) -> None:
        pass
