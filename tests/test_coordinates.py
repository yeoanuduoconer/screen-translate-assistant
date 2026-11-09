from screen_translator.coordinates import map_regions_to_logical_screen
from screen_translator.models import Rect, TextRegion


def test_maps_physical_ocr_coordinates_to_150_percent_logical_screen() -> None:
    selection = Rect(400, 200, 600, 300)
    physical = TextRegion(Rect(150, 60, 300, 45), "Hello", 0.99, font_px=42)
    mapped = map_regions_to_logical_screen([physical], selection, (900, 450))[0]
    assert mapped.box == Rect(500, 240, 200, 30)
    assert mapped.font_px == 28
