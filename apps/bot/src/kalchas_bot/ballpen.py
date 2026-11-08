"""Blue ballpoint marks drawn by hand over a printed slip.

Every stroke is a few control points smoothed into a curve, nudged by a seeded
wobble and drawn with uneven pressure, so a tick, a cross or a circled total
looks written, not printed. The seed comes from the slip, so the same slip
always gets the same marks.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

Point = tuple[float, float]

INK = (24, 52, 158)
FONT_PATH = Path(__file__).parent / "fonts" / "Caveat-SemiBold.ttf"


class Pen:
    """Draws on a transparent layer the size of the slip; ``apply`` lays it on."""

    def __init__(self, size: tuple[int, int], seed: str) -> None:
        self.layer = Image.new("RGBA", size, (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)
        self.rng = random.Random(seed)  # noqa: S311 — a hand wobble, not security

    # ------------------------------------------------------------ primitives

    def stroke(self, points: Sequence[Point], *, width: float = 3.0, wobble: float = 1.2) -> None:
        """One continuous pen stroke through ``points``."""
        path = _smooth([self._jitter(p, wobble) for p in points], steps=10)
        n = len(path)
        for i in range(n - 1):
            t = i / max(n - 2, 1)
            # Pressure: light touch-down, firm middle, lifting off at the end.
            pressure = 0.55 + 0.45 * math.sin(math.pi * min(1.0, 0.15 + t * 0.85))
            w = max(1.0, width * pressure * self.rng.uniform(0.9, 1.08))
            alpha = int(205 + 40 * pressure * self.rng.uniform(0.85, 1.0))
            self.draw.line((path[i], path[i + 1]), fill=(*INK, min(alpha, 245)), width=round(w))
            r = w / 2
            x, y = path[i + 1]
            self.draw.ellipse((x - r, y - r, x + r, y + r), fill=(*INK, min(alpha, 245)))

    def tick(self, cx: float, cy: float, size: float = 22) -> None:
        r = self.rng
        s = size * r.uniform(0.85, 1.12)
        short = r.uniform(0.35, 0.6)  # how far down the first stroke goes
        reach = r.uniform(0.55, 0.85)  # how high the long stroke flicks
        pts = [
            (-0.55, -0.05 + r.uniform(-0.12, 0.08)),
            (-0.3, 0.2 * short / 0.45),
            (-0.12 + r.uniform(-0.05, 0.05), short),
            (0.2, -0.1 * reach / 0.7),
            (0.45 + r.uniform(0, 0.25), -reach),
        ]
        angle = math.radians(r.uniform(-12, 9))
        cos, sin = math.cos(angle), math.sin(angle)
        self.stroke(
            [(cx + s * (x * cos - y * sin), cy + s * (x * sin + y * cos)) for x, y in pts],
            width=r.uniform(3.0, 3.8),
        )

    def cross(self, cx: float, cy: float, size: float = 20) -> None:
        s = size * self.rng.uniform(0.92, 1.08) / 2
        self.stroke(
            [(cx - s, cy - s), (cx - s * 0.1, cy - s * 0.05), (cx + s * 1.05, cy + s)], width=3.2
        )
        self.stroke(
            [(cx + s, cy - s * 1.1), (cx + s * 0.05, cy), (cx - s * 1.05, cy + s * 0.95)], width=3.2
        )

    def strike(self, x0: float, x1: float, y: float, *, wavy: bool = False) -> None:
        """A line through text, as if crossed out in a hurry."""
        count = max(4, int((x1 - x0) / 40))
        pts: list[Point] = []
        for i in range(count + 1):
            x = x0 + (x1 - x0) * i / count
            dy = (math.sin(i * 1.7) * 3.0 if wavy else 0.0) + (i / count) * self.rng.uniform(-3, 3)
            pts.append((x, y + dy))
        self.stroke(pts, width=2.6, wobble=0.8)

    def ring(self, box: tuple[float, float, float, float]) -> None:
        """A loose loop around a value, overshooting where it closes."""
        x0, y0, x1, y1 = box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = (x1 - x0) / 2 + 12, (y1 - y0) / 2 + 9
        start = self.rng.uniform(-2.6, -2.2)
        pts = []
        for i in range(15):
            a = start + i * (2 * math.pi + 0.6) / 14
            grow = 1 + 0.05 * i / 14
            pts.append((cx + math.cos(a) * rx * grow, cy + math.sin(a) * ry * grow))
        self.stroke(pts, width=2.8, wobble=1.0)

    def underline(self, x0: float, x1: float, y: float) -> None:
        self.stroke([(x0, y + 1), ((x0 + x1) / 2, y - 1), (x1, y + 2)], width=2.6)

    def text_width(self, text: str, size: int) -> float:
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        return probe.textlength(text, font=_hand(size))

    def write(
        self, xy: Point, text: str, *, size: int = 30, anchor: str = "la", tilt: float = 0
    ) -> None:
        """Handwritten words in the same ink."""
        font = _hand(size)
        pad = 12
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
        w, h = int(right - left) + pad * 2, int(bottom - top) + pad * 2
        word = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(word).text((pad - left, pad - top), text, font=font, fill=(*INK, 232))
        if tilt:
            word = word.rotate(tilt, resample=Image.Resampling.BICUBIC, expand=True)
        x, y = xy
        ww, wh = word.size
        if anchor[0] == "m":
            x -= ww / 2
        elif anchor[0] == "r":
            x -= ww
        if anchor[1] == "m":
            y -= wh / 2
        elif anchor[1] == "b":
            y -= wh
        self.layer.alpha_composite(word, (round(x), round(y)))

    # ---------------------------------------------------------------- output

    def apply(self, img: Image.Image) -> Image.Image:
        """Ink soaks into the paper a little: soften, then lay it on."""
        soft = self.layer.filter(ImageFilter.GaussianBlur(0.45))
        return Image.alpha_composite(img.convert("RGBA"), soft).convert("RGB")

    def _jitter(self, p: Point, amount: float) -> Point:
        return (p[0] + self.rng.uniform(-amount, amount), p[1] + self.rng.uniform(-amount, amount))


@lru_cache(maxsize=8)
def _hand(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if FONT_PATH.is_file():
        return ImageFont.truetype(str(FONT_PATH), size)
    return ImageFont.load_default()


def _smooth(points: Sequence[Point], *, steps: int) -> list[Point]:
    """Catmull-Rom through the control points, so strokes curve like a hand."""
    if len(points) < 3:
        return list(points)
    pts = [points[0], *points, points[-1]]
    out: list[Point] = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(
                tuple(  # type: ignore[arg-type]
                    0.5
                    * (
                        2 * p1[k]
                        + (-p0[k] + p2[k]) * t
                        + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                        + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3
                    )
                    for k in (0, 1)
                )
            )
    out.append(points[-1])
    return out
