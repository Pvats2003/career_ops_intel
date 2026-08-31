"""Orchestrates frame sampling + preprocessing + multi-engine OCR to find a
Device ID (e.g. "IC-188") near the start of a video.

Strategy (mirrors the product spec):
  1. Sample frames every `frame_interval_seconds` for the first
     `max_seconds_scanned` seconds only — never the whole video by default.
  2. Crop + enhance each frame, run every configured OCR engine on it.
  3. Regex-match `device_id_pattern` against each engine's text; among all
     matches found across all frames/engines, keep the one with the highest
     OCR confidence.
  4. Stop early once a match clears `min_confidence` — no need to keep
     burning CPU once we're confident.
  5. If nothing confident was found and `full_scan_on_low_confidence` is
     set, fall back to scanning the entire video once, as a last resort.
"""

from __future__ import annotations

import re
from pathlib import Path

from instacore_sync.core.config import OcrSettings
from instacore_sync.core.exceptions import OcrEngineError
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.domain.models import DeviceIdExtraction
from instacore_sync.services.ocr.engine_factory import OcrEngineFactory
from instacore_sync.services.ocr.image_preprocessing import preprocess_frame
from instacore_sync.services.video.frame_extractor import FrameExtractor

logger = get_logger(__name__)


class DeviceIdExtractor:
    def __init__(
        self,
        settings: OcrSettings,
        frame_extractor: FrameExtractor | None = None,
        engine_factory: OcrEngineFactory | None = None,
    ) -> None:
        self._settings = settings
        self._frames = frame_extractor or FrameExtractor()
        self._engines = engine_factory or OcrEngineFactory(settings)
        self._pattern = re.compile(settings.device_id_pattern, re.IGNORECASE)

    def extract(self, video_path: Path) -> DeviceIdExtraction:
        result = self._scan(video_path, full_video=False)
        if result.succeeded or not self._settings.full_scan_on_low_confidence:
            return result

        logger.info(
            "ocr.device_id.full_scan_fallback",
            video=str(video_path),
            best_confidence=result.confidence,
        )
        full_result = self._scan(video_path, full_video=True)
        return full_result if full_result.succeeded else result

    def _scan(self, video_path: Path, *, full_video: bool) -> DeviceIdExtraction:
        best: DeviceIdExtraction | None = None
        frames_examined = 0

        for frame in self._frames.iter_frames(
            video_path,
            interval_seconds=self._settings.frame_interval_seconds,
            max_seconds=self._settings.max_seconds_scanned,
            full_video=full_video,
        ):
            processed = preprocess_frame(frame.image_bgr)
            frames_examined += 1

            for engine in self._engines.engines_for():
                try:
                    read = engine.read_text(processed)
                except OcrEngineError as exc:
                    logger.warning(
                        "ocr.engine.read_failed", engine=engine.name, error=str(exc)
                    )
                    continue

                match = self._pattern.search(read.text)
                if not match:
                    continue

                device_id = self._normalize(match.group(0))
                candidate = DeviceIdExtraction(
                    device_id=device_id,
                    confidence=read.confidence,
                    engine_used=engine.name,
                    frame_timestamp_seconds=frame.timestamp_seconds,
                    frames_examined=frames_examined,
                    raw_text=read.text,
                    full_scan_performed=full_video,
                )

                if best is None or candidate.confidence > best.confidence:
                    best = candidate

                if candidate.confidence >= self._settings.min_confidence:
                    logger.info(
                        "ocr.device_id.found",
                        video=str(video_path),
                        device_id=device_id,
                        confidence=candidate.confidence,
                        engine=engine.name,
                        frame_t=frame.timestamp_seconds,
                    )
                    return candidate

        if best is not None:
            return best

        return DeviceIdExtraction(
            device_id=None,
            confidence=0.0,
            frames_examined=frames_examined,
            full_scan_performed=full_video,
        )

    @staticmethod
    def _normalize(raw: str) -> str:
        raw = raw.upper().replace(" ", "").replace("_", "-")
        if "-" not in raw:
            digits_start = next((i for i, c in enumerate(raw) if c.isdigit()), len(raw))
            raw = f"{raw[:digits_start]}-{raw[digits_start:]}"
        return raw
