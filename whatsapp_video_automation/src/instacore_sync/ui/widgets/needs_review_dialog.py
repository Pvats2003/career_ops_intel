"""Modal dialog for resolving a single Needs Review job: shows a video
thumbnail, what OCR actually read, its confidence, and lets the operator
type the correct Device ID by hand and send it straight to upload."""

from __future__ import annotations

import cv2
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from instacore_sync.domain.models import VideoJob
from instacore_sync.services.video.frame_extractor import FrameExtractor
from instacore_sync.utils.text_sanitize import is_valid_device_id

_THUMBNAIL_SIZE = (280, 280)


def _extract_thumbnail_image(job: VideoJob) -> QImage | None:
    """Best-effort: grab a representative frame from the opening seconds and
    convert it to a QImage (safe to construct off the GUI thread, unlike
    QPixmap). Returns None (never raises) if the video can't be read — the
    video may be corrupted (that's exactly the kind of file that ends up in
    Needs Review) or the path may no longer exist. This does real file I/O
    and video decoding, so it must never run on the GUI thread — a
    corrupted or slow-to-open file would freeze the whole window."""
    try:
        extractor = FrameExtractor()
        for frame in extractor.iter_frames(job.source_path, interval_seconds=0.5, max_seconds=2.0):
            rgb = cv2.cvtColor(frame.image_bgr, cv2.COLOR_BGR2RGB)
            height, width, _channels = rgb.shape
            image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888)
            return image.copy()  # .copy() so it survives `rgb` going out of scope
    except Exception:  # noqa: BLE001 - a bad video must never crash the review dialog
        pass
    return None


class _ThumbnailWorker(QObject):
    """Runs `_extract_thumbnail_image` on a background QThread so opening the
    review dialog never blocks the GUI thread on video decoding."""

    ready = Signal(object)  # QImage | None

    def __init__(self, job: VideoJob) -> None:
        super().__init__()
        self._job = job

    def run(self) -> None:
        self.ready.emit(_extract_thumbnail_image(self._job))


class NeedsReviewDialog(QDialog):
    """Returns the operator's chosen Device ID via `chosen_device_id` after
    `exec()` if they clicked Upload, otherwise None (Cancel/closed)."""

    def __init__(self, job: VideoJob, device_id_pattern: str, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._job = job
        self._pattern = device_id_pattern
        self.chosen_device_id: str | None = None

        self.setWindowTitle(f"Resolve: {job.original_filename}")
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)

        self._thumbnail_label = QLabel("Loading preview…")
        self._thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail_label.setMinimumHeight(_THUMBNAIL_SIZE[1])
        self._thumbnail_label.setObjectName("Muted")
        root.addWidget(self._thumbnail_label)

        # Video decoding is real file I/O and can be slow (or hang) on a
        # corrupted or slow-to-open file — exactly the kind of file that
        # ends up in Needs Review — so it must never run on the GUI thread.
        # Decode on a worker QThread; only the resulting QImage crosses
        # back (QPixmap itself may only be constructed on the GUI thread).
        self._thumbnail_thread = QThread(self)
        self._thumbnail_worker = _ThumbnailWorker(job)
        self._thumbnail_worker.moveToThread(self._thumbnail_thread)
        self._thumbnail_thread.started.connect(self._thumbnail_worker.run)
        self._thumbnail_worker.ready.connect(self._on_thumbnail_ready)
        self._thumbnail_thread.start()

        info_form = QFormLayout()
        detected_text_label = QLabel(job.ocr_raw_text or "(nothing legible was read)")
        detected_text_label.setWordWrap(True)
        info_form.addRow("Detected text:", detected_text_label)

        confidence_label = QLabel(
            f"{job.ocr_confidence * 100:.0f}%" if job.ocr_confidence else "0% (no match found)"
        )
        info_form.addRow("OCR confidence:", confidence_label)

        reason_label = QLabel(job.last_error or "—")
        reason_label.setWordWrap(True)
        info_form.addRow("Reason:", reason_label)
        root.addLayout(info_form)

        entry_row = QHBoxLayout()
        entry_label = QLabel("Device ID:")
        self._device_id_edit = QLineEdit(job.device_id or "")
        self._device_id_edit.setPlaceholderText("e.g. IC-188")
        self._device_id_edit.textChanged.connect(self._validate_input)
        entry_row.addWidget(entry_label)
        entry_row.addWidget(self._device_id_edit, stretch=1)
        root.addLayout(entry_row)

        self._validation_label = QLabel(" ")
        self._validation_label.setObjectName("Muted")
        root.addWidget(self._validation_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._upload_button = buttons.addButton("Upload", QDialogButtonBox.ButtonRole.AcceptRole)
        self._upload_button.setObjectName("PrimaryButton")
        buttons.accepted.connect(self._on_upload_clicked)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._validate_input(self._device_id_edit.text())

    def _on_thumbnail_ready(self, image: QImage | None) -> None:
        self._thumbnail_thread.quit()
        self._thumbnail_thread.wait()
        if image is not None:
            pixmap = QPixmap.fromImage(image).scaled(
                *_THUMBNAIL_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self._thumbnail_label.setPixmap(pixmap)
            self._thumbnail_label.setText("")
        else:
            self._thumbnail_label.setText("(No preview available)")

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt override signature
        self._stop_thumbnail_thread()
        super().closeEvent(event)

    def reject(self) -> None:
        self._stop_thumbnail_thread()
        super().reject()

    def _stop_thumbnail_thread(self) -> None:
        # If the dialog is closed before decoding finishes, don't destroy the
        # QThread while it's still running the worker.
        if self._thumbnail_thread.isRunning():
            self._thumbnail_thread.quit()
            self._thumbnail_thread.wait()

    def _validate_input(self, text: str) -> None:
        text = text.strip().upper()
        valid = is_valid_device_id(text, self._pattern)
        self._upload_button.setEnabled(valid)
        self._validation_label.setText(
            "" if valid or not text else "Doesn't look like a valid Device ID (expected e.g. IC-188)."
        )

    def _on_upload_clicked(self) -> None:
        self.chosen_device_id = self._device_id_edit.text().strip().upper()
        self.accept()
