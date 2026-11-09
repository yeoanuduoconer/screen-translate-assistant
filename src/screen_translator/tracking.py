from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True, slots=True)
class FrameMotion:
    dx: float = 0.0
    dy: float = 0.0
    confidence: float = 0.0


class FrameMotionTracker:
    def __init__(self, analysis_width: int = 480, minimum_confidence: float = 0.16) -> None:
        self.analysis_width = analysis_width
        self.minimum_confidence = minimum_confidence
        self._previous: np.ndarray | None = None
        self._window: np.ndarray | None = None
        self._scale_x = 1.0
        self._scale_y = 1.0

    def reset(self) -> None:
        self._previous = None
        self._window = None

    def _prepare(self, image: Image.Image) -> np.ndarray:
        gray = np.asarray(image if image.mode == "L" else image.convert("L"), dtype=np.uint8)
        width = min(self.analysis_width, image.width)
        height = max(32, round(image.height * width / image.width))
        resized = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA).astype(np.float32)
        self._scale_x = image.width / width
        self._scale_y = image.height / height
        if self._window is None or self._window.shape != resized.shape:
            self._window = cv2.createHanningWindow((width, height), cv2.CV_32F)
        return resized

    def observe(self, image: Image.Image) -> FrameMotion:
        current = self._prepare(image)
        if self._previous is None or self._previous.shape != current.shape:
            self._previous = current
            return FrameMotion()
        shift, confidence = cv2.phaseCorrelate(self._previous, current, self._window)
        self._previous = current
        dx = float(shift[0] * self._scale_x)
        dy = float(shift[1] * self._scale_y)
        if confidence < self.minimum_confidence:
            return FrameMotion(confidence=float(confidence))
        if abs(dx) > image.width * 0.45 or abs(dy) > image.height * 0.45:
            return FrameMotion(confidence=float(confidence))
        if abs(dx) < 0.75:
            dx = 0.0
        if abs(dy) < 0.75:
            dy = 0.0
        return FrameMotion(dx, dy, float(confidence))
