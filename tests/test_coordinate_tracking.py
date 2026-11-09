from screen_translator.coordinates import shift_regions_within
from screen_translator.models import Rect, TextRegion


def test_shifts_overlay_with_page_and_clips_to_selection() -> None:
    bounds = Rect(100, 100, 300, 200)
    regions = (
        TextRegion(Rect(140, 130, 80, 24), "Hello", 0.9, translated_text="你好"),
        TextRegion(Rect(350, 270, 80, 24), "Edge", 0.9, translated_text="边缘"),
    )
    shifted = shift_regions_within(regions, 20, -15, bounds)
    assert shifted[0].box == Rect(160, 115, 80, 24)
    assert shifted[1].box == Rect(370, 255, 30, 24)
