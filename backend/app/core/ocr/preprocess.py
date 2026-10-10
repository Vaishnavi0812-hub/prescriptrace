"""Image clean-up before OCR: decode, upscale, denoise, contrast, deskew, threshold.

Pure functions on numpy arrays (OpenCV). Phone photos of prescriptions are often small, tilted,
unevenly lit and noisy; each step targets one of those problems.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

# OpenCV's stubs return generic arrays; values are uint8 greyscale or BGR in practice.
Image = NDArray[Any]

TARGET_WIDTH = 1800  # Tesseract works best around 30 px x-height; upscale small photos
MAX_SIDE = 4000  # cap work on huge photos
MAX_SKEW = 15.0  # degrees; larger angles are more likely a misreading than a tilt


class ImageError(ValueError):
    """The upload is not a decodable image."""


@dataclass(frozen=True)
class Prepared:
    gray: Image  # deskewed greyscale (for crops shown to the user)
    binary: Image  # thresholded (for OCR)
    skew_degrees: float
    scale: float
    contrast: float  # rough quality signal (std-dev of grey levels)


def decode(data: bytes) -> Image:
    """Decode JPEG/PNG/WebP bytes. Rejects anything OpenCV cannot read as an image."""
    if not data:
        raise ImageError("empty upload")
    array = np.frombuffer(data, dtype=np.uint8)
    try:
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    except cv2.error as exc:  # OpenCV raises on some malformed input instead of returning None
        raise ImageError("not a readable image") from exc
    if image is None or image.size == 0:
        raise ImageError("not a readable image")
    return image


def prepare(image: Image) -> Prepared:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    # Speckle (salt-and-pepper) noise from cheap cameras/photocopies: a 3x3 median removes it.
    # Done before upscaling, which would otherwise grow each speck into a blob.
    gray = cv2.medianBlur(gray, 3)
    gray, scale = _resize(gray)
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    angle = estimate_skew(gray)
    if abs(angle) > 0.3:
        gray = rotate(gray, angle)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=31, C=15
    )
    return Prepared(gray, binary, round(angle, 2), scale, float(gray.std()))


def _resize(gray: Image) -> tuple[Image, float]:
    height, width = gray.shape[:2]
    scale = TARGET_WIDTH / width if width < TARGET_WIDTH else 1.0
    if max(height, width) * scale > MAX_SIDE:
        scale = MAX_SIDE / max(height, width)
    if abs(scale - 1.0) < 0.05:
        return gray, 1.0
    interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
    resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=interp)
    return np.asarray(resized, dtype=np.uint8), scale


def estimate_skew(gray: Image) -> float:
    """Angle (degrees, positive = counter-clockwise) that makes text lines horizontal.

    Text pixels are smeared horizontally into line blobs; the median angle of the long blobs is
    the page tilt. Returns 0 when there is not enough text to judge.
    """
    _, inverted = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, gray.shape[1] // 40), 3))
    blobs = cv2.dilate(inverted, kernel, iterations=1)
    contours, _ = cv2.findContours(blobs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles = []
    for contour in contours:
        (_, _), (w, h), angle = cv2.minAreaRect(contour)
        if w < h:
            w, h = h, w
            angle += 90
        if w < gray.shape[1] * 0.15 or h == 0 or w / h < 4:
            continue  # not a text line
        if angle > 45:
            angle -= 90
        angles.append(angle)
    if len(angles) < 2:
        return 0.0
    median = float(np.median(angles))
    return median if abs(median) <= MAX_SKEW else 0.0


def rotate(gray: Image, angle: float) -> Image:
    height, width = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    rotated = cv2.warpAffine(
        gray, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return np.asarray(rotated, dtype=np.uint8)


def crop_png(gray: Image, box: tuple[int, int, int, int], pad: int = 6, max_h: int = 72) -> bytes:
    """PNG of one text line (shown next to the recognised text so the user can compare)."""
    x, y, w, h = box
    y0, y1 = max(0, y - pad), min(gray.shape[0], y + h + pad)
    x0, x1 = max(0, x - pad), min(gray.shape[1], x + w + pad)
    crop = gray[y0:y1, x0:x1]
    if crop.shape[0] > max_h:
        factor = max_h / crop.shape[0]
        crop = cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".png", crop)
    if not ok:
        raise ImageError("could not encode crop")
    return bytes(buffer)
