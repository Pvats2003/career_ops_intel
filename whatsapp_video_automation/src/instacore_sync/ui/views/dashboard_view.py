"""The Dashboard — at-a-glance stats, live upload queue, and a rolling log tail."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instacore_sync.domain.models import DailyStats, VideoJob
from instacore_sync.ui.viewmodels.dashboard_viewmodel import (
    DashboardViewModel,
    format_bytes_per_second,
    format_eta,
)
from instacore_sync.ui.widgets.stat_card import StatCard
from instacore_sync.ui.widgets.status_badge import StatusBadge
from instacore_sync.workers.signals import PipelineSignalBus


class DashboardView(QWidget):
    def __init__(self, view_model: DashboardViewModel, signal_bus: PipelineSignalBus, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._vm = view_model
        self._row_by_job_id: dict[str, int] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(20)

        header = QVBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Live overview of today's WhatsApp → Drive → Sheets pipeline")
        subtitle.setObjectName("PageSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        # -- stat grid --------------------------------------------------------
        self._stats_grid = QGridLayout()
        self._stats_grid.setSpacing(14)
        self._cards: dict[str, StatCard] = {
            "waiting": StatCard("Waiting", "0", "⏳"),
            "uploading": StatCard("Uploading", "0", "☁"),
            "completed": StatCard("Completed Today", "0", "✅"),
            "failed": StatCard("Failed", "0", "⚠"),
            "needs_review": StatCard("Needs Review", "0", "\U0001F50D"),
            "confidence": StatCard("Avg OCR Confidence", "--", "\U0001F9E0"),
            "speed": StatCard("Transfer Speed", "0 KB/s", "⚡"),
            "eta": StatCard("Est. Time Remaining", "--", "⏱"),
        }
        for i, card in enumerate(self._cards.values()):
            self._stats_grid.addWidget(card, i // 4, i % 4)
        root.addLayout(self._stats_grid)

        # -- active queue table -------------------------------------------------
        queue_section = QLabel("Active Uploads")
        queue_section.setObjectName("SectionTitle")
        root.addWidget(queue_section)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["File", "Device ID", "Status", "Progress", "Speed"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumHeight(220)
        root.addWidget(self._table, stretch=2)

        # -- live log tail --------------------------------------------------------
        log_section = QLabel("Live Log")
        log_section.setObjectName("SectionTitle")
        root.addWidget(log_section)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)
        self._log_view.setObjectName("GlassCard")
        self._log_view.setMinimumHeight(140)
        root.addWidget(self._log_view, stretch=1)

        signal_bus.log_message.connect(self._append_log)
        self._vm.stats_updated.connect(self._on_stats)
        self._vm.job_changed.connect(self._on_job)

    # -- stats -----------------------------------------------------------------

    def _on_stats(self, stats: DailyStats) -> None:
        self._cards["waiting"].set_value(str(stats.waiting))
        self._cards["uploading"].set_value(str(stats.uploading))
        self._cards["completed"].set_value(str(stats.completed))
        self._cards["failed"].set_value(str(stats.failed))
        self._cards["needs_review"].set_value(str(stats.needs_review))
        self._cards["confidence"].set_value(
            f"{stats.avg_ocr_confidence * 100:.0f}%" if stats.avg_ocr_confidence else "--"
        )
        self._cards["speed"].set_value(format_bytes_per_second(stats.current_transfer_speed_bps))
        self._cards["eta"].set_value(format_eta(stats.estimated_seconds_remaining))

    # -- active queue table ------------------------------------------------------

    def _on_job(self, job: VideoJob) -> None:
        from instacore_sync.domain.enums import JobStatus

        terminal = {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.NEEDS_REVIEW,
            JobStatus.DUPLICATE,
        }
        if job.status in terminal:
            self._remove_row(job.job_id)
            return

        row = self._row_by_job_id.get(job.job_id)
        if row is None:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._row_by_job_id[job.job_id] = row

        self._table.setItem(row, 0, QTableWidgetItem(job.original_filename))
        self._table.setItem(row, 1, QTableWidgetItem(job.device_id or "–"))

        badge = StatusBadge(job.status)
        badge_container = QWidget()
        layout = QHBoxLayout(badge_container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(badge)
        layout.addStretch(1)
        self._table.setCellWidget(row, 2, badge_container)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(int(job.progress_fraction * 100))
        self._table.setCellWidget(row, 3, progress)

        self._table.setItem(row, 4, QTableWidgetItem(format_bytes_per_second(job.upload_speed_bps)))

    def _remove_row(self, job_id: str) -> None:
        row = self._row_by_job_id.pop(job_id, None)
        if row is None:
            return
        self._table.removeRow(row)
        for jid, r in list(self._row_by_job_id.items()):
            if r > row:
                self._row_by_job_id[jid] = r - 1

    # -- log tail -------------------------------------------------------------

    def _append_log(self, level: str, message: str) -> None:
        from datetime import datetime

        ts = datetime.now().strftime("%H:%M:%S")
        self._log_view.appendPlainText(f"[{ts}] {level:<7} {message}")
