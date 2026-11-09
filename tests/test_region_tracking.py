import cv2
import numpy as np
from PIL import Image

from screen_translator.models import Rect, TextRegion
from screen_translator.region_tracking import RegionTemplateTracker


def _frame(dx: int = 0, dy: int = 0, animated_noise: bool = False) -> Image.Image:
    canvas = np.full((320, 520, 3), 238, dtype=np.uint8)
    cv2.putText(
        canvas,
        "Anchor One",
        (70 + dx, 100 + dy),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (25, 31, 42),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "Anchor Two",
        (70 + dx, 190 + dy),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (25, 31, 42),
        2,
        cv2.LINE_AA,
    )
    if animated_noise:
        canvas[10:65, 300:500] = np.random.default_rng(5).integers(
            0, 255, (55, 200, 3), dtype=np.uint8
        )
    return Image.fromarray(canvas)


def test_region_tracker_follows_text_and_ignores_unrelated_animation() -> None:
    bounds = Rect(100, 50, 520, 320)
    regions = (
        TextRegion(Rect(170, 118, 205, 36), "Anchor One", 0.99, translated_text="锚点一"),
        TextRegion(Rect(170, 208, 205, 36), "Anchor Two", 0.99, translated_text="锚点二"),
    )
    tracker = RegionTemplateTracker()
    tracker.initialize(_frame(), regions, bounds)

    result = tracker.track(_frame(34, -21, animated_noise=True))

    assert result.lost is False
    assert result.regions is not None
    assert abs(result.regions[0].box.x - (regions[0].box.x + 34)) <= 1
    assert abs(result.regions[0].box.y - (regions[0].box.y - 21)) <= 1


def test_region_tracker_reports_lost_when_source_text_disappears() -> None:
    bounds = Rect(0, 0, 520, 320)
    regions = (TextRegion(Rect(70, 68, 205, 36), "Anchor One", 0.99, translated_text="锚点一"),)
    tracker = RegionTemplateTracker()
    tracker.initialize(_frame(), regions, bounds)

    blank = Image.new("RGB", (520, 320), (238, 238, 238))
    result = tracker.track(blank)

    assert result.lost is True


def test_fixed_header_and_body_keep_independent_positions_during_fast_scroll() -> None:
    width, height = 640, 520
    bounds = Rect(0, 0, width, height)
    header = TextRegion(Rect(31, 22, 245, 31), "Fixed tools", 0.9, "固定工具栏")
    body = TextRegion(Rect(70, 395, 285, 32), "A translated line", 0.9, "已经翻好的行")

    def page(shift: int, *, include_body: bool = True) -> Image.Image:
        pixels = np.full((height, width, 3), 245, dtype=np.uint8)
        cv2.putText(
            pixels, header.source_text, (32, 47), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2
        )
        if include_body:
            cv2.putText(
                pixels,
                body.source_text,
                (72, 422 - shift),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 0, 0),
                2,
            )
        return Image.fromarray(pixels)

    tracker = RegionTemplateTracker()
    tracker.initialize(page(0), (header, body), bounds)
    assert tracker.track(page(0)).regions == (header, body)

    for offset in (61, 148, 310):
        visible = tracker.track(page(offset)).regions
        assert visible is not None
        assert [region.box for region in visible] == [header.box, body.box.offset(0, -offset)]

    only_header = page(0, include_body=False)
    assert tracker.track(only_header).regions == (header,)
    tracker.remember(only_header, (header,), bounds)
    returned = tracker.track(page(280)).regions
    assert returned is not None
    assert [region.box for region in returned] == [header.box, body.box.offset(0, -280)]
