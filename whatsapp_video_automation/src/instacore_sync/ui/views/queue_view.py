"""Full upload queue: every non-terminal job, plus items awaiting manual review."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob
from instacore_sync.ui.widgets.status_badge import StatusBadge
from instacore_sync.workers.signals import PipelineSignalBus

_REFRESH_INTERVAL_MS = 2000

_ALL_STATUSES = list(JobStatus)


class QueueView(QWidget):
    def __init__(self, jobs_repo: JobsRepository, signal_bus: PipelineSignalBus, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._jobs_repo = jobs_repo

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Upload Queue")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Every video currently in flight, plus items waiting on manual review")
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)

        self._filter_combo = QComboBox()
        self._filter_combo.addItem("All active", None)
        for status in _ALL_STATUSES:
            self._filter_combo.addItem(status.value.replace("_", " ").title(), status)
        self._filter_combo.currentIndexChanged.connect(lambda _: self.refresh())
        header.addWidget(self._filter_combo)
        root.addLayout(header)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["File", "Device ID", "Status", "OCR Confidence", "Attempts", "Last Error"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, stretch=1)

        signal_bus.job_updated.connect(lambda _job: self.refresh())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(_REFRESH_INTERVAL_MS)
        self.refresh()

    def refresh(self) -> None:
        selected_status = self._filter_combo.currentData()
        if selected_status is None:
            jobs = self._jobs_repo.list_active() + self._jobs_repo.list_by_status(
                JobStatus.NEEDS_REVIEW
            )
        else:
            jobs = self._jobs_repo.list_by_status(selected_status)

        self._table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            self._populate_row(row, job)

    def _populate_row(self, row: int, job: VideoJob) -> None:
        self._table.setItem(row, 0, QTableWidgetItem(job.original_filename))
        self._table.setItem(row, 1, QTableWidgetItem(job.device_id or "–"))

        badge_container = QWidget()
        layout = QHBoxLayout(badge_container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(StatusBadge(job.status))
        layout.addStretch(1)
        self._table.setCellWidget(row, 2, badge_container)

        confidence_text = f"{job.ocr_confidence * 100:.0f}%" if job.ocr_confidence else "–"
        self._table.setItem(row, 3, QTableWidgetItem(confidence_text))
        self._table.setItem(row, 4, QTableWidgetItem(str(job.attempt_count)))
        self._table.setItem(row, 5, QTableWidgetItem(job.last_error or ""))
