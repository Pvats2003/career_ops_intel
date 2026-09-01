"""Exercises `FrameExtractor` against a small synthetic video generated with
OpenCV's own VideoWriter, so the test needs no fixture video file checked
into the repo and no external codecs beyond what opencv-python ships."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from instacore_sync.core.exceptions import VideoReadError
from instacore_sync.services.video.frame_extractor import FrameExtractor


def _write_synthetic_video(path: Path, *, fps: float = 10.0, seconds: float = 2.0) -> bool:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (64, 64))
    if not writer.isOpened():
        return False
    frame_count = int(fps * seconds)
    for i in range(frame_count):
        frame = np.full((64, 64, 3), fill_value=i % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path.exists() and path.stat().st_size > 0


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    video_path = tmp_path / "synthetic.mp4"
    if not _write_synthetic_video(video_path):
        pytest.skip("OpenCV build in this environment cannot encode mp4v video")
    return video_path


def test_iter_frames_respects_max_seconds_window(synthetic_video: Path) -> None:
    extractor = FrameExtractor()
    frames = list(
        extractor.iter_frames(synthetic_video, interval_seconds=0.5, max_seconds=1.0, full_video=False)
    )
    assert len(frames) >= 1
    assert all(f.timestamp_seconds <= 1.0 + 1e-6 for f in frames)


def test_iter_frames_full_video_covers_whole_duration(synthetic_video: Path) -> None:
    extractor = FrameExtractor()
    duration = extractor.probe_duration_seconds(synthetic_video)
    assert duration > 0

    frames = list(
        extractor.iter_frames(synthetic_video, interval_seconds=0.5, max_seconds=1.0, full_video=True)
    )
    assert frames[-1].timestamp_seconds >= duration - 0.5


def test_open_missing_file_raises_video_read_error(tmp_path: Path) -> None:
    extractor = FrameExtractor()
    missing = tmp_path / "does_not_exist.mp4"
    with pytest.raises(VideoReadError):
        list(extractor.iter_frames(missing))
