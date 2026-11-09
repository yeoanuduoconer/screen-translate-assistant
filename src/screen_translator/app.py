from __future__ import annotations

import os
import sys

from .paths import cache_root


def _configure_environment() -> None:
    # These must be set before importing NumPy, Qt or Paddle. Setting them in
    # the OCR module is too late because screen-capture imports NumPy first.
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache_root() / "paddlex"))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("PADDLE_PDX_CPU_NUM_THREADS", "4")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")


def main() -> int:
    _configure_environment()
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("ScreenTranslateAssistant")
    app.setOrganizationName("ScreenTranslateAssistant")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
