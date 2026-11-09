from screen_translator.translation import deepl_endpoint


def test_deepl_free_key_uses_free_endpoint() -> None:
    assert deepl_endpoint("example:fx") == "https://api-free.deepl.com/v2/translate"


def test_deepl_pro_key_uses_pro_endpoint() -> None:
    assert deepl_endpoint("example") == "https://api.deepl.com/v2/translate"
