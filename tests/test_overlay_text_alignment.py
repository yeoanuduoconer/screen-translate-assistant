import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_translator.models import Rect, TextRegion  # noqa: E402
from screen_translator.overlays import TranslationOverlay  # noqa: E402


def test_translation_text_starts_at_source_left_edge() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    overlay = TranslationOverlay(QRect(0, 0, 240, 100))
    overlay._regions = (
        TextRegion(
            Rect(50, 25, 130, 46),
            "Original",
            0.99,
            translated_text="译",
            background_color=(240, 240, 240),
            text_color=(8, 8, 8),
            font_px=36,
        ),
    )
    rendered = QImage(240, 100, QImage.Format.Format_ARGB32)
    rendered.fill(QColor(0, 0, 0, 0))
    overlay.render(rendered)

    dark_x = [
        x
        for y in range(25, 71)
        for x in range(50, 180)
        if rendered.pixelColor(x, y).red() < 80
    ]
    assert dark_x
    assert min(dark_x) < 65
    assert max(dark_x) < 90
