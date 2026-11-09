from __future__ import annotations

from dataclasses import replace

from .models import Rect, TextRegion


def map_regions_to_logical_screen(
    regions: list[TextRegion], selection: Rect, captured_size: tuple[int, int]
) -> list[TextRegion]:
    scale_x = captured_size[0] / selection.width
    scale_y = captured_size[1] / selection.height
    if scale_x <= 0 or scale_y <= 0:
        raise ValueError("Invalid capture-to-selection scale.")
    mapped: list[TextRegion] = []
    for region in regions:
        box = region.box
        left, top = round(box.x / scale_x), round(box.y / scale_y)
        logical_box = Rect(
            selection.x + left,
            selection.y + top,
            max(1, round(box.right / scale_x) - left),
            max(1, round(box.bottom / scale_y) - top),
        )
        mapped.append(
            replace(
                region,
                box=logical_box,
                font_px=max(7, round(region.font_px / scale_y)),
            )
        )
    return mapped


def _intersection(left: Rect, right: Rect) -> Rect | None:
    x1 = max(left.x, right.x)
    y1 = max(left.y, right.y)
    x2 = min(left.right, right.right)
    y2 = min(left.bottom, right.bottom)
    if x2 <= x1 or y2 <= y1:
        return None
    return Rect(x1, y1, x2 - x1, y2 - y1)


def shift_regions_within(
    regions: tuple[TextRegion, ...], dx: float, dy: float, bounds: Rect
) -> tuple[TextRegion, ...]:
    shifted: list[TextRegion] = []
    move_x = round(dx)
    move_y = round(dy)
    for region in regions:
        moved = replace(
            region,
            box=Rect(
                region.box.x + move_x,
                region.box.y + move_y,
                region.box.width,
                region.box.height,
            ),
        )
        visible_box = _intersection(moved.box, bounds)
        if visible_box is not None:
            shifted.append(replace(moved, box=visible_box))
    return tuple(shifted)
