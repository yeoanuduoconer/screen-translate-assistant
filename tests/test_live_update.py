from threading import Event
from time import monotonic, sleep

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from screen_translator import main_window
from screen_translator.models import Rect, TextRegion
from screen_translator.settings import AppSettings
from screen_translator.translation import DeepLTranslator


def test_new_translation_displays_while_older_request_is_blocked(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    first_requested = Event()
    release_first = Event()
    release_second = Event()
    requests: list[list[str]] = []
    box = Rect(40, 30, 120, 40)
    cached_box = Rect(40, 100, 120, 40)
    shared_box = Rect(40, 160, 120, 40)
    first = Image.new("RGB", (400, 220), "white")
    second = Image.new("RGB", first.size, "black")
    ImageDraw.Draw(first).rectangle((50, 40, 100, 55), fill="black")
    ImageDraw.Draw(second).rectangle((82, 54, 148, 63), fill="white")
    ImageDraw.Draw(second).rectangle((65, 110, 140, 130), fill="white")
    ImageDraw.Draw(second).rectangle((61, 170, 132, 189), fill="white")
    image = first

    class Capturer:
        def grab(self, region: Rect) -> Image.Image:
            return image

    class Ocr:
        def recognize(self, frame: Image.Image) -> list[TextRegion]:
            if frame.getpixel((0, 0)) == (255, 255, 255):
                return [TextRegion(box, "Old frame", 0.9)]
            return [
                TextRegion(box, "New frame", 0.9),
                TextRegion(cached_box, "Known line", 0.9),
                TextRegion(shared_box, "Old frame", 0.9),
            ]

    class Response:
        def __init__(self, texts):
            self.texts = texts

        def raise_for_status(self):
            pass

        def json(self):
            return {"translations": [{"text": f"译文 {text}"} for text in self.texts]}

    class Client:
        def post(self, url, headers, json):
            texts = json["text"]
            requests.append(texts)
            if texts == ["Old frame"]:
                first_requested.set()
                assert release_first.wait(10)
            if texts == ["New frame"]:
                assert release_second.wait(5)
            return Response(texts)

    translator = DeepLTranslator(client=Client())  # type: ignore[arg-type]
    translator.translate(["Known line"], "test")
    requests.clear()
    monkeypatch.setattr(
        main_window, "_PERFORMANCE_LOG", tmp_path / "performance.jsonl", raising=False
    )
    monkeypatch.setattr(main_window, "ScreenCapturer", Capturer)
    monkeypatch.setattr(main_window, "PaddleOcrEngine", Ocr)
    monkeypatch.setattr(main_window, "DeepLTranslator", lambda: translator)
    monkeypatch.setattr(main_window.GlobalHotkeys, "start", lambda self: None)
    monkeypatch.setattr(main_window.SettingsStore, "load", lambda self: AppSettings())
    window = main_window.MainWindow()
    window._api_key.setText("test")
    window._region = Rect(0, 0, *first.size)
    window._capture_timer.start()

    def pump_until(predicate) -> None:
        deadline = monotonic() + 3
        while not predicate() and monotonic() < deadline:
            app.processEvents()
            sleep(0.005)
        assert predicate()

    try:
        pump_until(first_requested.is_set)
        scroll_at = monotonic()
        image = second
        pump_until(lambda: requests == [["Old frame"], ["New frame"]])
        assert [item.source_text for item in window._overlay._regions] == ["Known line"]
        release_second.set()
        pump_until(
            lambda: any(item.source_text == "New frame" for item in window._overlay._regions)
        )
        print(f"New viewport to visible translation: {monotonic() - scroll_at:.3f}s")
        assert not release_first.is_set()
        release_first.set()
        pump_until(lambda: len(window._overlay._regions) == 3)
        assert requests == [["Old frame"], ["New frame"]]
    finally:
        release_first.set()
        release_second.set()
        window.close()
