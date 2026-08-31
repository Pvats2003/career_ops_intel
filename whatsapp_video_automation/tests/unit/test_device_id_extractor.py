"""Unit tests for Device ID normalization and pattern matching.

We exercise `DeviceIdExtractor._normalize` and `_scan`'s regex matching
directly with fake frames/engines rather than real video files or OCR
binaries, so these tests run fast and don't require Tesseract/PaddleOCR to
be installed in CI.
"""

from __future__ import annotations

import numpy as np
import pytest

from instacore_sync.core.config import OcrSettings
from instacore_sync.domain.enums import OcrEngineName, OcrEngineStatus
from instacore_sync.services.ocr.base import OcrReadResult
from instacore_sync.services.ocr.device_id_extractor import DeviceIdExtractor
from instacore_sync.services.video.frame_extractor import Frame


class _FakeEngine:
    def __init__(self, name: OcrEngineName, texts_by_call: list[OcrReadResult]) -> None:
        self.name = name
        self._texts = iter(texts_by_call)

    def status(self) -> OcrEngineStatus:
        return OcrEngineStatus.READY

    def read_text(self, image_bgr: np.ndarray) -> OcrReadResult:
        return next(self._texts)


class _FakeEngineFactory:
    def __init__(self, engines: list) -> None:
        self._engines = engines

    def engines_for(self, engine_name=None):
        return self._engines


class _FakeFrameExtractor:
    def __init__(self, frame_count: int = 3) -> None:
        self._frame_count = frame_count

    def iter_frames(self, video_path, *, interval_seconds, max_seconds, full_video=False):
        for i in range(self._frame_count):
            yield Frame(timestamp_seconds=i * interval_seconds, image_bgr=np.zeros((10, 10, 3), dtype=np.uint8))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("IC-188", "IC-188"),
        ("ic-188", "IC-188"),
        ("IC 188", "IC-188"),
        ("IC188", "IC-188"),
        ("ic551", "IC-551"),
    ],
)
def test_normalize_device_id(raw: str, expected: str) -> None:
    settings = OcrSettings()
    extractor = DeviceIdExtractor(settings, _FakeFrameExtractor(0), _FakeEngineFactory([]))
    assert extractor._normalize(raw) == expected


def test_extract_returns_high_confidence_match_and_stops_early() -> None:
    settings = OcrSettings(min_confidence=0.5)
    engine = _FakeEngine(
        OcrEngineName.TESSERACT,
        [
            OcrReadResult(text="garbage", confidence=0.9),
            OcrReadResult(text="Device: IC-188", confidence=0.95),
            OcrReadResult(text="unused", confidence=0.99),
        ],
    )
    extractor = DeviceIdExtractor(
        settings, _FakeFrameExtractor(frame_count=3), _FakeEngineFactory([engine])
    )

    result = extractor.extract(video_path=__file__)  # path unused by fake extractor

    assert result.succeeded
    assert result.device_id == "IC-188"
    assert result.confidence == pytest.approx(0.95)
    assert result.frames_examined == 2  # stopped after the second frame


def test_extract_falls_back_to_low_confidence_best_match_without_full_scan() -> None:
    settings = OcrSettings(min_confidence=0.9, full_scan_on_low_confidence=False)
    engine = _FakeEngine(
        OcrEngineName.TESSERACT,
        [OcrReadResult(text="IC-23 maybe", confidence=0.6)] * 1,
    )
    extractor = DeviceIdExtractor(
        settings, _FakeFrameExtractor(frame_count=1), _FakeEngineFactory([engine])
    )

    result = extractor.extract(video_path=__file__)

    assert result.device_id == "IC-23"
    assert result.confidence == pytest.approx(0.6)


def test_extract_returns_no_match_when_nothing_found() -> None:
    settings = OcrSettings(full_scan_on_low_confidence=False)
    engine = _FakeEngine(OcrEngineName.TESSERACT, [OcrReadResult(text="no device here", confidence=0.8)])
    extractor = DeviceIdExtractor(
        settings, _FakeFrameExtractor(frame_count=1), _FakeEngineFactory([engine])
    )

    result = extractor.extract(video_path=__file__)

    assert not result.succeeded
    assert result.device_id is None
