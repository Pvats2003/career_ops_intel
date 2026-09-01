"""Builds the set of OCR engines to run for a given `OcrEngineName` setting."""

from __future__ import annotations

from instacore_sync.core.config import OcrSettings
from instacore_sync.domain.enums import OcrEngineName
from instacore_sync.services.ocr.base import OcrEngine
from instacore_sync.services.ocr.paddle_engine import PaddleOcrEngine
from instacore_sync.services.ocr.tesseract_engine import TesseractOcrEngine


class OcrEngineFactory:
    """Lazily constructs and caches OCR engine instances (they are expensive)."""

    def __init__(self, settings: OcrSettings) -> None:
        self._settings = settings
        self._tesseract: TesseractOcrEngine | None = None
        self._paddle: PaddleOcrEngine | None = None

    def _get_tesseract(self) -> TesseractOcrEngine:
        if self._tesseract is None:
            self._tesseract = TesseractOcrEngine(self._settings.tesseract_cmd or None)
        return self._tesseract

    def _get_paddle(self) -> PaddleOcrEngine:
        if self._paddle is None:
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
