from screen_translator.translation import DeepLTranslator


class FakeResponse:
    def __init__(self, texts: list[str]) -> None:
        self._texts = texts

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"translations": [{"text": f"中:{text}"} for text in self._texts]}


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    def post(self, url, headers, json):
        del url, headers
        texts = list(json["text"])
        self.requests.append(texts)
        return FakeResponse(texts)


def test_translator_only_requests_new_unique_texts() -> None:
    client = FakeClient()
    translator = DeepLTranslator(client=client)  # type: ignore[arg-type]

    first = translator.translate(["Hello", "World", "Hello"], "key:fx")
    second = translator.translate(["World", "Again"], "key:fx")

    assert first == ["中:Hello", "中:World", "中:Hello"]
    assert second == ["中:World", "中:Again"]
    assert client.requests == [["Hello", "World"], ["Again"]]


def test_cache_is_separate_for_target_language() -> None:
    client = FakeClient()
    translator = DeepLTranslator(client=client)  # type: ignore[arg-type]

    translator.translate(["Hello"], "key:fx", target_lang="ZH-HANS")
    translator.translate(["Hello"], "key:fx", target_lang="JA")

    assert client.requests == [["Hello"], ["Hello"]]


def test_dense_page_splits_only_uncached_unique_texts_at_api_limit() -> None:
    client = FakeClient()
    translator = DeepLTranslator(client=client)  # type: ignore[arg-type]
    lines = [str(index) for index in range(51)]

    assert len(translator.translate([*lines, lines[0]], "key:fx")) == 52
    translator.translate(lines, "key:fx")
    assert client.requests == [lines[:50], lines[50:]]


def test_same_language_response_keeps_the_source() -> None:
    class ChineseResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            return {"translations": [{"text": "改写", "detected_source_language": "ZH"}]}

    class ChineseClient(FakeClient):
        def post(self, url, headers, json):
            return ChineseResponse(json["text"])

    translator = DeepLTranslator(client=ChineseClient())  # type: ignore[arg-type]
    assert translator.translate(["中文 API"], "key:fx") == ["中文 API"]
