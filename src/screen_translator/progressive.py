from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .models import Rect, TextRegion


@dataclass(frozen=True, slots=True)
class ImageBand:
    image: Image.Image
    origin: Rect
    core_top: int
    core_bottom: int
    index: int
    total: int


def split_horizontal_bands(
    image: Image.Image,
    selection: Rect,
    preferred_count: int = 1,
    overlap_px: int = 36,
) -> list[ImageBand]:
    """Split a screenshot while preserving global coordinates.

    A single full-page band is the runtime default. It avoids repeating OCR
    setup and reduces one page refresh to one batched translation request.
    Explicit counts remain available for diagnostics and visual experiments.
    """
    count = preferred_count if image.height >= 600 and image.width >= 500 else 1
    count = max(1, min(count, image.height // 160 or 1))
    scale_y = image.height / selection.height
    physical_step = image.height / count
    bands: list[ImageBand] = []
    for index in range(count):
        core_top_px = round(index * physical_step)
        core_bottom_px = image.height if index == count - 1 else round((index + 1) * physical_step)
        crop_top = max(0, core_top_px - (overlap_px if index else 0))
        crop_bottom = min(
            image.height,
            core_bottom_px + (overlap_px if index < count - 1 else 0),
        )
        logical_crop_top = selection.y + round(crop_top / scale_y)
        logical_crop_height = max(1, round((crop_bottom - crop_top) / scale_y))
        core_top = selection.y + round(core_top_px / scale_y)
        core_bottom = selection.y + round(core_bottom_px / scale_y)
        bands.append(
            ImageBand(
                image.crop((0, crop_top, image.width, crop_bottom)),
                Rect(selection.x, logical_crop_top, selection.width, logical_crop_height),
                core_top,
                core_bottom,
                index,
                count,
            )
        )
    return bands


def regions_in_band_core(
    regions: tuple[TextRegion, ...], band: ImageBand
) -> tuple[TextRegion, ...]:
    """Assign overlapping detections to exactly one band by their center line."""
    accepted: list[TextRegion] = []
    for region in regions:
        center_y = region.box.y + region.box.height / 2
        is_last = band.index == band.total - 1
        if center_y >= band.core_top and (center_y < band.core_bottom or is_last):
            accepted.append(region)
    return tuple(accepted)
