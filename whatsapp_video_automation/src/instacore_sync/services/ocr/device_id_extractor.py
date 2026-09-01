"""Orchestrates frame sampling + preprocessing + multi-engine OCR to find a
Device ID (e.g. "IC-188") near the start of a video.

Strategy (mirrors the product spec):
  1. Sample frames every `frame_interval_seconds` for the first
     `max_seconds_scanned` seconds only — never the whole video by default.
  2. Skip frames that are near-blank/near-uniform (loading screens, mid-
     transition frames) before spending an OCR call on them — this is the
     "dynamic frame selection" piece: which frames actually get OCR'd
     depends on their content, not just their timestamp.
  3. For each remaining frame, try preprocessing *variants* in increasing
     order of cost — default adaptive-threshold crop first, then an Otsu-
     threshold variant, then a 180-degree rotation-corrected variant — and
     every configured OCR engine on each. This is the "retry before giving
     up" behavior: a video that fails the cheap default variant on every
     frame gets a real second (and third) attempt with different image
     processing before anything is escalated.
  4. Regex-match `device_id_pattern` against each engine's text; among all
     matches found, keep the one with the highest OCR confidence. Stop
     early the moment a match clears `min_confidence`.
  5. If nothing confident was found and `full_scan_on_low_confidence` is
     set, fall back to scanning the entire video once (bounded to
     `OCR_FULL_SCAN_MAX_FRAMES` frames), as a last resort before the caller
     routes the video to Needs Review.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import numpy as np

from instacore_sync.core.config import OcrSettings
from instacore_sync.core.constants import OCR_FULL_SCAN_MAX_FRAMES
from instacore_sync.core.exceptions import OcrEngineError
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.domain.models import DeviceIdExtraction
from instacore_sync.services.ocr.engine_factory import OcrEngineFactory
from instacore_sync.services.ocr.image_preprocessing import (
    is_frame_likely_blank,
    preprocess_frame,
    preprocess_frame_otsu,
)
from instacore_sync.services.video.frame_extractor import FrameExtractor

logger = get_logger(__name__)

# (label, preprocessing function) pairs, tried in this order for every
# non-blank frame. Ordered cheapest/most-likely-to-work first so the common
# case (an upright, evenly-lit recording) never pays for the later variants.
_PREPROCESS_VARIANTS: list[tuple[str, Callable[[np.ndarray], np.ndarray]]] = [
    ("default", preprocess_frame),
    ("otsu", preprocess_frame_otsu),
    ("rotated_180", lambda img: preprocess_frame(img, rotation_degrees=180)),
]


def _lenient_extraction_pattern(pattern: str) -> str:
    """Best-effort: make the literal "IC-" in the well-known default
    pattern shape tolerate a missing hyphen when searching raw OCR text
    (see `DeviceIdExtractor.__init__` for why). A custom pattern that
    doesn't contain "IC-" is returned unchanged — degrading gracefully to
    today's behavior rather than guessing where else to loosen it."""
    return pattern.replace("IC-", "IC-?", 1) if "IC-" in pattern else pattern


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
        # Searches raw OCR text with a LENIENT version of the configured
        # pattern (hyphen optional): the banner's thin "-" glyph can be
        # erased by denoising/thresholding on a small cropped region,
        # producing legible text like "IC188" with no separator at all —
        # the strict pattern would never match that and would send an
        # otherwise-readable video to Needs Review for nothing.
        # `_normalize()` restores the canonical "IC-188" form afterward.
        # This is purely an extraction-time concern: `is_valid_device_id`
        # (Needs Review manual entry, Drive folder naming) still validates
        # against the original strict `settings.device_id_pattern`
        # unchanged, so what counts as a valid *stored* Device ID never
        # loosens — only what OCR is willing to consider a candidate match.
        self._pattern = re.compile(_lenient_extraction_pattern(settings.device_id_pattern), re.IGNORECASE)

    def extract(self, video_path: Path) -> DeviceIdExtraction:
        result = self._scan(video_path, full_video=False)
        if result.succeeded or not self._settings.full_scan_on_low_confidence:
            return result

        logger.info(
            "ocr.device_id.full_scan_fallback",
            video=str(video_path),
            best_confidence=result.confidence,
        )
        full_result = self._scan(video_path, full_video=True, max_frames=OCR_FULL_SCAN_MAX_FRAMES)
        return full_result if full_result.succeeded else result

    def _scan(
        self, video_path: Path, *, full_video: bool, max_frames: int | None = None
    ) -> DeviceIdExtraction:
        best: DeviceIdExtraction | None = None
        frames_considered = 0
        frames_examined = 0
        frames_skipped_blank = 0

        for frame in self._frames.iter_frames(
            video_path,
            interval_seconds=self._settings.frame_interval_seconds,
            max_seconds=self._settings.max_seconds_scanned,
            full_video=full_video,
        ):
            # Counts every frame pulled from the video toward the cap —
            # including ones about to be skipped as blank — not just the
            # ones actually OCR'd. A long blank/loading-screen stretch
            # previously let `frames_examined` (which only counted
            # non-blank frames) never reach `max_frames`, so the intended
            # "last resort" scan's cost bound didn't actually bound
            # anything: a long video with a long blank lead-in could churn
            # through far more than `max_frames` iterations.
            if max_frames is not None and frames_considered >= max_frames:
                logger.warning(
                    "ocr.device_id.full_scan_cap_reached",
                    video=str(video_path),
                    max_frames=max_frames,
                )
                break
            frames_considered += 1

            if is_frame_likely_blank(frame.image_bgr):
                frames_skipped_blank += 1
                continue

            frames_examined += 1

            candidate = self._try_variants_on_frame(frame.image_bgr, frame.timestamp_seconds, full_video)
            if candidate is None:
                continue

            if best is None or candidate.confidence > best.confidence:
                best = DeviceIdExtraction(
                    device_id=candidate.device_id,
                    confidence=candidate.confidence,
                    engine_used=candidate.engine_used,
                    frame_timestamp_seconds=candidate.frame_timestamp_seconds,
                    frames_examined=frames_examined,
                    raw_text=candidate.raw_text,
                    full_scan_performed=full_video,
                )

            if candidate.confidence >= self._settings.min_confidence:
                logger.info(
                    "ocr.device_id.found",
                    video=str(video_path),
                    device_id=candidate.device_id,
                    confidence=candidate.confidence,
                    engine=candidate.engine_used,
                    frame_t=frame.timestamp_seconds,
                    frames_skipped_blank=frames_skipped_blank,
                )
                return best

        if best is not None:
            return best

        return DeviceIdExtraction(
            device_id=None,
            confidence=0.0,
            frames_examined=frames_examined,
            full_scan_performed=full_video,
        )

    def _try_variants_on_frame(
        self, image_bgr: np.ndarray, timestamp_seconds: float, full_video: bool
    ) -> DeviceIdExtraction | None:
        """Try every preprocessing variant x engine combo on one frame, in
        cost order, stopping at the first confident match. Returns the
        single best candidate found on this frame (confident or not), or
        None if nothing in the text matched the Device ID pattern at all.
        """
        best_for_frame: DeviceIdExtraction | None = None

        for variant_label, preprocess in _PREPROCESS_VARIANTS:
            try:
                processed = preprocess(image_bgr)
            except Exception:  # noqa: BLE001 - a broken variant must not sink the whole frame
                logger.warning("ocr.preprocess_variant_failed", variant=variant_label)
                continue

            for engine in self._engines.engines_for():
                try:
                    read = engine.read_text(processed)
                except OcrEngineError as exc:
                    logger.warning("ocr.engine.read_failed", engine=engine.name, error=str(exc))
                    continue

                match = self._pattern.search(read.text)
                if not match:
                    continue

                device_id = self._normalize(match.group(0))
                candidate = DeviceIdExtraction(
                    device_id=device_id,
                    confidence=read.confidence,
                    engine_used=engine.name,
                    frame_timestamp_seconds=timestamp_seconds,
                    frames_examined=1,
                    raw_text=read.text,
                    full_scan_performed=full_video,
                )

                if best_for_frame is None or candidate.confidence > best_for_frame.confidence:
                    best_for_frame = candidate

                if candidate.confidence >= self._settings.min_confidence:
                    return candidate

            # Only escalate to the next (more expensive) variant if this one
            # produced nothing at all worth keeping — if it found a
            # low-confidence match, further variants are unlikely to help
            # and we've already recorded it as a fallback candidate.
            if best_for_frame is not None:
                break

        return best_for_frame

    @staticmethod
    def _normalize(raw: str) -> str:
        raw = raw.upper().replace(" ", "").replace("_", "-")
        if "-" not in raw:
            digits_start = next((i for i, c in enumerate(raw) if c.isdigit()), len(raw))
            raw = f"{raw[:digits_start]}-{raw[digits_start:]}"
        return raw
