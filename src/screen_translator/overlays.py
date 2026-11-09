from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from functools import lru_cache

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from .models import Rect, TextRegion


def _configure_native_overlay(widget: QWidget) -> None:
    if os.name != "nt":
        return
    hwnd = wintypes.HWND(int(widget.winId()))
    user32 = ctypes.windll.user32
    get_style = user32.GetWindowLongPtrW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style = user32.SetWindowLongPtrW
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t
    set_affinity = user32.SetWindowDisplayAffinity
    set_affinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    set_affinity.restype = wintypes.BOOL
    ex_style = get_style(hwnd, -20)
    ex_style |= 0x00000020 | 0x00080000 | 0x08000000
    set_style(hwnd, -20, ex_style)
    set_affinity(hwnd, 0x00000011)


class SelectionOverlay(QWidget):
    region_selected = Signal(object)
    canceled = Signal()

    def __init__(self, virtual_geometry: QRect) -> None:
        super().__init__()
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self.setGeometry(virtual_geometry)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.activateWindow()
        self.setFocus()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._current = self._start
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._start is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._current = event.position().toPoint()
        selected = QRect(self._start, self._current).normalized()
        if selected.width() >= 20 and selected.height() >= 20:
            global_top_left = self.mapToGlobal(selected.topLeft())
            self.region_selected.emit(
                Rect(global_top_left.x(), global_top_left.y(), selected.width(), selected.height())
            )
            self.close()
        else:
            self._start = None
            self._current = None
            self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.canceled.emit()
            self.close()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(4, 8, 16, 145))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._start is not None and self._current is not None:
            selected = QRect(self._start, self._current).normalized()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(selected, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(44, 200, 255), 3))
            painter.drawRect(selected)
        painter.setPen(Qt.GlobalColor.white)
        font = QFont("Microsoft YaHei UI", 16)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRect(0, 22, self.width(), 50),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "拖动选择自动翻译区域 · Esc 取消",
        )


_WRAP_FLAGS = (
    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWrapAnywhere
)


@lru_cache(maxsize=1024)
def _fit_translation(
    text: str, width: int, height: int, source_ink_height: int
) -> tuple[QFont, QRectF | None, str]:
    font = QFont("Microsoft YaHei UI")
    text = " ".join(text.splitlines())
    ink_height = max(1, min(source_ink_height or height, height))
    for pixel_size in range(max(7, round(ink_height * 1.4)), 6, -1):
        font.setPixelSize(pixel_size)
        metrics = QFontMetricsF(font)
        ink = metrics.tightBoundingRect(text)
        if ink.width() <= width and ink.height() <= ink_height:
            return font, ink, text
    if metrics.lineSpacing() * 2 <= height:
        bounds = metrics.boundingRect(QRectF(0, 0, width, height), int(_WRAP_FLAGS), text)
        if bounds.width() <= width and bounds.height() <= height:
            return font, None, text
    text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)
    return font, metrics.tightBoundingRect(text), text


class TranslationOverlay(QWidget):
    def __init__(self, virtual_geometry: QRect) -> None:
        super().__init__()
        self._regions: tuple[TextRegion, ...] = ()
        self._selection: Rect | None = None
        self._original_visible = False
        self.setGeometry(virtual_geometry)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        _configure_native_overlay(self)

    def set_regions(self, regions: tuple[TextRegion, ...]) -> None:
        if regions == self._regions and self.isVisible() == (
            bool(regions) and not self._original_visible
        ):
            return
        self._regions = regions
        self.update()
        if regions and not self._original_visible:
            self.show()
        elif not regions:
            self.hide()

    def clear(self) -> None:
        self.set_regions(())

    def set_selection(self, selection: Rect) -> None:
        self._selection = selection
        self.update()

    def set_original_visible(self, visible: bool) -> None:
        self._original_visible = visible
        if visible or not self._regions:
            self.hide()
        else:
            self.show()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        if self._original_visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        origin = self.geometry().topLeft()
        if self._selection is not None:
            box = self._selection
            painter.setClipRect(
                QRect(box.x - origin.x(), box.y - origin.y(), box.width, box.height)
            )
        for region in self._regions:
            if not region.translated_text:
                continue
            box = region.box
            # Exact source bounds: no padding, border, shadow or rounded corner.
            # Text begins at the source box's left edge and remains vertically centered.
            rect = QRect(box.x - origin.x(), box.y - origin.y(), box.width, box.height)
            painter.fillRect(rect, QColor(*region.background_color, 255))
            font, ink, text = _fit_translation(
                region.translated_text, rect.width(), rect.height(), region.font_px
            )
            painter.save()
            painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
            painter.setFont(font)
            painter.setPen(QColor(*region.text_color, 255))
            if ink is None:
                painter.drawText(rect, _WRAP_FLAGS, text)
            else:
                painter.drawText(
                    QPointF(
                        rect.x() - ink.left(),
                        rect.y() + (rect.height() - ink.height()) / 2 - ink.top(),
                    ),
                    text,
                )
            painter.restore()
