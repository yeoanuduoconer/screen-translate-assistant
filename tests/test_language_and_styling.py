import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from screen_translator.language import (
    detected_language,
    filter_regions,
    same_language,
    translation_changes_text,
)
from screen_translator.models import Rect, TextRegion
from screen_translator.styling import sample_region_style


def region(text: str) -> TextRegion:
    return TextRegion(Rect(0, 0, 100, 24), text, 0.9)


def test_language_detection_distinguishes_latin_kana_and_han() -> None:
    assert detected_language("Settings") == "EN"
    assert detected_language("設定してください") == "JA"
    assert detected_language("系统设置") == "ZH"


def test_auto_mode_skips_han_only_chinese() -> None:
    regions = [region("Settings"), region("設定してください"), region("系统设置")]
    accepted = filter_regions(regions, "AUTO", "ZH-HANS")
    assert [item.source_text for item in accepted] == ["Settings", "設定してください"]


def test_japanese_selection_leaves_ambiguous_han_and_chinese_ui_intact() -> None:
    lines = [region("攻撃開始"), region("系统设置 · API"), region("設定を保存")]
    accepted = filter_regions(lines, "JA", "ZH-HANS")
    assert [item.source_text for item in accepted] == ["設定を保存"]


def test_chinese_page_with_shared_punctuation_and_english_label_is_left_untouched() -> None:
    lines = [region("中文・简体"), region("设置 API Key"), region("Windows")]
    assert filter_regions(lines, "AUTO", "ZH-HANS") == []
    assert not translation_changes_text("Windows", "Windows.")
    assert not translation_changes_text("中文ＡＰＩ", "中文 API。")
    assert translation_changes_text("Settings", "设置")


def test_same_language_recognizes_deepl_variants() -> None:
    assert same_language("ZH", "ZH-HANS")
    assert same_language("EN", "EN-US")
    assert same_language("JA", "JA")
    assert not same_language("AUTO", "ZH-HANS")


def test_region_style_samples_background_and_fits_tight_height() -> None:
    background = (232, 218, 196)
    image = Image.new("RGB", (360, 100), background)
    draw = ImageDraw.Draw(image)
    font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf"
    font = ImageFont.truetype(font_path, 32) if font_path.is_file() else ImageFont.load_default(32)
    bounds = draw.textbbox((40, 28), "Hello", font=font)
    draw.text((40, 28), "Hello", font=font, fill=(24, 31, 42))
    box = Rect(bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1])
    styled = sample_region_style(image, TextRegion(box, "Hello", 0.99))
    assert all(
        abs(left - right) <= 2
        for left, right in zip(styled.background_color, background, strict=False)
    )
    assert styled.font_px == max(8, round(styled.box.height * 0.90))
    assert styled.font_px <= box.height
    assert sum(styled.text_color) < sum(styled.background_color)
