from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass, replace

RgbColor = tuple[int, int, int]


def _logical_display_scale() -> float:
    if os.name != "nt":
        return 1.0
    dpi = int(ctypes.windll.user32.GetDpiForSystem())
    return max(1.0, dpi / 96.0)


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def valid(self) -> bool:
        return self.width >= 8 and self.height >= 8

    def as_bbox(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.right, self.bottom

    def offset(self, dx: int, dy: int) -> Rect:
        return replace(self, x=self.x + dx, y=self.y + dy)


@dataclass(frozen=True, slots=True)
class TextRegion:
    box: Rect
    source_text: str
    confidence: float
    translated_text: str = ""
    background_color: RgbColor = (255, 255, 255)
    text_color: RgbColor = (0, 0, 0)
    font_px: int = 0

    def with_translation(self, value: str) -> TextRegion:
        return replace(self, translated_text=value)

    def with_style(
        self, background_color: RgbColor, text_color: RgbColor, font_px: int
    ) -> TextRegion:
        return replace(
            self,
            background_color=background_color,
            text_color=text_color,
            font_px=font_px,
        )

    def offset(self, dx: int, dy: int) -> TextRegion:
        # OCR boxes are measured in physical screenshot pixels while Qt's
        # overlay is positioned in logical pixels. Windows 150% scaling, for
        # example, requires dividing every local coordinate and font size by 1.5.
        scale = _logical_display_scale()
        logical_box = Rect(
            dx + round(self.box.x / scale),
            dy + round(self.box.y / scale),
            max(1, round(self.box.width / scale)),
            max(1, round(self.box.height / scale)),
        )
        return replace(
            self,
            box=logical_box,
            font_px=max(7, round(self.font_px / scale)),
        )


@dataclass(frozen=True, slots=True)
class PipelineResult:
    regions: tuple[TextRegion, ...]
    error: str = ""
