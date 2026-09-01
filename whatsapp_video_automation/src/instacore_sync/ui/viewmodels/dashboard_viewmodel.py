"""Thin presentation-state layer between `PipelineSignalBus` and `DashboardView`.

Keeps the view itself dumb (just renders whatever the view-model holds) and
keeps formatting logic (bytes/sec -> "4.2 MB/s", ETA -> "~3m left") in one
tested place instead of scattered across widgets.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import DailyStats, VideoJob
from instacore_sync.workers.signals import PipelineSignalBus

# Mirrors DashboardView._on_job_updated's own terminal-status set: once a
# job reaches one of these, it's done needing display here and must be
# dropped, or `_jobs_by_id` grows without bound for the life of the
# process — this app processes 150-500 videos/day continuously, and
# "minimize to tray" instead of quitting actively encourages long-running
# sessions where that growth would actually matter.
_TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.NEEDS_REVIEW,
    JobStatus.DUPLICATE,
}


def format_bytes_per_second(bps: float) -> str:
    if bps <= 0:
        return "0 KB/s"
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    value = float(bps)
    for unit in units:
        if value < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB/s"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


class DashboardViewModel(QObject):
    stats_updated = Signal(object)  # DailyStats
    job_changed = Signal(object)    # VideoJob

    def __init__(self, signal_bus: PipelineSignalBus, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._latest_stats = DailyStats(date="")
        self._jobs_by_id: dict[str, VideoJob] = {}

        signal_bus.stats_changed.connect(self._on_stats_changed)
        signal_bus.job_updated.connect(self._on_job_updated)

    @property
    def latest_stats(self) -> DailyStats:
        return self._latest_stats

    def active_jobs(self) -> list[VideoJob]:
        active_statuses = {
            JobStatus.DISCOVERED,
            JobStatus.QUEUED,
            JobStatus.EXTRACTING,
            JobStatus.HASHING,
            JobStatus.UPLOADING,
            JobStatus.UPDATING_SHEET,
        }
        return sorted(
            (j for j in self._jobs_by_id.values() if j.status in active_statuses),
            key=lambda j: j.discovered_at,
        )

    def _on_stats_changed(self, stats: DailyStats) -> None:
        self._latest_stats = stats
        self.stats_updated.emit(stats)

    def _on_job_updated(self, job: VideoJob) -> None:
        if job.status in _TERMINAL_STATUSES:
            # Drop rather than cache: a terminal job never needs to be
            # looked up here again, and keeping it would leak memory for
            # the lifetime of the process (see `_TERMINAL_STATUSES`).
            self._jobs_by_id.pop(job.job_id, None)
        else:
            self._jobs_by_id[job.job_id] = job
        self.job_changed.emit(job)
