import cv2
import numpy as np
from PIL import Image

from screen_translator.tracking import FrameMotionTracker


def test_tracks_page_translation_between_frames() -> None:
    first = np.zeros((300, 500), dtype=np.uint8)
    cv2.rectangle(first, (80, 60), (190, 130), 255, -1)
    cv2.putText(first, "PAGE", (230, 210), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 255, 3)
    transform = np.float32([[1, 0, 36], [0, 1, -22]])
    second = cv2.warpAffine(first, transform, (500, 300))

    tracker = FrameMotionTracker(analysis_width=500)
    assert tracker.observe(Image.fromarray(first)).dx == 0
    motion = tracker.observe(Image.fromarray(second))
    assert motion.confidence > 0.5
    assert abs(motion.dx - 36) < 1
    assert abs(motion.dy + 22) < 1
