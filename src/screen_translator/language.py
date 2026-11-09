from __future__ import annotations

import re
import unicodedata

from .models import TextRegion

_LATIN_RE = re.compile(r"[A-Za-z]")
_KANA_RE = re.compile(r"[ぁ-ゖァ-ヺㇰ-ㇿｦ-ﾝ]")
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def detected_language(text: str) -> str:
    if _KANA_RE.search(text):
        return "JA"
    if _HAN_RE.search(text):
        # Latin abbreviations and shared punctuation don't make a Han line English.
        return "ZH"
    if _LATIN_RE.search(text):
        return "EN"
    return "UNKNOWN"


def normalized_target(target_language: str) -> str:
    if target_language.startswith("ZH"):
        return "ZH"
    if target_language.startswith("EN"):
        return "EN"
    return target_language


def same_language(source_language: str, target_language: str) -> bool:
    return source_language != "AUTO" and source_language == normalized_target(target_language)


def should_translate(text: str, source_language: str, target_language: str) -> bool:
    detected = detected_language(text)
    target = normalized_target(target_language)
    if source_language == "AUTO":
        return detected in {"EN", "JA"} and detected != target
    if same_language(source_language, target_language):
        return False
    if source_language == "EN":
        return detected == "EN"
    if source_language == "JA":
        return detected == "JA"
    if source_language == "ZH":
        return detected == "ZH"
    return False


def translation_changes_text(source: str, translated: str) -> bool:
    def content(text: str) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKC", text).casefold() if char.isalnum()
        )

    output = content(translated)
    return bool(output and output != content(source))


def filter_regions(
    regions: list[TextRegion], source_language: str, target_language: str
) -> list[TextRegion]:
    chinese_lines = sum(detected_language(region.source_text) == "ZH" for region in regions)
    mostly_chinese = (
        source_language == "AUTO"
        and normalized_target(target_language) == "ZH"
        and chinese_lines >= 2
        and chinese_lines * 3 >= len(regions) * 2
    )
    return [
        region
        for region in regions
        if should_translate(region.source_text, source_language, target_language)
        and not (
            mostly_chinese
            and detected_language(region.source_text) == "EN"
            and len(region.source_text.split()) <= 2
            and len(region.source_text) <= 16
        )
    ]
