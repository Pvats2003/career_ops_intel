"""Builds the set of OCR engines to run for a given `OcrEngineName` setting."""

from __future__ import annotations

import threading

from instacore_sync.core.config import OcrSettings
from instacore_sync.domain.enums import OcrEngineName
from instacore_sync.services.ocr.base import OcrEngine
from instacore_sync.services.ocr.paddle_engine import PaddleOcrEngine
from instacore_sync.services.ocr.tesseract_engine import TesseractOcrEngine


class OcrEngineFactory:
    """Lazily constructs and caches OCR engine instances (they are expensive).

    One factory instance is shared by every upload worker thread (via
    `DeviceIdExtractor`), so `engines_for()` can be called concurrently by
    several threads at once — most realistically right at startup, when a
    burst of already-queued videos all start processing together. Without
    a lock, several threads could each see an uncached engine and each
    construct their own (`PaddleOCR(...)` in particular is called out as
    slow specifically because it loads real detection/recognition models),
    wasting significant CPU/memory on redundant loads before only one
    survives as `self._paddle`.
    """

    def __init__(self, settings: OcrSettings) -> None:
        self._settings = settings
        self._tesseract: TesseractOcrEngine | None = None
        self._paddle: PaddleOcrEngine | None = None
        self._lock = threading.Lock()

    def _get_tesseract(self) -> TesseractOcrEngine:
        if self._tesseract is None:
            with self._lock:
                if self._tesseract is None:  # re-check inside the lock
                    self._tesseract = TesseractOcrEngine(self._settings.tesseract_cmd or None)
        return self._tesseract

    def _get_paddle(self) -> PaddleOcrEngine:
        if self._paddle is None:
            with self._lock:
                if self._paddle is None:  # re-check inside the lock
                    self._paddle = PaddleOcrEngine()
        return self._paddle

    def engines_for(self, engine_name: OcrEngineName | None = None) -> list[OcrEngine]:
        """Return the ordered list of engines to try for the given (or configured) mode."""
        mode = engine_name or self._settings.engine
        if mode == OcrEngineName.TESSERACT:
            return [self._get_tesseract()]
        if mode == OcrEngineName.PADDLEOCR:
            return [self._get_paddle()]
        # AUTO: try both, caller picks the highest-confidence match.
        return [self._get_tesseract(), self._get_paddle()]
