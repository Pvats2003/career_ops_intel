"""Qt signal bus that implements `PipelineEventSink`.

Every method here runs on whatever thread the pipeline is using (the
dedicated asyncio thread, or a ThreadPoolExecutor worker thread it spawns).
Emitting a Qt signal from a non-GUI thread is safe *as long as it is
connected with the default `AutoConnection`*, which Qt resolves to
`QueuedConnection` across threads — so every slot connected to these
signals runs on the GUI thread automatically. No manual locking needed.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from instacore_sync.domain.enums import GoogleAuthStatus, OcrEngineStatus, WatcherStatus
from instacore_sync.domain.models import DailyStats, UploadLogEntry, VideoJob


class PipelineSignalBus(QObject):
    job_updated = Signal(object)          # VideoJob
    log_entry_added = Signal(object)      # UploadLogEntry
    stats_changed = Signal(object)        # DailyStats
    watcher_status_changed = Signal(object)          # WatcherStatus
    auth_status_changed = Signal(object, object)     # GoogleAuthStatus, str | None
    ocr_engine_status_changed = Signal(str, object)  # engine name, OcrEngineStatus
    log_message = Signal(str, str)        # level, message
    pause_state_changed = Signal(bool)    # is_paused
    health_check_completed = Signal(list)  # list[HealthCheckResult]
    wizard_check_result = Signal(str, object)  # check name, HealthCheckResult

    # -- PipelineEventSink protocol implementation --------------------------

    def on_job_updated(self, job: VideoJob) -> None:
        self.job_updated.emit(job)

    def on_log_entry(self, entry: UploadLogEntry) -> None:
        self.log_entry_added.emit(entry)

    def on_stats_changed(self, stats: DailyStats) -> None:
        self.stats_changed.emit(stats)

    def on_watcher_status(self, status: WatcherStatus) -> None:
        self.watcher_status_changed.emit(status)

    def on_auth_status(self, status: GoogleAuthStatus, account_email: str | None) -> None:
        self.auth_status_changed.emit(status, account_email)

    def on_ocr_engine_status(self, engine_name: str, status: OcrEngineStatus) -> None:
        self.ocr_engine_status_changed.emit(engine_name, status)

    def on_log_message(self, level: str, message: str) -> None:
        self.log_message.emit(level, message)

    def on_pause_state_changed(self, is_paused: bool) -> None:
        self.pause_state_changed.emit(is_paused)
