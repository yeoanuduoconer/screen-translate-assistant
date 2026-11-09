from pathlib import Path

from screen_translator.paths import cache_root
from screen_translator.settings import (
    AppSettings,
    SettingsStore,
    protect_secret,
    unprotect_secret,
)


def test_dpapi_secret_round_trip() -> None:
    secret = "test-secret-\u65e5\u672c\u8a9e"
    encrypted = protect_secret(secret)
    assert encrypted
    assert secret not in encrypted
    assert unprotect_secret(encrypted) == secret


def test_settings_store_round_trip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path)
    expected = AppSettings(
        provider="DeepL",
        encrypted_api_key=protect_secret("abc:fx"),
        capture_interval_ms=420,
        change_threshold=0.04,
        stable_frames=3,
    )
    store.save(expected)
    assert store.load() == expected


def test_runtime_paths_can_live_outside_source_checkout(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("SCREEN_TRANSLATOR_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("SCREEN_TRANSLATOR_CACHE_DIR", str(cache_dir))

    assert SettingsStore().path == config_dir / "config.json"
    assert cache_root() == cache_dir
    assert SettingsStore(tmp_path).path == tmp_path / "config.json"
