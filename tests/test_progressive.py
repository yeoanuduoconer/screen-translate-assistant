from PIL import Image

from screen_translator.models import Rect, TextRegion
from screen_translator.progressive import regions_in_band_core, split_horizontal_bands


def test_runtime_default_uses_one_full_page_band() -> None:
    image = Image.new("RGB", (1500, 900), "white")
    selection = Rect(100, 60, 1000, 600)

    bands = split_horizontal_bands(image, selection)

    assert len(bands) == 1
    assert bands[0].image.size == image.size
    assert bands[0].origin == selection
    assert bands[0].core_top == selection.y
    assert bands[0].core_bottom == selection.bottom


def test_explicit_bands_cover_selection_top_to_bottom() -> None:
    image = Image.new("RGB", (1500, 900), "white")
    selection = Rect(100, 60, 1000, 600)

    bands = split_horizontal_bands(image, selection, preferred_count=3)

    assert len(bands) == 3
    assert bands[0].origin.y == 60
    assert bands[0].core_top == 60
    assert bands[-1].core_bottom == 660
    assert bands[0].image.height > 300
    assert bands[1].origin.y < bands[1].core_top


def test_overlap_detections_are_assigned_to_one_core() -> None:
    image = Image.new("RGB", (1200, 900), "white")
    selection = Rect(0, 0, 800, 600)
    bands = split_horizontal_bands(image, selection, preferred_count=3)
    upper = TextRegion(Rect(20, 180, 200, 30), "upper", 0.9)
    lower = TextRegion(Rect(20, 210, 200, 30), "lower", 0.9)

    first = regions_in_band_core((upper, lower), bands[0])
    second = regions_in_band_core((upper, lower), bands[1])

    assert [item.source_text for item in first] == ["upper"]
    assert [item.source_text for item in second] == ["lower"]
