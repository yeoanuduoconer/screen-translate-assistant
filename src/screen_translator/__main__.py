from __future__ import annotations

import ctypes
import multiprocessing as mp
import os
import traceback

from .app import main
from .paths import cache_root


def _report_startup_error(error: BaseException) -> None:
    log_path = cache_root() / "startup-error.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass
    if os.name == "nt":
        message = f"屏幕翻译助手启动失败：\n\n{error}\n\n错误日志：\n{log_path}"
        ctypes.windll.user32.MessageBoxW(None, message, "屏幕翻译助手", 0x10)


if __name__ == "__main__":
    mp.freeze_support()
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        _report_startup_error(exc)
        raise
