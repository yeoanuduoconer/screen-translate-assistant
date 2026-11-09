from PIL import Image, ImageDraw

from screen_translator.capture import StableChangeGate, frame_difference, frame_signature


def image(color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (320, 180), color)


def test_signature_difference_detects_scene_change() -> None:
    black = frame_signature(image((0, 0, 0)))
    white = frame_signature(image((255, 255, 255)))
    assert frame_difference(black, white) == 1.0


def test_gate_waits_for_stable_changed_frame() -> None:
    gate = StableChangeGate(threshold=0.02, stable_frames=2)
    first = image((20, 20, 20))
    changed = image((230, 230, 230))

    assert gate.observe(first) is False
    assert gate.observe(first) is True
    assert gate.observe(first) is False
    assert gate.observe(changed) is False
    assert gate.observe(changed) is True
    assert gate.observe(changed) is False


def test_small_subtitle_change_triggers_large_selection() -> None:
    first = Image.new("RGB", (1500, 1050), "white")
    changed = first.copy()
    ImageDraw.Draw(changed).text((700, 850), "Live caption", fill="black", font_size=25)
    gate = StableChangeGate()

    assert frame_difference(frame_signature(first), frame_signature(changed)) < gate.threshold
    assert not gate.observe(first)
    assert gate.observe(first)
    assert not gate.observe(changed)
    assert gate.observe(changed)


def test_scroll_intermediate_frames_do_not_get_marked_as_processed() -> None:
    gate = StableChangeGate(quiet_seconds=0.18)
    first, middle, last = (
        frame_signature(Image.new("RGB", (640, 480), color)) for color in ("white", "gray", "black")
    )
    assert not gate.observe_signature(first, 1.00)
    assert not gate.observe_signature(first, 1.07)
    assert not gate.observe_signature(middle, 1.10)
    assert not gate.observe_signature(middle, 1.17)
    assert not gate.observe_signature(last, 1.20)
    assert not gate.observe_signature(last, 1.40, can_submit=False)
    assert gate.observe_signature(last, 1.43)
    assert gate.ready_since == 1.40
    assert not gate.observe_signature(last, 1.47)
