from __future__ import annotations

import atexit
import hashlib
import threading
from collections import OrderedDict
from collections.abc import Sequence

import httpx

from .language import normalized_target


class TranslationError(RuntimeError):
    pass


def deepl_endpoint(api_key: str) -> str:
    if api_key.strip().endswith(":fx"):
        return "https://api-free.deepl.com/v2/translate"
    return "https://api.deepl.com/v2/translate"


class DeepLTranslator:
    def __init__(
        self,
        timeout_seconds: float = 18.0,
        max_cache_entries: int = 2048,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_cache_entries = max(1, max_cache_entries)
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self._cache: OrderedDict[tuple[str, str, str, str], str] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._closed = False
        if self._owns_client:
            atexit.register(self.close)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            self._client.close()

    def _cache_key(
        self, api_key: str, source_lang: str | None, target_lang: str, text: str
    ) -> tuple[str, str, str, str]:
        key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]
        return key_fingerprint, source_lang or "AUTO", target_lang, text

    def _remember(self, key: tuple[str, str, str, str], value: str) -> None:
        with self._cache_lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_cache_entries:
                self._cache.popitem(last=False)

    def cached_translations(
        self, texts: Sequence[str], api_key: str, source_lang: str | None, target_lang: str
    ) -> list[str | None]:
        with self._cache_lock:
            return [
                self._cache.get(self._cache_key(api_key.strip(), source_lang, target_lang, text))
                for text in texts
            ]

    def translate(
        self,
        texts: Sequence[str],
        api_key: str,
        context: str = "",
        source_lang: str | None = None,
        target_lang: str = "ZH-HANS",
    ) -> list[str]:
        clean_key = api_key.strip()
        if not clean_key:
            raise TranslationError("请先保存 DeepL API Key。")
        if not texts:
            return []

        resolved: list[str | None] = [None] * len(texts)
        missing_texts: list[str] = []
        missing_keys: list[tuple[str, str, str, str]] = []
        missing_indices: list[list[int]] = []
        missing_lookup: dict[tuple[str, str, str, str], int] = {}
        with self._cache_lock:
            for index, text in enumerate(texts):
                key = self._cache_key(clean_key, source_lang, target_lang, text)
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
                    resolved[index] = cached
                    continue
                position = missing_lookup.get(key)
                if position is None:
                    position = len(missing_texts)
                    missing_lookup[key] = position
                    missing_texts.append(text)
                    missing_keys.append(key)
                    missing_indices.append([])
                missing_indices[position].append(index)

        # DeepL accepts at most 50 text values in each request.
        for start in range(0, len(missing_texts), 50):
            end = start + 50
            translations = self._request(
                missing_texts[start:end],
                clean_key,
                context,
                source_lang,
                target_lang,
            )
            for key, indices, value in zip(
                missing_keys[start:end], missing_indices[start:end], translations, strict=True
            ):
                self._remember(key, value)
                for index in indices:
                    resolved[index] = value

        if any(value is None for value in resolved):
            raise TranslationError("翻译缓存内部状态异常。")
        return [str(value) for value in resolved]

    def _request(
        self,
        texts: Sequence[str],
        api_key: str,
        context: str,
        source_lang: str | None,
        target_lang: str,
    ) -> list[str]:
        payload: dict[str, object] = {
            "text": list(texts),
            "target_lang": target_lang,
            "model_type": "latency_optimized",
            "preserve_formatting": True,
        }
        if source_lang and source_lang != "AUTO":
            payload["source_lang"] = source_lang
        if context:
            payload["context"] = context[:6000]

        try:
            response = self._client.post(
                deepl_endpoint(api_key),
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("translations", [])
            if len(items) != len(texts):
                raise TranslationError("DeepL 返回的译文数量与原文不一致。")
            translations = [
                source
                if normalized_target(item.get("detected_source_language") or "")
                == normalized_target(target_lang)
                else item["text"]
                for source, item in zip(texts, items, strict=True)
            ]
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                message = "DeepL API Key 无效或无权限。"
            elif status == 429:
                message = "DeepL 请求过于频繁，请稍后重试。"
            elif status == 456:
                message = "DeepL 额度已用完。"
            else:
                message = f"DeepL 请求失败（HTTP {status}）。"
            raise TranslationError(message) from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise TranslationError(f"DeepL 连接或响应异常：{exc}") from exc

        return translations
