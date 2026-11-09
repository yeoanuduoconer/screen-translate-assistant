import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_translator.models import Rect, TextRegion  # noqa: E402
from screen_translator.overlays import TranslationOverlay  # noqa: E402


def test_overlay_does_not_paint_outside_ocr_bounds() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    overlay = TranslationOverlay(QRect(0, 0, 200, 100))
    overlay._regions = (
        TextRegion(
            Rect(50, 30, 60, 24),
            "Hello",
            0.99,
            translated_text="你好",
            background_color=(121, 132, 143),
            text_color=(10, 10, 10),
            font_px=20,
        ),
    )
    rendered = QImage(200, 100, QImage.Format.Format_ARGB32)
    rendered.fill(QColor(0, 0, 0, 0))
    overlay.render(rendered)

    assert rendered.pixelColor(49, 30).alpha() == 0
    assert rendered.pixelColor(110, 30).alpha() == 0
    assert rendered.pixelColor(50, 30) == QColor(121, 132, 143, 255)
    assert rendered.pixelColor(109, 53).alpha() == 255
