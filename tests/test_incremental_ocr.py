from PIL import Image, ImageChops, ImageDraw

from screen_translator.models import Rect, TextRegion
from screen_translator.ocr import OcrSnapshot, recognize_changed


def test_local_ocr_replaces_deleted_line_and_keeps_untouched_lines() -> None:
    original = Image.new("RGB", (800, 700), "white")
    old = TextRegion(Rect(100, 90, 200, 20), "old", 0.9)
    kept = TextRegion(Rect(100, 500, 200, 20), "kept", 0.9)
    ImageDraw.Draw(original).rectangle(old.box.as_bbox(), fill="black")
    updated = original.copy()
    ImageDraw.Draw(updated).rectangle(old.box.as_bbox(), fill="white")
    ImageDraw.Draw(updated).rectangle((115, 95, 165, 105), fill="black")

    def recognize(crop: Image.Image) -> list[TextRegion]:
        assert crop.width < 350 and crop.height < 150
        left, top, right, bottom = ImageChops.invert(crop).getbbox()
        return [TextRegion(Rect(left, top, right - left, bottom - top), "new", 0.9)]

    snapshot = recognize_changed(updated, recognize, OcrSnapshot(original, (old, kept)))
    assert snapshot.regions[0].box == Rect(115, 95, 51, 11)
    assert snapshot.regions[1] is kept


def test_verified_scroll_recognizes_only_newly_exposed_strip() -> None:
    original = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(original)
    for y in range(20, 560, 70):
        draw.rectangle((y // 2, y, 390 - y // 8, y + 12), fill="black")
    old = TextRegion(Rect(80, 130, 125, 21), "kept", 0.9)
    updated = Image.new("RGB", original.size, "white")
    updated.paste(original.crop((0, 60, 400, 600)), (0, 0))

    def recognize(crop: Image.Image) -> list[TextRegion]:
        assert crop.width == 400 and crop.height < 180
        return []

    snapshot = recognize_changed(updated, recognize, OcrSnapshot(original, (old,)))
    assert len(snapshot.regions) == 1
    assert snapshot.regions[0].box == old.box.offset(0, -60)


def test_scroll_reuses_body_and_fixed_browser_bars() -> None:
    width, height = 600, 900
    header, footer, offset = 88, 850, 120
    original = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(original)
    draw.rectangle((0, 0, width - 1, header - 1), fill="navy")
    draw.rectangle((0, footer, width - 1, height - 1), fill="maroon")
    for y in range(100, 835, 70):
        draw.rectangle((15, y, width - y // 10, y + 16), fill=(y % 256, 0, 0))
    header_region = TextRegion(Rect(25, 18, 160, 23), "header", 0.9)
    body_region = TextRegion(Rect(15, 240, 190, 16), "body", 0.9)
    footer_region = TextRegion(Rect(25, 860, 160, 24), "footer", 0.9)

    updated = original.copy()
    updated.paste(original.crop((0, header + offset, width, footer)), (0, header))
    draw = ImageDraw.Draw(updated)
    draw.rectangle((0, footer - offset, width - 1, footer - 1), fill="white")
    draw.rectangle((20, 800, 320, 824), fill="black")
    calls: list[tuple[int, int]] = []

    def recognize(crop: Image.Image) -> list[TextRegion]:
        calls.append(crop.size)
        return []

    previous = OcrSnapshot(original, (header_region, body_region, footer_region))
    snapshot = recognize_changed(updated, recognize, previous)
    assert snapshot.mode == "滚动增量"
    assert len(calls) == 1 and calls[0][1] < 250
    assert snapshot.regions[:2] == (
        header_region,
        TextRegion(body_region.box.offset(0, -offset), "body", 0.9),
    )
