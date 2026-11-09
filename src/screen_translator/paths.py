from __future__ import annotations

import os
import sys
from pathlib import Path


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def cache_root() -> Path:
    override = os.environ.get("SCREEN_TRANSLATOR_CACHE_DIR")
    return Path(override) if override else application_root() / ".cache"
