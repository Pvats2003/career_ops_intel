"""Cheap, bounded frame sampling from the start of a video.

We deliberately never decode a whole 150 MB video just to read a Device ID
that appears in the first few seconds: `iter_frames` seeks with OpenCV's
`CAP_PROP_POS_MSEC` and only decodes the sampled timestamps, which keeps
per-video CPU cost roughly constant regardless of video length.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from instacore_sync.core.exceptions import VideoReadError
from instacore_sync.core.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Frame:
    timestamp_seconds: float
    image_bgr: np.ndarray


# When `full_video=True` and the container's fps/frame-count metadata can't
# be trusted (0 or missing — common for remuxed/streamed files, some
# Android screen-recorder outputs, VFR video), we can't compute a real
# duration to scan to. Falling back to `max_seconds` would silently
# collapse the fallback scan to the exact same narrow window the initial
# scan already failed on, defeating its purpose as a "last resort" pass.
# Instead we keep seeking forward until reads actually stop succeeding,
# bounded by this generous-but-finite safety cap so a genuinely corrupt
# file can't make the fallback scan run indefinitely.
_FULL_SCAN_SAFETY_CAP_SECONDS = 300.0
# How many consecutive failed reads in a row count as "reached the real
# end of the stream" rather than one transient seek miss.
_CONSECUTIVE_MISS_STOP = 3


class FrameExtractor:
    """Samples frames from a video at a fixed interval, bounded by a time window."""

    def iter_frames(
        self,
        video_path: Path,
        *,
        interval_seconds: float = 0.5,
        max_seconds: float = 6.0,
        full_video: bool = False,
    ) -> Iterator[Frame]:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise VideoReadError(f"Could not open video for reading: {video_path}")

        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            metadata_reliable = fps > 0 and frame_count > 0
            duration_seconds = (frame_count / fps) if metadata_reliable else 0.0

            if full_video:
                end_seconds = duration_seconds if metadata_reliable else _FULL_SCAN_SAFETY_CAP_SECONDS
            else:
                end_seconds = min(max_seconds, duration_seconds) if metadata_reliable else max_seconds
            if end_seconds <= 0:
                end_seconds = max_seconds

            # Only trust "N misses in a row = end of stream" for the
            # unreliable-metadata full-scan case — an ordinary bounded scan
            # (or a full scan with a trustworthy duration) has no need to
            # stop early on a miss; it's already bounded by `end_seconds`.
            stop_on_consecutive_misses = full_video and not metadata_reliable
            consecutive_misses = 0

            t = 0.0
            while t <= end_seconds:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if ok and frame is not None:
                    consecutive_misses = 0
                    yield Frame(timestamp_seconds=t, image_bgr=frame)
                else:
                    logger.debug("frame_extractor.seek_miss", video=str(video_path), t=t)
                    consecutive_misses += 1
                    if stop_on_consecutive_misses and consecutive_misses >= _CONSECUTIVE_MISS_STOP:
                        break  # genuinely reached the end of the stream
                t += interval_seconds
        finally:
            cap.release()

    def probe_duration_seconds(self, video_path: Path) -> float:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise VideoReadError(f"Could not open video for probing: {video_path}")
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            return (frame_count / fps) if fps > 0 else 0.0
        finally:
            cap.release()
