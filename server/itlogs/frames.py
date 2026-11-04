"""Which frame is worth a model call.

The glasses send several frames a second; the reader should see one when the scene has stopped
moving (hand gone, display settled) and it should be the sharpest of those. Both measures are
pixel math on a thumbnail, free compared with a model call. Bytes that are not an image (tests,
fakes) count as still and sharp, so the loop's logic stays testable without pictures.
"""

from __future__ import annotations

import io
from collections import deque
from dataclasses import dataclass, field

from PIL import Image, ImageFilter, ImageStat

THUMB = (48, 64)  # portrait, like the glasses frames
EDGE_SIZE = (180, 320)  # enough for the digits on a scale display to count as edges


def _gray(jpeg: bytes, size: tuple[int, int]) -> Image.Image | None:
    try:
        im = Image.open(io.BytesIO(jpeg))
        im.load()
    except Exception:
        return None
    return im.convert("L").resize(size)


def sharpness(jpeg: bytes) -> float:
    """Variance of the edge image: higher is sharper. 1.0 when the bytes are not an image."""
    im = _gray(jpeg, EDGE_SIZE)
    if im is None:
        return 1.0
    return float(ImageStat.Stat(im.filter(ImageFilter.FIND_EDGES)).var[0])


def thumbnail(jpeg: bytes) -> list[int] | None:
    """Grayscale pixels at THUMB size, or None when the bytes are not an image."""
    im = _gray(jpeg, THUMB)
    return None if im is None else list(im.getdata())


def difference(a: list[int], b: list[int]) -> float:
    """Mean absolute pixel difference, 0 to 255, between two thumbnails."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b, strict=False)) / n


@dataclass
class Stillness:
    """Tracks whether the scene is still, frame by frame.

    ``move`` is the mean pixel difference (0 to 255 at thumbnail size) above which the scene
    counts as moving; ``still_ms`` how long it must stay below that to count as settled. Frames
    that are not images (tests) are still from the start.
    """

    move: float = 10.0  # head-worn camera: 18 to 35 while placing food, single digits when looking
    still_ms: int = 600
    last_diff: float = 0.0  # the last frame-to-frame difference, for tuning `move` on real runs
    _prev: list[int] | None = None
    _still_since_ms: int | None = None
    _frames: deque[tuple[int, bytes]] = field(default_factory=lambda: deque(maxlen=16))

    def observe(self, jpeg: bytes, t_ms: int) -> None:
        self._frames.append((t_ms, jpeg))
        thumb = thumbnail(jpeg)
        if thumb is None:
            # not a picture: nothing to compare, treat as still from the beginning of time
            self._still_since_ms = -1_000_000
            return
        self.last_diff = 0.0 if self._prev is None else difference(self._prev, thumb)
        if self._prev is None or self.last_diff > self.move:
            self._still_since_ms = t_ms
        self._prev = thumb

    def still(self, t_ms: int) -> bool:
        return self._still_since_ms is not None and t_ms - self._still_since_ms >= self.still_ms

    def still_since(self) -> int | None:
        return self._still_since_ms

    def sharpest(self, since_ms: int, until_ms: int) -> tuple[int, bytes] | None:
        """The sharpest frame with since_ms <= t <= until_ms, or the latest frame when none fit."""
        candidates = [(t, f) for t, f in self._frames if since_ms <= t <= until_ms]
        if not candidates:
            return self._frames[-1] if self._frames else None
        return max(candidates, key=lambda tf: sharpness(tf[1]))

    @property
    def latest(self) -> tuple[int, bytes] | None:
        return self._frames[-1] if self._frames else None
