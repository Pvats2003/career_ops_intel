"""A pill-shaped label whose color follows `JobStatus` (styled via QSS `status` property)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from instacore_sync.domain.enums import JobStatus

_DISPLAY_TEXT = {
    JobStatus.DISCOVERED: "Discovered",
    JobStatus.QUEUED: "Queued",
    JobStatus.EXTRACTING: "Reading ID",
    JobStatus.HASHING: "Hashing",
    JobStatus.DUPLICATE: "Duplicate",
    JobStatus.UPLOADING: "Uploading",
    JobStatus.UPDATING_SHEET: "Updating Sheet",
    JobStatus.COMPLETED: "Completed",
    JobStatus.NEEDS_REVIEW: "Needs Review",
    JobStatus.FAILED: "Failed",
}


class StatusBadge(QLabel):
    def __init__(self, status: JobStatus, parent=None) -> None:  # noqa: ANN001
        super().__init__(_DISPLAY_TEXT.get(status, status.value), parent)
        self.set_status(status)

    def set_status(self, status: JobStatus) -> None:
        self.setText(_DISPLAY_TEXT.get(status, status.value))
        self.setProperty("status", status.value)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
