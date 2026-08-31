"""Unit tests for Device ID normalization and pattern matching.

We exercise `DeviceIdExtractor` directly with fake frames/engines rather
than real video files or OCR binaries, so these tests run fast and don't
require Tesseract/PaddleOCR to be installed in CI.

`_FakeEngine` is call-count indexed (not a plain iterator) because the
extractor may call an engine multiple times per frame — once per
preprocessing variant (default / Otsu / rotated) — whenever a variant
produces no regex match at all; a flat iterator would raise StopIteration
the moment a test wants to assert "no match anywhere" behavior.
"""

from __future__ import annotations

import numpy as np
import pytest

from instacore_sync.core.config import OcrSettings
from instacore_sync.domain.enums import OcrEngineName, OcrEngineStatus
from instacore_sync.services.ocr.base import OcrReadResult
from instacore_sync.services.ocr.device_id_extractor import DeviceIdExtractor
from instacore_sync.services.video.frame_extractor import Frame

_NO_MATCH = OcrReadResult(text="no device here", confidence=0.8)


class _FakeEngine:
    """Returns `overrides[call_index]` if present, else `default`, per call."""

    def __init__(
        self,
        name: OcrEngineName,
        default: OcrReadResult = _NO_MATCH,
        overrides: dict[int, OcrReadResult] | None = None,
    ) -> None:
        self.name = name
        self._default = default
        self._overrides = overrides or {}
        self.call_count = 0

    def status(self) -> OcrEngineStatus:
        return OcrEngineStatus.READY

    def read_text(self, image_bgr: np.ndarray) -> OcrReadResult:
        idx = self.call_count
        self.call_count += 1
        return self._overrides.get(idx, self._default)


class _FakeEngineFactory:
    def __init__(self, engines: list) -> None:
        self._engines = engines

    def engines_for(self, engine_name=None):
        return self._engines


def _non_blank_frame(seed: int) -> np.ndarray:
    """A small synthetic frame with real pixel variance (not near-uniform),
    so it survives `is_frame_likely_blank`'s pre-filter like a real screen
    recording frame would."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(40, 40, 3), dtype=np.uint8)


class _FakeFrameExtractor:
    def __init__(self, frame_count: int = 3) -> None:
        self._frame_count = frame_count

    def iter_frames(self, video_path, *, interval_seconds, max_seconds, full_video=False):
        for i in range(self._frame_count):
            yield Frame(timestamp_seconds=i * interval_seconds, image_bgr=_non_blank_frame(seed=i))


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
    """A match on the very first frame/variant is returned immediately,
    without examining later frames."""
    settings = OcrSettings(min_confidence=0.5)
    engine = _FakeEngine(
        OcrEngineName.TESSERACT,
        overrides={0: OcrReadResult(text="Device: IC-188", confidence=0.95)},
    )
    extractor = DeviceIdExtractor(settings, _FakeFrameExtractor(frame_count=3), _FakeEngineFactory([engine]))

    result = extractor.extract(video_path=__file__)  # path unused by fake extractor

    assert result.succeeded
    assert result.device_id == "IC-188"
    assert result.confidence == pytest.approx(0.95)
    assert result.frames_examined == 1
    assert engine.call_count == 1  # matched on the first (default) variant — no escalation needed


def test_extract_escalates_to_alternate_variant_before_giving_up_on_a_frame() -> None:
    """If the default preprocessing variant finds nothing at all on a frame,
    the extractor retries that same frame with the Otsu-threshold variant
    before moving on — this is the "retry, only then Needs Review" behavior."""
    settings = OcrSettings(min_confidence=0.5)
    engine = _FakeEngine(
        OcrEngineName.TESSERACT,
        overrides={1: OcrReadResult(text="Device: IC-188", confidence=0.95)},  # 2nd call = otsu variant
    )
    extractor = DeviceIdExtractor(settings, _FakeFrameExtractor(frame_count=1), _FakeEngineFactory([engine]))

    result = extractor.extract(video_path=__file__)

    assert result.succeeded
    assert result.device_id == "IC-188"
    assert engine.call_count == 2  # default variant (no match) then otsu variant (match)


def test_extract_scans_multiple_frames_until_match_found() -> None:
    """A frame that yields nothing on any variant contributes nothing, but
    the scan continues to the next sampled frame rather than giving up."""
    settings = OcrSettings(min_confidence=0.5)
    # Frame 0 exhausts all 3 variants with no match (calls 0,1,2); frame 1's
    # default variant (call 3) matches.
    engine = _FakeEngine(
        OcrEngineName.TESSERACT,
        overrides={3: OcrReadResult(text="Device: IC-551", confidence=0.9)},
    )
    extractor = DeviceIdExtractor(settings, _FakeFrameExtractor(frame_count=2), _FakeEngineFactory([engine]))

    result = extractor.extract(video_path=__file__)

    assert result.succeeded
    assert result.device_id == "IC-551"
    assert result.frames_examined == 2
    assert engine.call_count == 4


def test_extract_falls_back_to_low_confidence_best_match_without_full_scan() -> None:
    settings = OcrSettings(min_confidence=0.9, full_scan_on_low_confidence=False)
    engine = _FakeEngine(OcrEngineName.TESSERACT, default=OcrReadResult(text="IC-23 maybe", confidence=0.6))
    extractor = DeviceIdExtractor(settings, _FakeFrameExtractor(frame_count=1), _FakeEngineFactory([engine]))

    result = extractor.extract(video_path=__file__)

    assert result.device_id == "IC-23"
    assert result.confidence == pytest.approx(0.6)


def test_extract_returns_no_match_when_nothing_found() -> None:
    settings = OcrSettings(full_scan_on_low_confidence=False)
    engine = _FakeEngine(OcrEngineName.TESSERACT, default=_NO_MATCH)
    extractor = DeviceIdExtractor(settings, _FakeFrameExtractor(frame_count=1), _FakeEngineFactory([engine]))

    result = extractor.extract(video_path=__file__)

    assert not result.succeeded
    assert result.device_id is None


def test_extract_skips_blank_frames_without_calling_engine() -> None:
    """A near-uniform (blank/loading-screen) frame should never reach the
    OCR engine at all — this is the "dynamic frame selection" optimization."""

    class _AllBlankFrameExtractor:
        def iter_frames(self, video_path, *, interval_seconds, max_seconds, full_video=False):
            for i in range(3):
                yield Frame(timestamp_seconds=i * 0.5, image_bgr=np.zeros((40, 40, 3), dtype=np.uint8))

    settings = OcrSettings(full_scan_on_low_confidence=False)
    engine = _FakeEngine(OcrEngineName.TESSERACT)
    extractor = DeviceIdExtractor(settings, _AllBlankFrameExtractor(), _FakeEngineFactory([engine]))

    result = extractor.extract(video_path=__file__)

    assert not result.succeeded
    assert engine.call_count == 0
    assert result.frames_examined == 0
