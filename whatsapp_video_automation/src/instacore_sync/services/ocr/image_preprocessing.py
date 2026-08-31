"""Frame -> OCR-ready crop.

Instacore always renders the Device ID banner near the top of the phone's
screen, and the phone occupies the center of the recorded frame (the
recording app adds letterboxing/UI chrome around it). We crop to that
region before running OCR both to raise accuracy (less noise for the
engine to reject) and to cut OCR latency (a small crop is much faster than
a full 1080p frame).

Beyond the default pipeline (`preprocess_frame`), this module exposes a
small set of alternate preprocessing *variants* — a different threshold
method, and rotation correction — that `DeviceIdExtractor` retries, in
increasing order of cost, before giving up on a frame. Most videos are read
correctly by the first (cheapest) variant; the extra variants only run when
that fails, so well-behaved videos pay no extra cost.
"""

from __future__ import annotations

import cv2
import numpy as np

# Below this per-pixel intensity standard deviation, a frame is almost
# certainly a blank/black loading frame or a mid-transition frame with no
# legible text — skip OCR on it entirely rather than waste an engine call
# that can only ever return empty/garbage text. This is the "dynamic frame
# selection" piece: instead of blindly OCR-ing every sampled timestamp, we
# skip the ones that carry no information, which both speeds up the common
# case and lets a fixed time budget spend more of its calls on frames that
# actually stand a chance of containing the Device ID banner.
_BLANK_FRAME_STD_THRESHOLD = 6.0


def crop_top_banner(image_bgr: np.ndarray, *, height_fraction: float = 0.22) -> np.ndarray:
    """Crop the top portion of the frame where the Device ID banner lives.

    Also trims 8% off each side to drop status-bar icons/notches that
    sometimes confuse OCR at the very edges.
    """
    h, w = image_bgr.shape[:2]
    crop_h = max(1, int(h * height_fraction))
    side_margin = max(0, int(w * 0.08))
    return image_bgr[0:crop_h, side_margin : w - side_margin]


def _enhance_common(image_bgr: np.ndarray) -> np.ndarray:
    """Shared grayscale -> denoise -> CLAHE -> upscale steps used by every variant."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(denoised)

    h, w = contrasted.shape[:2]
    if h < 120:
        scale = 120 / max(h, 1)
        contrasted = cv2.resize(
            contrasted, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC
        )
    return contrasted


def enhance_for_ocr(image_bgr: np.ndarray) -> np.ndarray:
    """Grayscale -> denoise -> contrast boost -> adaptive-threshold binarize.

    Adaptive thresholding copes well with uneven screen brightness/glare,
    which is the common case for a phone screen recording — this is the
    default, cheapest variant, tried first.
    """
    contrasted = _enhance_common(image_bgr)
    return cv2.adaptiveThreshold(
        contrasted,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=15,
    )


def enhance_for_ocr_otsu(image_bgr: np.ndarray) -> np.ndarray:
    """Alternate variant: global Otsu threshold instead of adaptive.

    Otsu picks a single global cutoff from the frame's intensity histogram,
    which sometimes reads a banner cleanly where local adaptive thresholding
    fragments the digits (e.g. a very uniformly lit banner). Retried only
    when the default variant found nothing confident.
    """
    contrasted = _enhance_common(image_bgr)
    _, binarized = cv2.threshold(contrasted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binarized


def rotate_frame(image_bgr: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate a frame by a multiple of 90 degrees (cheap, lossless, exact)."""
    if degrees % 360 == 90:
        return cv2.rotate(image_bgr, cv2.ROTATE_90_CLOCKWISE)
    if degrees % 360 == 180:
        return cv2.rotate(image_bgr, cv2.ROTATE_180)
    if degrees % 360 == 270:
        return cv2.rotate(image_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image_bgr


def is_frame_likely_blank(image_bgr: np.ndarray) -> bool:
    """Cheap pre-filter: True if the frame is near-uniform (blank/black/mid-transition).

    Computed on a downsampled grayscale copy so the check costs a fraction
    of a millisecond — far cheaper than the OCR call it's meant to skip.
    """
    small = cv2.resize(image_bgr, (64, 64), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return bool(gray.std() < _BLANK_FRAME_STD_THRESHOLD)


def preprocess_frame(image_bgr: np.ndarray, *, rotation_degrees: int = 0) -> np.ndarray:
    """Default pipeline: optional rotation -> crop the banner region -> enhance."""
    rotated = rotate_frame(image_bgr, rotation_degrees) if rotation_degrees else image_bgr
    cropped = crop_top_banner(rotated)
    return enhance_for_ocr(cropped)


def preprocess_frame_otsu(image_bgr: np.ndarray, *, rotation_degrees: int = 0) -> np.ndarray:
    """Otsu-threshold pipeline: optional rotation -> crop the banner region -> enhance."""
    rotated = rotate_frame(image_bgr, rotation_degrees) if rotation_degrees else image_bgr
    cropped = crop_top_banner(rotated)
    return enhance_for_ocr_otsu(cropped)
