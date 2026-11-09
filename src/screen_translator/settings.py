from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "ScreenTranslateAssistant"


@dataclass(slots=True)
class AppSettings:
    provider: str = "DeepL"
    encrypted_api_key: str = ""
    source_language: str = "AUTO"
    target_language: str = "ZH-HANS"
    capture_interval_ms: int = 300
    change_threshold: float = 0.025
    stable_frames: int = 2


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def protect_secret(value: str) -> str:
    if not value:
        return ""
    if os.name != "nt":
        raise RuntimeError("Credential encryption is supported only on Windows.")
    source, source_buffer = _blob_from_bytes(value.encode("utf-8"))
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(source), APP_NAME, None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        del source_buffer
        kernel32.LocalFree(output.pbData)


def unprotect_secret(value: str) -> str:
    if not value:
        return ""
    encrypted = base64.b64decode(value)
    source, source_buffer = _blob_from_bytes(encrypted)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        del source_buffer
        kernel32.LocalFree(output.pbData)


class SettingsStore:
    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            override = os.environ.get("SCREEN_TRANSLATOR_CONFIG_DIR")
            local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            root = Path(override) if override else local_app_data / APP_NAME
        self.root = root
        self.path = root / "config.json"

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = {field.name for field in AppSettings.__dataclass_fields__.values()}
            return AppSettings(**{key: value for key, value in data.items() if key in allowed})
        except (OSError, ValueError, TypeError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)
