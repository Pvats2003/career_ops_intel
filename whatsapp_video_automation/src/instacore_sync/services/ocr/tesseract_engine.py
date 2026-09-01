"""Tesseract OCR backend (via pytesseract)."""

from __future__ import annotations

import numpy as np

from instacore_sync.core.exceptions import OcrEngineError
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.domain.enums import OcrEngineName, OcrEngineStatus
from instacore_sync.services.ocr.base import OcrReadResult

logger = get_logger(__name__)

_TESSERACT_CONFIG = "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-:"


class TesseractOcrEngine:
    """Fast, CPU-only, zero-model-download OCR engine — good default choice."""

    name = OcrEngineName.TESSERACT

    def __init__(self, tesseract_cmd: str | None = None) -> None:
        self._status = OcrEngineStatus.UNKNOWN
        self._configure(tesseract_cmd)

    def _configure(self, tesseract_cmd: str | None) -> None:
        try:
            import pytesseract

            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            pytesseract.get_tesseract_version()
            self._status = OcrEngineStatus.READY
        except Exception as exc:  # noqa: BLE001 - engine availability probe
            logger.warning("ocr.tesseract.unavailable", error=str(exc))
            self._status = OcrEngineStatus.UNAVAILABLE

    def status(self) -> OcrEngineStatus:
        return self._status

    def read_text(self, image_bgr: np.ndarray) -> OcrReadResult:
        if self._status != OcrEngineStatus.READY:
            raise OcrEngineError("Tesseract is not available on this system")

        import pytesseract

        try:
            data = pytesseract.image_to_data(
                image_bgr, config=_TESSERACT_CONFIG, output_type=pytesseract.Output.DICT
            )
        except Exception as exc:  # noqa: BLE001
            raise OcrEngineError(f"Tesseract failed to process frame: {exc}") from exc

        words: list[str] = []
        confidences: list[float] = []
        for text, conf in zip(data.get("text", []), data.get("conf", []), strict=False):
            text = text.strip()
            try:
                conf_f = float(conf)
            except (TypeError, ValueError):
                continue
            if text and conf_f >= 0:
                words.append(text)
                confidences.append(conf_f)

        joined = " ".join(words)
        avg_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
        return OcrReadResult(text=joined, confidence=avg_conf)
