"""Needs Review: every video OCR couldn't confidently read a Device ID
from. Each row opens `NeedsReviewDialog` to see the frame, what OCR read,
and pick the correct Device ID by hand — see docs/ARCHITECTURE.md."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instacore_sync.core.config import AppSettings
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob
from instacore_sync.ui.widgets.needs_review_dialog import NeedsReviewDialog
from instacore_sync.workers.pipeline_thread import PipelineThread
from instacore_sync.workers.signals import PipelineSignalBus

_REFRESH_INTERVAL_MS = 2000


class NeedsReviewView(QWidget):
    def __init__(
        self,
        jobs_repo: JobsRepository,
        signal_bus: PipelineSignalBus,
        pipeline_thread: PipelineThread,
        settings: AppSettings,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self._jobs_repo = jobs_repo
        self._pipeline_thread = pipeline_thread
        self._settings = settings

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        header = QVBoxLayout()
        title = QLabel("Needs Review")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Videos OCR couldn't confidently read — pick the Device ID by hand and upload")
        subtitle.setObjectName("PageSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["File", "Detected Text", "Confidence", "Reason", ""])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, stretch=1)

        self._dirty = False
        signal_bus.job_updated.connect(self._mark_dirty)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_if_dirty)
        self._timer.start(_REFRESH_INTERVAL_MS)
        self.refresh()

    def _mark_dirty(self, _job: VideoJob) -> None:
        # Any job update can affect this list — either a video just landed
        # in Needs Review, or one was just resolved and should drop off it.
        self._dirty = True

    def _refresh_if_dirty(self) -> None:
        if self._dirty:
            self.refresh()

    def refresh(self) -> None:
        self._dirty = False
        jobs = self._jobs_repo.list_by_status(JobStatus.NEEDS_REVIEW)
        self._table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            self._populate_row(row, job)

    def _populate_row(self, row: int, job: VideoJob) -> None:
        self._table.setItem(row, 0, QTableWidgetItem(job.original_filename))
        self._table.setItem(row, 1, QTableWidgetItem((job.ocr_raw_text or "").strip() or "—"))
        confidence_text = f"{job.ocr_confidence * 100:.0f}%" if job.ocr_confidence else "0%"
        self._table.setItem(row, 2, QTableWidgetItem(confidence_text))
        self._table.setItem(row, 3, QTableWidgetItem(job.last_error or ""))

        resolve_button = QPushButton("Resolve…")
        resolve_button.setObjectName("PrimaryButton")
        resolve_button.clicked.connect(lambda _checked, j=job: self._on_resolve_clicked(j))
        self._table.setCellWidget(row, 4, resolve_button)

    def _on_resolve_clicked(self, job: VideoJob) -> None:
        if not job.source_path.exists():
            QMessageBox.warning(
                self,
                "Can't resolve",
                f"{job.original_filename} no longer exists at its expected location:\n{job.source_path}",
            )
            return

        dialog = NeedsReviewDialog(job, self._settings.ocr.device_id_pattern, parent=self)
        if dialog.exec() == NeedsReviewDialog.DialogCode.Accepted and dialog.chosen_device_id:
            self._pipeline_thread.resolve_needs_review(job.job_id, dialog.chosen_device_id)
            self._dirty = True
