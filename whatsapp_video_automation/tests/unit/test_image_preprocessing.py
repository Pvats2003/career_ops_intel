from __future__ import annotations

import numpy as np

from instacore_sync.services.ocr.image_preprocessing import (
    is_frame_likely_blank,
    preprocess_frame,
    preprocess_frame_otsu,
    rotate_frame,
)


def test_is_frame_likely_blank_detects_uniform_frame() -> None:
    blank = np.zeros((80, 80, 3), dtype=np.uint8)
    assert is_frame_likely_blank(blank) is True


def test_is_frame_likely_blank_false_for_textured_frame() -> None:
    rng = np.random.default_rng(0)
    noisy = rng.integers(0, 255, size=(80, 80, 3), dtype=np.uint8)
    assert is_frame_likely_blank(noisy) is False


def test_rotate_frame_180_is_involution() -> None:
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 255, size=(50, 80, 3), dtype=np.uint8)
    rotated_twice = rotate_frame(rotate_frame(frame, 180), 180)
    assert np.array_equal(frame, rotated_twice)


def test_rotate_frame_90_swaps_dimensions() -> None:
    frame = np.zeros((50, 80, 3), dtype=np.uint8)
    rotated = rotate_frame(frame, 90)
    assert rotated.shape[:2] == (80, 50)


def test_rotate_frame_zero_degrees_is_noop() -> None:
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    assert rotate_frame(frame, 0) is frame


def test_preprocess_frame_and_otsu_variant_both_produce_binary_image() -> None:
    rng = np.random.default_rng(2)
    frame = rng.integers(0, 255, size=(200, 400, 3), dtype=np.uint8)

    default_out = preprocess_frame(frame)
    otsu_out = preprocess_frame_otsu(frame)

    for out in (default_out, otsu_out):
        assert out.ndim == 2  # grayscale/binary
        assert set(np.unique(out).tolist()) <= {0, 255}


def test_preprocess_frame_with_rotation_changes_output_shape() -> None:
    frame = np.full((100, 300, 3), 128, dtype=np.uint8)
    upright = preprocess_frame(frame, rotation_degrees=0)
    rotated = preprocess_frame(frame, rotation_degrees=90)
    # After a 90-degree rotation the (now much taller, narrower) crop region
    # differs from the upright crop, so the outputs should not match shape.
    assert upright.shape != rotated.shape
