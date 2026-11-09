from PIL import Image, ImageDraw

from screen_translator.models import Rect, TextRegion
from screen_translator.styling import sample_region_style


def test_style_tightens_expanded_ocr_box_to_visible_glyphs() -> None:
    image = Image.new("RGB", (240, 100), (242, 239, 231))
    draw = ImageDraw.Draw(image)
    draw.rectangle((58, 36, 175, 59), fill=(24, 31, 42))
    region = TextRegion(Rect(40, 20, 155, 58), "example", 0.99)

    styled = sample_region_style(image, region)

    assert 55 <= styled.box.x <= 59
    assert 33 <= styled.box.y <= 37
    assert 117 <= styled.box.width <= 123
    assert 23 <= styled.box.height <= 29
    assert styled.font_px < region.box.height


def test_style_keeps_box_on_busy_background() -> None:
    image = Image.new("RGB", (80, 60))
    pixels = image.load()
    for y in range(60):
        for x in range(80):
            pixels[x, y] = ((x * 17) % 256, (y * 23) % 256, ((x + y) * 11) % 256)
    region = TextRegion(Rect(10, 10, 50, 30), "art", 0.9)

    styled = sample_region_style(image, region)

    assert styled.box == region.box
