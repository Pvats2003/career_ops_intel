"""Regression tests for concurrent OCR engine construction/use.

`OcrEngineFactory` and `PaddleOcrEngine` are both shared across every
upload worker thread. Without locking, several threads racing an uncached
engine could each independently construct their own (wasting CPU/memory on
redundant model loads), and PaddleOCR's predictor could be called
concurrently from multiple threads on one shared instance — not documented
as safe. `paddleocr` isn't installed in this environment (an optional,
heavy dependency), so `PaddleOCR` itself is faked via `sys.modules`.
"""

from __future__ import annotations

import sys
import threading
import time
import types

import pytest

from instacore_sync.core.config import OcrSettings
from instacore_sync.services.ocr.engine_factory import OcrEngineFactory
from instacore_sync.services.ocr.paddle_engine import PaddleOcrEngine


def test_engine_factory_constructs_each_engine_exactly_once_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tesseract_build_count = 0
    paddle_build_count = 0

    class _SlowFakeTesseract:
        def __init__(self, *_a, **_kw) -> None:
            nonlocal tesseract_build_count
            time.sleep(0.02)  # widen the race window
            tesseract_build_count += 1

    class _SlowFakePaddle:
        def __init__(self, *_a, **_kw) -> None:
            nonlocal paddle_build_count
            time.sleep(0.02)
            paddle_build_count += 1

    monkeypatch.setattr("instacore_sync.services.ocr.engine_factory.TesseractOcrEngine", _SlowFakeTesseract)
    monkeypatch.setattr("instacore_sync.services.ocr.engine_factory.PaddleOcrEngine", _SlowFakePaddle)

    from instacore_sync.domain.enums import OcrEngineName

    factory = OcrEngineFactory(OcrSettings(engine=OcrEngineName.AUTO))

    def _use_factory() -> None:
        factory.engines_for()

    threads = [threading.Thread(target=_use_factory) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert tesseract_build_count == 1, "Tesseract engine was constructed more than once under concurrency"
    assert paddle_build_count == 1, "Paddle engine was constructed more than once under concurrency"


@pytest.fixture
def fake_paddleocr_module(monkeypatch: pytest.MonkeyPatch):
    """Installs a fake `paddleocr` module in `sys.modules` so
    `PaddleOcrEngine._ensure_loaded`'s inline `from paddleocr import
    PaddleOCR` succeeds without the real (heavy, not installed here)
    dependency."""
    build_count = 0
    call_count = 0
    max_concurrent_calls = 0
    in_flight = 0
    in_flight_lock = threading.Lock()

    class _FakePaddleOCR:
        def __init__(self, *_a, **_kw) -> None:
            nonlocal build_count
            time.sleep(0.02)
            build_count += 1

        def ocr(self, _image, cls=False):  # noqa: ANN001, FBT002
            nonlocal call_count, max_concurrent_calls, in_flight
            with in_flight_lock:
                in_flight += 1
                max_concurrent_calls = max(max_concurrent_calls, in_flight)
            time.sleep(0.02)  # widen the race window
            with in_flight_lock:
                in_flight -= 1
                call_count += 1
            return [[[[[0, 0], [1, 0], [1, 1], [0, 1]], ("IC-188", 0.9)]]]

    fake_module = types.SimpleNamespace(PaddleOCR=_FakePaddleOCR)
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    stats = types.SimpleNamespace(
        build_count=lambda: build_count,
        call_count=lambda: call_count,
        max_concurrent_calls=lambda: max_concurrent_calls,
    )
    return stats


def test_paddle_engine_lazily_constructs_exactly_once_under_concurrency(fake_paddleocr_module) -> None:
    engine = PaddleOcrEngine()

    threads = [threading.Thread(target=engine._ensure_loaded) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert fake_paddleocr_module.build_count() == 1


def test_paddle_engine_serializes_concurrent_inference_calls(fake_paddleocr_module) -> None:
    """PaddleOCR's predictor is not documented as safe for concurrent
    inference from multiple threads on one shared instance — inference
    calls must be serialized, not run in parallel against the same
    `self._reader`."""
    import numpy as np

    engine = PaddleOcrEngine()
    image = np.zeros((10, 10, 3), dtype=np.uint8)

    threads = [threading.Thread(target=engine.read_text, args=(image,)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert fake_paddleocr_module.call_count() == 8
    assert fake_paddleocr_module.max_concurrent_calls() == 1, "concurrent inference calls were not serialized"


def test_paddle_engine_treats_none_line_as_no_text_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Some PaddleOCR versions return `[[None]]` (not `[[]]`) for "no text
    detected" on a frame. Unpacking `_box, (text, conf) = None` used to
    raise a raw TypeError that escaped as an unhandled exception instead
    of being treated as an ordinary no-match result."""
    import numpy as np

    class _NoDetectionPaddleOCR:
        def __init__(self, *_a, **_kw) -> None:
            pass

        def ocr(self, _image, cls=False):  # noqa: ANN001, FBT002
            return [[None]]

    fake_module = types.SimpleNamespace(PaddleOCR=_NoDetectionPaddleOCR)
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    engine = PaddleOcrEngine()
    result = engine.read_text(np.zeros((10, 10, 3), dtype=np.uint8))

    assert result.text == ""
    assert result.confidence == 0.0
