from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np
from PIL import Image

from .models import Rect, RgbColor, TextRegion


def _as_color(values: np.ndarray) -> RgbColor:
    median = np.median(values.reshape(-1, 3), axis=0)
    return tuple(int(round(float(channel))) for channel in median)  # type: ignore[return-value]


def _contrast_color(background: RgbColor) -> RgbColor:
    luminance = 0.2126 * background[0] + 0.7152 * background[1] + 0.0722 * background[2]
    return (18, 18, 18) if luminance >= 150 else (245, 245, 245)


def _tight_glyph_box(
    crop: np.ndarray, background: RgbColor, original: Rect, left: int, top: int
) -> Rect:
    """Shrink a recognition polygon to its visible glyph pixels.

    Paddle deliberately expands text polygons to improve recognition. That
    extra context is inappropriate for a replacement overlay because it looks
    offset and covers adjacent UI. On textured backgrounds, where a reliable
    foreground cannot be isolated, this function keeps the original OCR box.
    """
    background_vector = np.asarray(background, dtype=np.int16)
    distances = np.linalg.norm(crop - background_vector, axis=2)
    non_zero = distances[distances > 4]
    if non_zero.size < 6:
        return original

    threshold = max(18.0, min(64.0, float(np.percentile(non_zero, 35))))
    mask = (distances >= threshold).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    minimum_height = max(2, round(crop.shape[0] * 0.10))
    kept = (stats[:, cv2.CC_STAT_HEIGHT] >= minimum_height) & (
        stats[:, cv2.CC_STAT_AREA] >= 2
    )
    kept[0] = False
    ys, xs = np.nonzero(kept[labels])
    coverage = len(xs) / max(1, crop.shape[0] * crop.shape[1])
    if len(xs) < 6 or coverage > 0.48:
        return original

    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    tight_width = x2 - x1
    tight_height = y2 - y1
    if tight_width < original.width * 0.30 or tight_height < original.height * 0.30:
        return original

    padding = max(1, round(original.height * 0.025))
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(crop.shape[1], x2 + padding)
    y2 = min(crop.shape[0], y2 + padding)
    return Rect(left + x1, top + y1, x2 - x1, y2 - y1)


def sample_region_style(image: Image.Image, region: TextRegion) -> TextRegion:
    return _sample_region_style(np.asarray(image.convert("RGB"), dtype=np.int16), region)


def _sample_region_style(pixels: np.ndarray, region: TextRegion) -> TextRegion:
    height, width = pixels.shape[:2]
    box = region.box
    left = max(0, min(width - 1, box.x))
    top = max(0, min(height - 1, box.y))
    right = max(left + 1, min(width, box.right))
    bottom = max(top + 1, min(height, box.bottom))
    box = Rect(left, top, right - left, bottom - top)

    margin = max(2, min(6, box.height // 5))
    outer_left = max(0, left - margin)
    outer_top = max(0, top - margin)
    outer_right = min(width, right + margin)
    outer_bottom = min(height, bottom + margin)
    outer = pixels[outer_top:outer_bottom, outer_left:outer_right]
    ring_mask = np.ones(outer.shape[:2], dtype=bool)
    ring_mask[
        top - outer_top : bottom - outer_top,
        left - outer_left : right - outer_left,
    ] = False
    ring = outer[ring_mask]

    crop = pixels[top:bottom, left:right]
    if ring.size >= 12:
        background = _as_color(ring)
    else:
        corner = max(1, min(crop.shape[0], crop.shape[1]) // 5)
        samples = np.concatenate(
            (
                crop[:corner, :corner].reshape(-1, 3),
                crop[:corner, -corner:].reshape(-1, 3),
                crop[-corner:, :corner].reshape(-1, 3),
                crop[-corner:, -corner:].reshape(-1, 3),
            )
        )
        background = _as_color(samples)

    tight_box = _tight_glyph_box(crop, background, box, left, top)
    tight_crop = pixels[tight_box.y : tight_box.bottom, tight_box.x : tight_box.right]
    flat = tight_crop.reshape(-1, 3)
    background_vector = np.asarray(background, dtype=np.int16)
    distances = np.linalg.norm(flat - background_vector, axis=1)
    if flat.shape[0] >= 8:
        cutoff = np.percentile(distances, 82)
        foreground_samples = flat[distances >= cutoff]
    else:
        foreground_samples = flat
    text_color = _as_color(foreground_samples)
    if np.linalg.norm(np.asarray(text_color) - background_vector) < 70:
        text_color = _contrast_color(background)

    # The overlay font fitter still reduces this when a translation is longer.
    # Starting at 90% keeps short translations visually close to the source size.
    font_px = max(8, int(round(tight_box.height * 0.90)))
    tightened = replace(region, box=tight_box)
    return tightened.with_style(background, text_color, font_px)


def apply_region_styles(image: Image.Image, regions: list[TextRegion]) -> list[TextRegion]:
    pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
    return [_sample_region_style(pixels, region) for region in regions]
