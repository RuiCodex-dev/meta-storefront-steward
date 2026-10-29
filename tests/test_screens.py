"""Screenshot pipeline rules, offline: the screen-shape gate and the pixel-fidelity guard."""
from PIL import Image

from steward.screens import _rounded_mask, best_screen_box, fidelity


def _seg(*boxes):
    return {"boxes": [{"x1": x1, "y1": y1, "x2": x2, "y2": y2} for x1, y1, x2, y2 in boxes]}


def test_landscape_capture_takes_an_upright_phone_screen():
    # 20:9 landscape screen holds a 16:9 game (pillarboxed, as on a real phone)
    b = best_screen_box(_seg((380, 660, 1540, 1190)), 1920, 1280, 1920 / 1080)
    assert b is not None and b["aspect_error"] > 0.2


def test_a_phone_lying_flat_is_rejected():
    # seen from the front edge a flat phone is a thin sliver (ratio about 6:1), not a screen
    assert best_screen_box(_seg((150, 830, 1780, 1100)), 1920, 1280, 1920 / 1080) is None


def test_orientation_must_match():
    portrait_box = _seg((420, 850, 870, 1800))
    assert best_screen_box(portrait_box, 1280, 1920, 1080 / 1920) is not None
    assert best_screen_box(portrait_box, 1280, 1920, 1920 / 1080) is None


def test_a_screen_less_elongated_than_the_capture_is_rejected():
    # a 4:3 box cannot hold a 20:9 capture without cropping or shrinking it into a corner
    assert best_screen_box(_seg((400, 700, 1000, 1500)), 1280, 1920, 1080 / 2400) is None


def test_fidelity_guard_sees_a_single_changed_pixel():
    ui = Image.new("RGB", (40, 80), (10, 120, 200))
    mask = _rounded_mask(40, 80, 6)
    final = Image.new("RGB", (100, 100), (0, 0, 0))
    final.paste(ui, (30, 10), mask)
    assert fidelity(final, ui, (30, 10, 70, 90), mask)["max_abs_diff"] == 0
    final.putpixel((50, 50), (10, 121, 200))
    assert fidelity(final, ui, (30, 10, 70, 90), mask)["max_abs_diff"] == 1
