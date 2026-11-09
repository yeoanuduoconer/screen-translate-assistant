from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from time import perf_counter

import numpy as np
from PIL import Image, ImageGrab

from .models import Rect


def system_display_scale() -> float:
    if os.name != "nt":
        return 1.0
    dpi = int(ctypes.windll.user32.GetDpiForSystem())
    return max(1.0, dpi / 96.0)


class ScreenCapturer:
    def grab(self, region: Rect) -> Image.Image:
        if not region.valid:
            raise ValueError("Capture region is too small.")
        scale = system_display_scale()
        physical_bbox = (
            round(region.x * scale),
            round(region.y * scale),
            round(region.right * scale),
            round(region.bottom * scale),
        )
        return ImageGrab.grab(bbox=physical_bbox, all_screens=True).convert("RGB")


def frame_signature(image: Image.Image) -> np.ndarray:
    return np.asarray(image.resize((192, 108)).convert("L"), dtype=np.float32) / 255.0


def frame_difference(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.mean(np.abs(left - right)))


def frame_changed(left: np.ndarray, right: np.ndarray, threshold: float) -> bool:
    delta = np.abs(left - right)
    # One changed line can be almost invisible when averaged over a whole page.
    tiles = delta.reshape(18, 6, 24, 8).mean(axis=(1, 3))
    return bool(delta.mean() > threshold or tiles.max() > threshold * 1.6)


@dataclass(slots=True)
class StableChangeGate:
    threshold: float = 0.025
    stable_frames: int = 2
    quiet_seconds: float = 0.0
    _candidate: np.ndarray | None = None
    _processed: np.ndarray | None = None
    _stable_count: int = 0
    candidate_since: float = 0.0
    ready_since: float | None = None

    def reset(self) -> None:
        self._candidate = None
        self._processed = None
        self._stable_count = 0
        self.candidate_since = 0.0
        self.ready_since = None

    def observe(self, image: Image.Image) -> bool:
        return self.observe_signature(frame_signature(image))

    def observe_signature(
        self, current: np.ndarray, observed_at: float | None = None, *, can_submit: bool = True
    ) -> bool:
        observed_at = perf_counter() if observed_at is None else observed_at
        if self._candidate is None or frame_changed(current, self._candidate, self.threshold):
            self._candidate = current
            self._stable_count = 1
            self.candidate_since = observed_at
            self.ready_since = None
        else:
            self._stable_count += 1
        if (
            self._stable_count < self.stable_frames
            or observed_at - self.candidate_since < self.quiet_seconds
        ):
            return False
        if self.ready_since is None:
            self.ready_since = observed_at
        if not can_submit:
            return False
        if self._processed is None or frame_changed(current, self._processed, self.threshold):
            self._processed = current
            return True
        return False
