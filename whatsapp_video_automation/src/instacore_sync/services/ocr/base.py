"""OCR engine abstraction.

Every engine (Tesseract, PaddleOCR, ...) implements `OcrEngine.read_text`,
returning plain text plus a single 0-1 confidence score. This lets
`device_id_extractor.py` treat all engines uniformly and pick whichever
produced the highest-confidence, pattern-matching result — the "allow
switching OCR engines" and "try multiple OCR engines, choose highest
confidence" requirements both live entirely behind this interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from instacore_sync.domain.enums import OcrEngineName, OcrEngineStatus


@dataclass(frozen=True, slots=True)
class OcrReadResult:
    text: str
    confidence: float  # 0.0 - 1.0


class OcrEngine(Protocol):
    """Structural interface every OCR backend must satisfy."""

    name: OcrEngineName

    def read_text(self, image_bgr: np.ndarray) -> OcrReadResult: ...

    def status(self) -> OcrEngineStatus: ...
