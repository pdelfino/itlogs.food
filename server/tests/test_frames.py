"""The frame selection: still scenes, sharp frames, and bytes that are not images."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFilter

from itlogs.frames import Stillness, difference, sharpness, thumbnail


def _jpeg(shift: int = 0, blur: float = 0.0) -> bytes:
    """A scale-like picture: a dark display with a bright number, movable and blurrable."""
    im = Image.new("L", (360, 640), 200)
    d = ImageDraw.Draw(im)
    d.rectangle((120 + shift, 300, 240 + shift, 360), fill=20)
    d.text((150 + shift, 320), "87", fill=240)
    d.rectangle((60 + shift, 200, 300 + shift, 280), fill=90)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def test_sharp_beats_blurred():
    # the synthetic scale drops from ~1170 to ~690 across blur 0 to 4: the order is what matters
    values = [sharpness(_jpeg(blur=b)) for b in (0.0, 1.0, 2.0, 4.0)]
    assert values == sorted(values, reverse=True)
    assert values[0] > values[-1] * 1.5


def test_motion_vs_stillness():
    a, b, c = thumbnail(_jpeg()), thumbnail(_jpeg()), thumbnail(_jpeg(shift=40))
    assert a is not None and b is not None and c is not None
    assert difference(a, b) < 1.0
    assert difference(a, c) > 6.0


def test_non_images_are_still_and_sharp():
    assert thumbnail(b"not a picture") is None
    assert sharpness(b"not a picture") == 1.0
    s = Stillness()
    s.observe(b"a", 0)
    assert s.still(0)


def test_still_second_then_sharpest():
    s = Stillness(still_ms=800)
    for i in range(4):
        s.observe(_jpeg(shift=i * 30), i * 150)  # a hand moving across
    assert not s.still(450)
    s.observe(_jpeg(blur=3.0), 600)  # the hand left; this frame is soft
    s.observe(_jpeg(), 750)  # the same scene, sharp
    s.observe(_jpeg(blur=2.0), 900)
    s.observe(_jpeg(blur=2.0), 1050)
    assert not s.still(1050)  # still since 600, not yet 800 ms
    s.observe(_jpeg(blur=2.0), 1450)
    assert s.still(1450)
    best = s.sharpest(s.still_since() or 0, 1450)
    assert best is not None and best[0] == 750
