from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter

import cv2
import numpy as np
from PIL import Image

from .models import Rect, TextRegion
from .tracking import FrameMotionTracker


@dataclass(frozen=True, slots=True)
class TrackingResult:
    regions: tuple[TextRegion, ...] | None = None
    confidence: float = 0.0
    lost: bool = False


@dataclass(slots=True)
class _Line:
    region: TextRegion
    pixels: np.ndarray
    source_x: int
    source_y: int
    x: int
    y: int


class RegionTemplateTracker:
    """Reuse verified text patches across scrolls within the selected region."""

    def __init__(self) -> None:
        self._motion = FrameMotionTracker(analysis_width=384)
        self.reset()

    def reset(self) -> None:
        self._motion.reset()
        self._bounds: Rect | None = None
        self._size: tuple[int, int] | None = None
        self._lines: list[_Line] = []
        self._last_gray: np.ndarray | None = None
        self._result = TrackingResult()
        self._scan_cursor = 0
        self._scans_left = 0

    def initialize(self, image: Image.Image, regions: tuple[TextRegion, ...], bounds: Rect) -> None:
        self.reset()
        self.remember(image, regions, bounds)

    def remember(self, image: Image.Image, regions: tuple[TextRegion, ...], bounds: Rect) -> None:
        if not regions or bounds.width <= 0 or bounds.height <= 0:
            return
        if self._bounds != bounds or self._size != image.size:
            self.reset()
            self._bounds, self._size = bounds, image.size
            self._motion.observe(image)

        gray = np.asarray(image.convert("L"), dtype=np.uint8)
        sx, sy = image.width / bounds.width, image.height / bounds.height
        for region in regions:
            if not region.translated_text:
                continue
            box = region.box
            left, top = round((box.x - bounds.x) * sx), round((box.y - bounds.y) * sy)
            right, bottom = round((box.right - bounds.x) * sx), round((box.bottom - bounds.y) * sy)
            if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
                continue
            patch = gray[top:bottom, left:right]
            if patch.size < 16 or patch.std() < 5:
                continue
            self._lines = [
                line
                for line in self._lines
                if not (
                    line.region.source_text == region.source_text
                    and abs(line.x - left) <= 8
                    and abs(line.y - top) <= 8
                )
            ]
            self._lines.append(_Line(region, patch.copy(), left, top, left, top))

        # Keep recently seen lines even when they are outside the viewport.
        self._lines = self._lines[-160:]
        self._scans_left = len(self._lines)

    @staticmethod
    def _matches(gray: np.ndarray, line: _Line, x: int, y: int) -> bool:
        height, width = line.pixels.shape
        left, top = max(0, x), max(0, y)
        right, bottom = min(gray.shape[1], x + width), min(gray.shape[0], y + height)
        if right <= left or bottom <= top:
            return False
        if (right - left) * (bottom - top) < width * height * 0.65:
            return False
        reference = line.pixels[top - y : bottom - y, left - x : right - x]
        # A visible patch consisting only of blank margins is not a match.
        if reference.size != line.pixels.size and reference.std() < 5:
            return False
        actual = gray[top:bottom, left:right]
        if np.array_equal(reference, actual):
            return True
        delta = cv2.absdiff(reference, actual)
        if delta.mean() > 3.0:
            return False
        window = (min(24, delta.shape[1]), min(12, delta.shape[0]))
        if cv2.blur(delta, window).max() <= 16:
            return True
        # Ignore a small disturbance in the blank margin only when the
        # original strokes and their immediate surroundings still match.
        background = np.median(np.concatenate((reference[0], reference[-1])))
        ink = (np.abs(reference.astype(np.float32) - background) >= 22).astype(np.uint8)
        if not 0.02 <= ink.mean() <= 0.5:
            return False
        ink = cv2.dilate(ink, np.ones((3, 3), np.uint8))
        return bool(cv2.blur(delta * ink, window).max() <= 10)

    def _search(
        self, gray: np.ndarray, line: _Line, horizontal_radius: int
    ) -> tuple[int, int] | None:
        probe = line.pixels[:, :192]
        if probe.std() < 5:
            probe = line.pixels
        height, width = probe.shape
        left = max(0, line.x - horizontal_radius)
        right = min(gray.shape[1], line.x + width + horizontal_radius)
        if right - left < width or height > gray.shape[0]:
            return None
        scores = cv2.matchTemplate(gray[:, left:right], probe, cv2.TM_CCOEFF_NORMED)
        for _ in range(4):
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            if score < 0.95:
                break
            if self._matches(gray, line, x + left, y):
                return x + left, y
            scores[max(0, y - 1) : y + 2] = -1
        return None

    def track(self, image: Image.Image) -> TrackingResult:
        if self._bounds is None:
            return TrackingResult()
        if self._size != image.size:
            return TrackingResult((), lost=True)
        luma = image.convert("L")
        gray = np.asarray(luma, dtype=np.uint8)
        unchanged = self._last_gray is not None and np.array_equal(gray, self._last_gray)
        if unchanged and not self._scans_left:
            return self._result
        self._last_gray = gray

        dx = dy = 0
        if not unchanged:
            motion = self._motion.observe(luma)
            dx, dy = round(motion.dx), round(motion.dy)
            self._scans_left = len(self._lines)

        located: list[_Line] = []
        missing: list[_Line] = []
        for line in reversed(self._lines):
            x, y = line.x, line.y
            guesses = [(x, y)]
            if dx or dy:
                shifted = (x + dx, y + dy)
                guesses = [
                    shifted,
                    (shifted[0], shifted[1] - 1),
                    (shifted[0], shifted[1] + 1),
                    (x, y),
                ]
            for new_x, new_y in guesses:
                if self._matches(gray, line, new_x, new_y):
                    line.x, line.y = new_x, new_y
                    located.append(line)
                    break
            else:
                # Keep predicting a line's offscreen location during a
                # scroll. A return to the viewport still requires a match.
                if dx or dy:
                    height, width = line.pixels.shape
                    if (
                        y + dy + height <= 0
                        or y + dy >= image.height
                        or x + dx + width <= 0
                        or x + dx >= image.width
                    ):
                        line.x, line.y = x + dx, y + dy
                        continue
                missing.append(line)

        # Global motion only proposes positions. A per-line search can recover
        # lines that jumped farther or moved differently from fixed toolbars.
        scan_started = perf_counter()
        scans = min(len(missing), self._scans_left, 8)
        offsets: list[tuple[int, int]] = []
        for index in range(scans):
            if index and perf_counter() - scan_started > 0.009:
                break
            line = missing[self._scan_cursor % len(missing)]
            self._scan_cursor += 1
            self._scans_left -= 1
            location = next(
                (
                    (line.x + x, line.y + y)
                    for x, y in offsets
                    if self._matches(gray, line, line.x + x, line.y + y)
                ),
                None,
            )
            if location is None:
                location = self._search(gray, line, 3)
            if location is None and index < 2 and perf_counter() - scan_started < 0.006:
                location = self._search(gray, line, 75)
            if location is not None:
                offset = (location[0] - line.x, location[1] - line.y)
                if offset not in offsets:
                    offsets.append(offset)
                line.x, line.y = location
                located.append(line)
        if not missing:
            self._scans_left = 0

        sx, sy = image.width / self._bounds.width, image.height / self._bounds.height
        visible: list[TextRegion] = []
        positions: dict[str, list[tuple[int, int]]] = {}
        for line in located:
            region = line.region
            box = region.box.offset(
                round((line.x - line.source_x) / sx), round((line.y - line.source_y) / sy)
            )
            occurrences = positions.setdefault(region.source_text, [])
            if any(abs(x - box.x) <= 5 and abs(y - box.y) <= 4 for x, y in occurrences):
                continue
            occurrences.append((box.x, box.y))
            visible.append(replace(region, box=box))
        visible.sort(key=lambda region: (region.box.y, region.box.x))
        self._result = TrackingResult(tuple(visible), 1.0 if visible else 0.0, lost=not visible)
        return self._result
