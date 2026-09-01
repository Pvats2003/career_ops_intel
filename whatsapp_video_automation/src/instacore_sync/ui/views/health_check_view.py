"""Health Check page: runs `services/health/health_check_service.py`'s
battery of checks and shows each as a PASS/WARNING/FAILED row with a
suggested fix — the page a non-technical user (or whoever is helping
them) opens first when something seems wrong, instead of reading logs."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instacore_sync.domain.enums import HealthStatus
from instacore_sync.domain.models import HealthCheckResult
from instacore_sync.workers.pipeline_thread import PipelineThread
from instacore_sync.workers.signals import PipelineSignalBus

_STATUS_LABEL = {
    HealthStatus.PASS: "✅ PASS",
    HealthStatus.WARNING: "⚠️ WARNING",
    HealthStatus.FAILED: "❌ FAILED",
}
# Matches dark_theme.qss's own palette rather than introducing new colors.
_STATUS_COLOR = {
    HealthStatus.PASS: QColor("#5DE0E6"),
    HealthStatus.WARNING: QColor("#FBBF24"),
    HealthStatus.FAILED: QColor("#FF8FA3"),
}


class HealthCheckView(QWidget):
    def __init__(
        self,
        signal_bus: PipelineSignalBus,
        pipeline_thread: PipelineThread,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self._pipeline_thread = pipeline_thread

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        header = QVBoxLayout()
        title = QLabel("Health Check")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Internet, Google Drive/Sheets, OCR, disk space, and the background pipeline")
        subtitle.setObjectName("PageSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        toolbar = QVBoxLayout()
        self._run_button = QPushButton("Run Health Check")
        self._run_button.setObjectName("PrimaryButton")
        self._run_button.clicked.connect(self._on_run_clicked)
        toolbar.addWidget(self._run_button)
        root.addLayout(toolbar)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Check", "Status", "Details", "Suggested Fix"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, stretch=1)

        self._status_label = QLabel("Click \"Run Health Check\" to check everything.")
        self._status_label.setObjectName("Muted")
        root.addWidget(self._status_label)

        signal_bus.health_check_completed.connect(self._on_results)
        self._has_run = False

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        # Auto-run the first time this page is opened, so a user who
        # navigates here to see what's wrong doesn't have to know to
        # click a button first — but never re-run automatically on every
        # subsequent visit (that would surprise someone just glancing at
        # results from a moment ago, and each run does real network I/O).
        super().showEvent(event)
        if not self._has_run:
            self._on_run_clicked()

    def _on_run_clicked(self) -> None:
        self._has_run = True
        self._run_button.setEnabled(False)
        self._run_button.setText("Running…")
        self._status_label.setText("Running checks — this reaches the internet, Drive, and Sheets…")
        self._pipeline_thread.request_health_check()

    def _on_results(self, results: list[HealthCheckResult]) -> None:
        self._run_button.setEnabled(True)
        self._run_button.setText("Run Health Check")
        self._table.setRowCount(len(results))
        for row, result in enumerate(results):
            self._populate_row(row, result)

        failed = sum(1 for r in results if r.status == HealthStatus.FAILED)
        warned = sum(1 for r in results if r.status == HealthStatus.WARNING)
        if failed:
            self._status_label.setText(f"{failed} check(s) failed, {warned} warning(s) — see suggested fixes below.")
        elif warned:
            self._status_label.setText(f"{warned} warning(s) — everything else looks good.")
        else:
            self._status_label.setText("All checks passed.")

    def _populate_row(self, row: int, result: HealthCheckResult) -> None:
        self._table.setItem(row, 0, QTableWidgetItem(result.name))

        status_item = QTableWidgetItem(_STATUS_LABEL[result.status])
        status_item.setForeground(_STATUS_COLOR[result.status])
        self._table.setItem(row, 1, status_item)

        self._table.setItem(row, 2, QTableWidgetItem(result.message))
        self._table.setItem(row, 3, QTableWidgetItem(result.suggested_fix or "—"))
