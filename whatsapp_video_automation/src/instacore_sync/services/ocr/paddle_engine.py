"""PaddleOCR backend — heavier but often more accurate on stylized UI fonts.

Loaded lazily: constructing `PaddleOCR()` downloads/loads detection +
recognition models, which is slow the first time and unnecessary if the
user only ever selects Tesseract.
"""

from __future__ import annotations

import threading
from contextlib import suppress
from typing import Any

import numpy as np

from instacore_sync.core.exceptions import OcrEngineError
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.domain.enums import OcrEngineName, OcrEngineStatus
from instacore_sync.services.ocr.base import OcrReadResult

logger = get_logger(__name__)


class PaddleOcrEngine:
    """Wraps PaddleOCR behind the same `OcrEngine` interface as Tesseract."""

    name = OcrEngineName.PADDLEOCR

    def __init__(self) -> None:
        self._status = OcrEngineStatus.UNKNOWN
        self._reader: Any | None = None
        # One PaddleOcrEngine instance is shared across every upload worker
        # thread (via OcrEngineFactory). Guards both lazy construction
        # (several threads racing an uncached reader would each trigger a
        # full, slow model load) and, in `read_text`, the actual inference
        # call — PaddleOCR's predictor is not documented as safe for
        # concurrent inference from multiple threads on one instance, and
        # a corrupted/crashing concurrent call would be far worse than the
        # reduced parallelism this lock trades for.
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._reader is not None:
            return
        with self._lock:
            if self._reader is not None:  # re-check inside the lock
                return
            try:
                from paddleocr import PaddleOCR

                self._reader = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
                self._status = OcrEngineStatus.READY
            except Exception as exc:  # noqa: BLE001 - engine availability probe
                logger.warning("ocr.paddleocr.unavailable", error=str(exc))
                self._status = OcrEngineStatus.UNAVAILABLE
                raise OcrEngineError(f"PaddleOCR could not be initialized: {exc}") from exc

    def status(self) -> OcrEngineStatus:
        if self._status == OcrEngineStatus.UNKNOWN:
            with suppress(OcrEngineError):
                self._ensure_loaded()
        return self._status

    def read_text(self, image_bgr: np.ndarray) -> OcrReadResult:
        self._ensure_loaded()
        assert self._reader is not None

        try:
            # PaddleOCR expects a 3-channel image.
            image = image_bgr
            if image.ndim == 2:
                import cv2

                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            with self._lock:
                result = self._reader.ocr(image, cls=False)
        except Exception as exc:  # noqa: BLE001
            self._status = OcrEngineStatus.ERROR
            raise OcrEngineError(f"PaddleOCR failed to process frame: {exc}") from exc

        lines = result[0] if result else []
        words: list[str] = []
        confidences: list[float] = []
        for line in lines or []:
            # Some PaddleOCR versions return `[[None]]` (not `[[]]`) for "no
            # text detected" on a frame, giving `lines = [None]` — unpacking
            # `_box, (text, conf) = None` raises TypeError. A malformed/
            # unexpected line shape is treated the same as "nothing read on
            # this line" (skipped) rather than crashing the whole read —
            # this is an ordinary blank/no-match frame, not an OCR failure.
            if not line:
                continue
            try:
                _box, (text, conf) = line
            except (TypeError, ValueError):
                logger.debug("ocr.paddleocr.unexpected_line_shape", line=repr(line))
                continue
            if text:
                words.append(text)
                confidences.append(float(conf))

        joined = " ".join(words)
        avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
        return OcrReadResult(text=joined, confidence=avg_conf)
