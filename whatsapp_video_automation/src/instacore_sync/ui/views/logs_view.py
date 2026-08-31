"""Searchable, filterable, exportable audit log (backed by SQLite `upload_logs`)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.ui.widgets.status_badge import StatusBadge


class LogsView(QWidget):
    def __init__(self, logs_repo: LogsRepository, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._logs_repo = logs_repo

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        header = QVBoxLayout()
        title = QLabel("Upload Logs")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Every processed video — searchable by Device ID, filename, or status")
        subtitle.setObjectName("PageSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        filters = QHBoxLayout()
        filters.setSpacing(10)

        self._device_input = QLineEdit()
        self._device_input.setPlaceholderText("Filter by Device ID (e.g. IC-188)")
        self._filename_input = QLineEdit()
        self._filename_input.setPlaceholderText("Filter by filename")

        self._status_combo = QComboBox()
        self._status_combo.addItem("All statuses", None)
        for status in JobStatus:
            self._status_combo.addItem(status.value.replace("_", " ").title(), status)

        search_button = QPushButton("Search")
        search_button.setObjectName("PrimaryButton")
        search_button.clicked.connect(self.refresh)

        export_button = QPushButton("Export CSV")
        export_button.clicked.connect(self._export_csv)

        filters.addWidget(self._device_input)
        filters.addWidget(self._filename_input)
        filters.addWidget(self._status_combo)
        filters.addWidget(search_button)
        filters.addStretch(1)
        filters.addWidget(export_button)
        root.addLayout(filters)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Filename", "Device ID", "Status", "OCR Confidence", "Engine", "Drive Link", "Completed At"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, stretch=1)

        self.refresh()

    def refresh(self) -> None:
        entries = self._logs_repo.search(
            device_id=self._device_input.text().strip() or None,
            filename_contains=self._filename_input.text().strip() or None,
            status=self._status_combo.currentData(),
            limit=1000,
        )
        self._table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self._table.setItem(row, 0, QTableWidgetItem(entry.filename))
            self._table.setItem(row, 1, QTableWidgetItem(entry.device_id or "–"))

            badge_container = QWidget()
            layout = QHBoxLayout(badge_container)
            layout.setContentsMargins(4, 2, 4, 2)
            layout.addWidget(StatusBadge(entry.status))
            layout.addStretch(1)
            self._table.setCellWidget(row, 2, badge_container)

            confidence_text = f"{entry.ocr_confidence * 100:.0f}%" if entry.ocr_confidence else "–"
            self._table.setItem(row, 3, QTableWidgetItem(confidence_text))
            self._table.setItem(row, 4, QTableWidgetItem(entry.ocr_engine_used or "–"))
            self._table.setItem(row, 5, QTableWidgetItem(entry.drive_link or entry.error_message or ""))
            completed = entry.completed_at.strftime("%Y-%m-%d %H:%M:%S") if entry.completed_at else "–"
            self._table.setItem(row, 6, QTableWidgetItem(completed))

    def _export_csv(self) -> None:
        default_path = str(Path.home() / "instacore_sync_logs.csv")
        path_str, _ = QFileDialog.getSaveFileName(self, "Export Logs to CSV", default_path, "CSV Files (*.csv)")
        if not path_str:
            return
        try:
            self._logs_repo.export_csv(Path(path_str))
            QMessageBox.information(self, "Export complete", f"Logs exported to:\n{path_str}")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
