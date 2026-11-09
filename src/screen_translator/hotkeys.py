from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal


class GlobalHotkeys(QObject):
    triggered = Signal(str)
    registration_error = Signal(str)

    _HOTKEYS = {
        1: ("start", ord("T")),
        2: ("original", ord("O")),
        3: ("pause", ord("P")),
        4: ("stop", ord("S")),
    }

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()

    def start(self) -> None:
        if os.name != "nt" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="global-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = 0

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()

        modifiers = 0x0002 | 0x0004 | 0x4000  # CTRL | SHIFT | NOREPEAT
        registered: list[int] = []
        for hotkey_id, (_name, virtual_key) in self._HOTKEYS.items():
            if user32.RegisterHotKey(None, hotkey_id, modifiers, virtual_key):
                registered.append(hotkey_id)
            else:
                self.registration_error.emit(f"快捷键 Ctrl+Shift+{chr(virtual_key)} 注册失败。")

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == 0x0312:  # WM_HOTKEY
                item = self._HOTKEYS.get(int(message.wParam))
                if item:
                    self.triggered.emit(item[0])

        for hotkey_id in registered:
            user32.UnregisterHotKey(None, hotkey_id)
