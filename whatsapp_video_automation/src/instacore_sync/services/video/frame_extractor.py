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
            duration_seconds = (frame_count / fps) if fps > 0 else max_seconds

            end_seconds = duration_seconds if full_video else min(max_seconds, duration_seconds)
            if end_seconds <= 0:
                end_seconds = max_seconds

            t = 0.0
            while t <= end_seconds:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if ok and frame is not None:
                    yield Frame(timestamp_seconds=t, image_bgr=frame)
                else:
                    logger.debug("frame_extractor.seek_miss", video=str(video_path), t=t)
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
