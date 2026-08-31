"""Frame -> OCR-ready crop.

Instacore always renders the Device ID banner near the top of the phone's
screen, and the phone occupies the center of the recorded frame (the
recording app adds letterboxing/UI chrome around it). We crop to that
region before running OCR both to raise accuracy (less noise for the
engine to reject) and to cut OCR latency (a small crop is much faster than
a full 1080p frame).
"""

from __future__ import annotations

import cv2
import numpy as np


def crop_top_banner(image_bgr: np.ndarray, *, height_fraction: float = 0.22) -> np.ndarray:
    """Crop the top portion of the frame where the Device ID banner lives.

    Also trims 8% off each side to drop status-bar icons/notches that
    sometimes confuse OCR at the very edges.
    """
    h, w = image_bgr.shape[:2]
    crop_h = max(1, int(h * height_fraction))
    side_margin = max(0, int(w * 0.08))
    return image_bgr[0:crop_h, side_margin : w - side_margin]


def enhance_for_ocr(image_bgr: np.ndarray) -> np.ndarray:
    """Grayscale -> denoise -> contrast boost -> binarize, tuned for on-screen text."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(denoised)

    # Upscale small crops — Tesseract/PaddleOCR are both markedly more
    # accurate on text that is at least ~30px tall.
    h, w = contrasted.shape[:2]
    if h < 120:
        scale = 120 / max(h, 1)
        contrasted = cv2.resize(
            contrasted, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC
        )

    binarized = cv2.adaptiveThreshold(
        contrasted,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=15,
    )
    return binarized


def preprocess_frame(image_bgr: np.ndarray) -> np.ndarray:
    """Full pipeline: crop the banner region, then enhance it for OCR."""
    cropped = crop_top_banner(image_bgr)
    return enhance_for_ocr(cropped)
