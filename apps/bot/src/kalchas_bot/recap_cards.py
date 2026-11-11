"""Recap cards, weekly (three cards) and daily (one), in the "Paper" look.

Warm paper, Manrope, faint pitch lines, real crests with a soft glow in the
team's colour, and one green for goals with hatching for no goal. Drawn on a
1200x675 grid and rendered at 1.5x so X, Telegram and Discord all get a crisp
16:9 image.

Numbers, crests and charts come from the recap ``data``; every word comes
from ``texts``, which the admin has edited and approved.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from kalchas_core.recap import QUICK, normalize_texts
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from kalchas_bot import banner

logger = logging.getLogger("kalchas.bot.recap_cards")

W, H = 1200, 675
SCALE = 1.5
PAD = 52
FOOT_Y = H - 52

BG = (247, 245, 239)
INK = (19, 22, 27)
INK2 = (77, 84, 98)
MUTED = (139, 144, 154)
LINE = (227, 224, 214)
TRACK = (235, 232, 224)
TILE = (255, 255, 255)
TILE_LINE = (235, 232, 223)
GOAL = (15, 138, 92)
GOAL_SOFT = (223, 241, 232)
MISS = (166, 170, 178)
RED = (208, 69, 60)
PITCH = (239, 237, 230)

_HERE = Path(__file__).parent
FONT_PATH = _HERE / "fonts" / "Manrope-Variable.ttf"
MARK_PATH = _HERE / "assets" / "kalchas-mark.png"
_fonts: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}

READOUT: dict[str, str] = {
    "delta_goal": "+{v:.1f}",
    "delta_5min": "{v:.1f}",
    "pressure_index": "{v:.0f}",
    "rule_of_three": "{v:.1f}",
    "kscore": "{v:.0f}",
}


def render_recap_cards(data: Mapping[str, Any], texts: Mapping[str, Any]) -> list[bytes]:
    """PNG bytes for each card that has something to say."""
    words = normalize_texts(texts, data)
    if data.get("kind") == "day":
        cards = [_daily(data, words)]
    else:
        cards = [_cover(data, words)]
        if data.get("calls"):
            cards.append(_calls(data, words))
        if data.get("miss"):
            cards.append(_miss(data, words))
    out = []
    for card in cards:
        buf = BytesIO()
        card.image.save(buf, format="PNG", optimize=True)
        out.append(buf.getvalue())
    return out


# ---------------------------------------------------------------- canvas


def _font(size: float, weight: int = 500) -> ImageFont.FreeTypeFont:
    px = max(1, round(size * SCALE))
    key = (px, weight)
    if key not in _fonts:
        font = ImageFont.truetype(str(FONT_PATH), px)
        font.set_variation_by_axes([weight])
        _fonts[key] = font
    return _fonts[key]


def _s(value: float) -> int:
    return round(value * SCALE)


def _clean(value: object) -> str:
    # Manrope has no prime glyph; 76' is how most football graphics write it anyway.
    return str(value or "").replace("′", "'")


class Card:
    """Draws in 1200x675 units; everything is scaled on the way to the image."""

    def __init__(
        self, glows: Sequence[tuple[tuple[int, int, int] | None, tuple[float, float]]]
    ) -> None:
        self.image = Image.new("RGB", (_s(W), _s(H)), BG)
        self._backdrop(glows)
        self.draw = ImageDraw.Draw(self.image)

    def _backdrop(
        self, glows: Sequence[tuple[tuple[int, int, int] | None, tuple[float, float]]]
    ) -> None:
        layer = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        pen = ImageDraw.Draw(layer)
        for colour, (cx, cy) in glows:
            if colour is None:
                continue
            r = 230
            pen.ellipse([_s(cx - r), _s(cy - r), _s(cx + r), _s(cy + r)], fill=(*colour, 72))
        layer = layer.filter(ImageFilter.GaussianBlur(_s(70)))
        self.image.paste(layer, (0, 0), layer)
        pitch = ImageDraw.Draw(self.image)
        width = _s(2)
        pitch.line([(_s(600), 0), (_s(600), _s(H))], fill=PITCH, width=width)
        pitch.ellipse([_s(490), _s(227), _s(710), _s(447)], outline=PITCH, width=width)
        for x0, x1, y0, y1 in (
            (-2, 168, 157, 517),
            (1032, 1202, 157, 517),
            (-2, 58, 247, 427),
            (1142, 1202, 247, 427),
        ):
            pitch.rectangle([_s(x0), _s(y0), _s(x1), _s(y1)], outline=PITCH, width=width)

    def text(
        self,
        xy: tuple[float, float],
        value: object,
        *,
        size: float,
        weight: int = 500,
        fill: tuple[int, int, int] = INK,
        anchor: str = "la",
    ) -> float:
        font = _font(size, weight)
        clean = _clean(value)
        self.draw.text((_s(xy[0]), _s(xy[1])), clean, font=font, fill=fill, anchor=anchor)
        return font.getlength(clean) / SCALE

    def caps(
        self,
        xy: tuple[float, float],
        value: object,
        *,
        size: float,
        fill: tuple[int, int, int],
        anchor: str = "l",
    ) -> float:
        """Uppercase with a little tracking, the way small labels are set."""
        word = _clean(value).upper()
        track = size * 0.09
        total = sum(self.width(ch, size=size, weight=800) + track for ch in word) - track
        x, y = xy
        if anchor == "r":
            x -= total
        elif anchor == "m":
            x -= total / 2
        for ch in word:
            x += self.text((x, y), ch, size=size, weight=800, fill=fill) + track
        return total

    def width(self, value: object, *, size: float, weight: int = 500) -> float:
        return _font(size, weight).getlength(_clean(value)) / SCALE

    def fit(
        self, value: object, *, width: float, size: float, weight: int, smallest: float
    ) -> float:
        """The largest size up to `size` at which one line fits `width`."""
        natural = self.width(value, size=size, weight=weight)
        return size if natural <= width else max(smallest, size * width / natural)

    def lines(
        self,
        value: object,
        *,
        width: float,
        size: float,
        weight: int = 500,
        max_lines: int | None = None,
    ) -> list[str]:
        out: list[str] = []
        for para in _clean(value).split("\n"):
            current = ""
            for word in para.split():
                trial = f"{current} {word}".strip()
                if current and self.width(trial, size=size, weight=weight) > width:
                    out.append(current)
                    current = word
                else:
                    current = trial
            if current:
                out.append(current)
        if max_lines is not None and len(out) > max_lines:
            out = out[:max_lines]
            out[-1] = out[-1].rstrip(".,;:") + "…"
        return out

    def wrap(
        self,
        xy: tuple[float, float],
        value: object,
        *,
        width: float,
        size: float,
        weight: int = 500,
        fill: tuple[int, int, int] = INK,
        leading: float = 1.45,
        max_lines: int | None = None,
        align: str = "l",
    ) -> float:
        x, y = xy
        for line in self.lines(value, width=width, size=size, weight=weight, max_lines=max_lines):
            if align == "m":
                self.text(
                    (x + width / 2, y), line, size=size, weight=weight, fill=fill, anchor="ma"
                )
            else:
                self.text((x, y), line, size=size, weight=weight, fill=fill)
            y += size * leading
        return y

    def rect(
        self,
        box: tuple[float, float, float, float],
        *,
        fill: tuple[int, int, int] | None = None,
        radius: float = 0,
        outline: tuple[int, int, int] | None = None,
    ) -> None:
        self.draw.rounded_rectangle(
            [_s(v) for v in box], radius=_s(radius), fill=fill, outline=outline, width=_s(1)
        )

    def tile(self, box: tuple[float, float, float, float], radius: float = 18) -> None:
        x0, y0, x1, y1 = box
        shadow = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [_s(x0), _s(y0 + 6), _s(x1), _s(y1 + 6)], radius=_s(radius), fill=(30, 30, 20, 26)
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(_s(10)))
        self.image.paste(shadow, (0, 0), shadow)
        self.draw = ImageDraw.Draw(self.image)
        self.rect(box, fill=TILE, outline=TILE_LINE, radius=radius)

    def hline(self, y: float, x0: float = PAD, x1: float = W - PAD) -> None:
        self.draw.line([(_s(x0), _s(y)), (_s(x1), _s(y))], fill=LINE, width=_s(1))

    def hatch(self, box: tuple[float, float, float, float], *, radius: float) -> None:
        x0, y0, x1, y1 = (_s(v) for v in box)
        if x1 - x0 < 2:
            return
        layer = Image.new("RGB", (x1 - x0, y1 - y0), TRACK)
        stripes = ImageDraw.Draw(layer)
        step, h = _s(6), y1 - y0
        for start in range(-h, x1 - x0, step):
            stripes.line([(start, h), (start + h, 0)], fill=MISS, width=_s(2))
        mask = Image.new("L", layer.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, layer.size[0] - 1, layer.size[1] - 1], radius=_s(radius), fill=255
        )
        self.image.paste(layer, (x0, y0), mask)

    def dot(self, center: tuple[float, float], radius: float, fill: tuple[int, int, int]) -> None:
        cx, cy = center
        self.draw.ellipse(
            [_s(cx - radius), _s(cy - radius), _s(cx + radius), _s(cy + radius)], fill=fill
        )

    def paste(self, image: Image.Image, xy: tuple[float, float]) -> None:
        self.image.paste(image, (_s(xy[0]), _s(xy[1])), image)


# ---------------------------------------------------------------- crests


@lru_cache(maxsize=256)
def _crest_source(url: str, name: str) -> tuple[Image.Image, tuple[int, int, int] | None]:
    try:
        return banner._crest(url, name)
    except Exception:  # noqa: BLE001 - a missing crest never stops a recap
        logger.debug("crest failed for %s", name)
        return banner._letter_badge(name), None


def _crest(url: object, name: object, size: float) -> Image.Image:
    logo, _ = _crest_source(str(url or ""), str(name or ""))
    px = _s(size)
    return logo.resize((px, px), Image.Resampling.LANCZOS)


def _colour(url: object, name: object) -> tuple[int, int, int] | None:
    return _crest_source(str(url or ""), str(name or ""))[1]


def _flagged_colour(call: Mapping[str, Any] | None) -> tuple[int, int, int] | None:
    if not call:
        return None
    side = call.get("team") or "home"
    return _colour(call.get(f"{side}_logo"), call.get(side))


# ---------------------------------------------------------------- shared parts


def _header(card: Card, words: Mapping[str, str]) -> None:
    mark = _mark(38)
    if mark is not None:
        card.paste(mark, (PAD, 31))
    card.text((PAD + 50, 50), "Kalchas", size=22, weight=800, anchor="lm")
    dates = words.get("period_dates", "")
    tail = f" · {dates}" if dates else ""
    tail_w = card.text((W - PAD, 50), tail, size=16, fill=INK2, anchor="rm") if tail else 0
    card.text(
        (W - PAD - tail_w, 50), words.get("period_label", ""), size=16, weight=700, anchor="rm"
    )
    card.hline(83)


def _footer(card: Card, note: str) -> None:
    card.hline(FOOT_Y)
    card.text((PAD, H - 26), note, size=16, fill=INK2, anchor="lm")
    card.text((W - PAD, H - 26), "kalchas.live", size=16, weight=800, anchor="rm")


@lru_cache(maxsize=4)
def _mark(size: float) -> Image.Image | None:
    try:
        mark = Image.open(MARK_PATH).convert("RGBA")
    except OSError:
        return None
    px = _s(size)
    mark = mark.resize((px, px), Image.Resampling.LANCZOS)
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, px - 1, px - 1], fill=255)
    mark.putalpha(Image.composite(mark.getchannel("A"), mask, mask))
    return mark


def _headline(card: Card, words: Mapping[str, str], *, x: float, y: float, width: float) -> float:
    number = words.get("headline_number", "")
    if number.strip():  # an emptied field leaves no gap
        size = card.fit(number, width=width, size=72, weight=800, smallest=40)
        card.text((x, y), number, size=size, weight=800, fill=GOAL)
        y += size * 1.04
    return card.wrap(
        (x, y),
        words.get("headline_rest", ""),
        width=width,
        size=30,
        weight=800,
        leading=1.12,
        max_lines=2,
    )


def _timeline(
    card: Card,
    box: tuple[float, float, float],
    *,
    flags: Sequence[int],
    goal: int | None,
    height: float = 10,
) -> None:
    """A 0-90 strip: a tick for each signal, green to the goal, hatched if none came."""
    x0, x1, cy = box

    def at(minute: float) -> float:
        return x0 + (x1 - x0) * max(0.0, min(minute, 90)) / 90

    top, bottom = cy - height / 2, cy + height / 2
    card.rect((x0, top, x1, bottom), fill=TRACK, radius=height / 2)
    card.draw.line(
        [(_s(at(45)), _s(top - 3)), (_s(at(45)), _s(bottom + 3))], fill=MISS, width=_s(1)
    )
    first = min(flags) if flags else 0
    if goal is None:
        card.hatch((at(first), top, x1, bottom), radius=height / 2)
    else:
        card.rect(
            (at(first), top, max(at(goal), at(first) + 8), bottom), fill=GOAL, radius=height / 2
        )
    for minute in flags:
        card.rect((at(minute) - 1.5, top - 5, at(minute) + 1.5, bottom + 5), fill=INK, radius=1.5)
    if goal is not None:
        card.dot((at(goal), cy), 10, BG)
        card.dot((at(goal), cy), 7.5, GOAL)


def _versus(
    card: Card,
    call: Mapping[str, Any],
    *,
    cx: float,
    y: float,
    crest: float,
    spread: float,
    score_size: float,
    name_size: float = 15,
    name_width: float = 130,
    minute_label: str = "",
) -> float:
    """Crest, score, crest; names under the crests, the flagged side underlined in green."""
    flagged = call.get("team")
    score = _clean(call.get("settle_score") or call.get("fire_score") or "")
    card.text((cx, y + crest / 2), score, size=score_size, weight=800, anchor="mm")
    if minute_label:
        card.text(
            (cx, y + crest / 2 + score_size * 0.62),
            minute_label,
            size=12,
            weight=700,
            fill=MUTED,
            anchor="ma",
        )
    bottom = y + crest
    for side, centre in (("home", cx - spread), ("away", cx + spread)):
        card.paste(_crest(call.get(f"{side}_logo"), call.get(side), crest), (centre - crest / 2, y))
        ny = y + crest + 8
        is_flag = side == flagged
        end = card.wrap(
            (centre - name_width / 2, ny),
            call.get(side),
            width=name_width,
            size=name_size,
            weight=700,
            fill=INK if is_flag else INK2,
            leading=1.2,
            max_lines=2,
            align="m",
        )
        if is_flag:
            card.rect((centre - 13, end + 3, centre + 13, end + 6), fill=GOAL, radius=1.5)
            end += 6
        bottom = max(bottom, end)
    return bottom


def _goal_label(call: Mapping[str, Any]) -> str:
    return f"{call.get('goal_minute')}'" if call.get("goal_minute") is not None else ""


# ---------------------------------------------------------------- weekly: cover


def _cover(data: Mapping[str, Any], words: Mapping[str, str]) -> Card:
    calls = data.get("calls") or []
    feature = calls[0] if calls else None
    card = Card([(_flagged_colour(feature), (60, 600)), (GOAL, (1130, 40))])
    _header(card, words)
    left, lw, right = PAD, 400.0, 496.0

    card.caps((left, 112), words.get("kicker", ""), size=14, fill=GOAL)
    y = _headline(card, words, x=left, y=134, width=lw)
    card.wrap((left, y + 8), words.get("cover_line", ""), width=lw, size=18, fill=INK2, max_lines=3)

    if feature:
        top, bottom = 440.0, 605.0
        card.tile((left, top, left + lw, bottom), radius=16)
        card.caps((left + 18, top + 20), words.get("feature_label", ""), size=12, fill=MUTED)
        card.caps(
            (left + lw - 18, top + 20), words.get("feature_tag", ""), size=12, fill=GOAL, anchor="r"
        )
        end = _versus(
            card,
            feature,
            cx=left + lw / 2,
            y=top + 42,
            crest=50,
            spread=110,
            score_size=32,
            name_size=13,
            minute_label=_goal_label(feature),
        )
        card.wrap(
            (left + 18, end + 8),
            words.get("feature_line", ""),
            width=lw - 36,
            size=15,
            weight=600,
            leading=1.35,
            max_lines=2,
            align="m",
        )

    # How long until the goal
    card.text((right, 112), words.get("waits_title", ""), size=16, weight=800)
    card.text((W - PAD, 114), f"{data['total']} signals", size=14, fill=INK2, anchor="ra")
    waits = [(w["label"], int(w["count"]), True) for w in data.get("waits") or []]
    waits.append(("No goal", int(data["misses"]), False))
    most = max([n for _, n, _ in waits] + [1])
    bar_x0, bar_x1 = right + 130, W - PAD - 52
    by = 152.0
    for label, n, is_goal in waits:
        card.text(
            (right, by), label, size=15, weight=600, fill=INK if is_goal else MUTED, anchor="lm"
        )
        card.rect((bar_x0, by - 9, bar_x1, by + 9), fill=TRACK, radius=6)
        end = bar_x0 + (bar_x1 - bar_x0) * n / most
        if n and is_goal:
            card.rect((bar_x0, by - 9, end, by + 9), fill=GOAL, radius=6)
        elif n:
            card.hatch((bar_x0, by - 9, end, by + 9), radius=6)
        card.text(
            (W - PAD, by), str(n), size=15, weight=800, fill=INK if is_goal else MUTED, anchor="rm"
        )
        by += 30
    card.wrap(
        (right, by - 4),
        words.get("waits_note", ""),
        width=W - PAD - right,
        size=15,
        fill=INK2,
        max_lines=2,
    )

    # Day by day
    dy = by + 44
    card.text((right, dy), words.get("days_title", ""), size=16, weight=800)
    card.text((W - PAD, dy + 2), "goals / signals", size=14, fill=INK2, anchor="ra")
    days = data.get("days") or []
    busiest = max([int(d["total"]) for d in days] + [1])
    best = (data.get("best_day") or {}).get("day")
    col_w, col_h = 46.0, 100.0
    span = (W - PAD - right) / max(len(days), 1)
    top = dy + 32
    for index, day in enumerate(days):
        cx = right + span * index + span / 2
        x0, x1 = cx - col_w / 2, cx + col_w / 2
        card.rect((x0, top, x1, top + col_h), fill=TRACK, radius=7)
        goals, total = int(day["goals"]), int(day["total"])
        g_h, m_h = col_h * goals / busiest, col_h * (total - goals) / busiest
        if m_h:
            card.hatch((x0, top + col_h - g_h - m_h, x1, top + col_h - g_h), radius=5)
        if g_h:
            card.rect((x0, top + col_h - g_h, x1, top + col_h), fill=GOAL, radius=7)
        card.text(
            (cx, top + col_h + 8),
            f"{goals}/{total}",
            size=15,
            weight=800,
            fill=GOAL if day["day"] == best else INK,
            anchor="ma",
        )
        card.text((cx, top + col_h + 28), str(day["day"]), size=13, fill=MUTED, anchor="ma")

    _footer(card, words.get("cover_footer", ""))
    return card


# ---------------------------------------------------------------- weekly: the calls


def _calls(data: Mapping[str, Any], words: Mapping[str, str]) -> Card:
    calls: Sequence[Mapping[str, Any]] = data["calls"][:3]
    card = Card([(_flagged_colour(calls[0]), (40, 640)), (GOAL, (1140, 30))])
    _header(card, words)
    card.text((PAD, 104), words.get("calls_title", ""), size=40, weight=800)
    card.text((W - PAD, 126), words.get("calls_sub", ""), size=16, fill=INK2, anchor="rm")

    gap_x = 18.0
    tile_w = (W - 2 * PAD - gap_x * (len(calls) - 1)) / len(calls)
    top, bottom = 166.0, 605.0
    for index, call in enumerate(calls):
        x0 = PAD + index * (tile_w + gap_x)
        x1 = x0 + tile_w
        inner = tile_w - 40
        card.tile((x0, top, x1, bottom))
        card.caps(
            (x0 + tile_w / 2, top + 18), call.get("league") or "", size=11, fill=MUTED, anchor="m"
        )
        end = _versus(
            card,
            call,
            cx=x0 + tile_w / 2,
            y=top + 42,
            crest=66,
            spread=tile_w * 0.3,
            score_size=38,
            name_width=tile_w * 0.38,
            minute_label=_goal_label(call),
        )
        gap = int(call.get("gap") or 0)
        flags = call.get("flags") or [call["minute"]]
        # A goal inside a minute reads as "too fast to act on"; under 2 min reads as quick.
        big = "Under 2 min" if gap <= QUICK else f"{gap} min"
        label = "after the last signal" if len(flags) > 1 else "after the signal"
        by = end + 22
        big_w = card.text((x0 + 20, by), big, size=32, weight=800, fill=GOAL)
        card.text((x0 + 20 + big_w + 8, by + 15), label, size=14, fill=INK2)
        _timeline(card, (x0 + 20, x1 - 20, by + 56), flags=flags, goal=call.get("goal_minute"))
        signal_text = "Signal " if len(flags) == 1 else "Signals "
        sw = card.text((x0 + 20, by + 70), signal_text, size=14, fill=INK2)
        card.text((x0 + 20 + sw, by + 70), " ".join(f"{m}'" for m in flags), size=14, weight=800)
        gw = card.text(
            (x1 - 20, by + 70), f"{call.get('goal_minute')}'", size=14, weight=800, anchor="ra"
        )
        card.text((x1 - 20 - gw, by + 70), "Goal ", size=14, fill=INK2, anchor="ra")
        story_y = by + 98
        max_lines = max(2, int((bottom - 14 - story_y) / (17 * 1.45)))
        card.wrap(
            (x0 + 20, story_y),
            words.get(f"call_{index + 1}", ""),
            width=inner,
            size=17,
            max_lines=max_lines,
        )

    _footer(card, words.get("calls_footer", ""))
    return card


# ---------------------------------------------------------------- weekly: the miss


def _miss(data: Mapping[str, Any], words: Mapping[str, str]) -> Card:
    miss: Mapping[str, Any] = data["miss"]
    card = Card(
        [
            (_colour(miss.get("home_logo"), miss.get("home")), (40, 640)),
            (_colour(miss.get("away_logo"), miss.get("away")), (1150, 20)),
        ]
    )
    _header(card, words)
    left_w, right = 650.0, 752.0

    card.caps((PAD, 112), words.get("miss_kicker", ""), size=14, fill=RED)
    crest = 64.0
    y = 136.0
    card.paste(_crest(miss.get("home_logo"), miss.get("home"), crest), (PAD, y))
    score = _clean(miss.get("settle_score") or miss.get("fire_score") or "")
    score_w = card.width(score, size=28, weight=800)
    card.text((PAD + crest + 12, y + crest / 2), score, size=28, weight=800, anchor="lm")
    away_x = PAD + crest + 24 + score_w
    card.paste(_crest(miss.get("away_logo"), miss.get("away"), crest), (away_x, y))
    title_x = away_x + crest + 22
    title_w = PAD + left_w - title_x
    title = f"{miss.get('home')} v {miss.get('away')}"
    size = card.fit(title, width=title_w, size=32, weight=800, smallest=22)
    end = card.wrap(
        (title_x, y + 4), title, width=title_w, size=size, weight=800, leading=1.1, max_lines=2
    )
    meta = " · ".join(
        p for p in (miss.get("league"), f"Signal at {miss['minute']}'", "No goal") if p
    )
    card.wrap((title_x, end + 2), meta, width=title_w, size=14, fill=INK2, max_lines=1)

    y = max(y + crest, end + 22) + 20
    _timeline(card, (PAD, PAD + left_w, y), flags=miss.get("flags") or [miss["minute"]], goal=None)
    y = card.wrap(
        (PAD, y + 22), words.get("miss", ""), width=left_w, size=19, leading=1.5, max_lines=5
    )

    lesson = words.get("lesson", "").strip()
    if lesson:
        lines = card.lines(lesson, width=left_w - 36, size=20, weight=700, max_lines=3)
        box_h = 46 + 27 * len(lines)
        top = min(y + 14, FOOT_Y - 16 - box_h)
        card.tile((PAD, top, PAD + left_w, top + box_h), radius=14)
        card.caps((PAD + 18, top + 16), words.get("lesson_label", ""), size=12, fill=MUTED)
        for i, line in enumerate(lines):
            card.text((PAD + 18, top + 36 + 27 * i), line, size=20, weight=700)

    readout = _readout(miss)
    ry = 112.0
    if readout:
        big_w = card.text((right, ry - 6), readout, size=58, weight=800)
        card.wrap(
            (right + big_w + 16, ry + 4),
            words.get("readout_note", ""),
            width=W - PAD - right - big_w - 16,
            size=15,
            fill=INK2,
            leading=1.35,
            max_lines=3,
        )
        ry += 82
    card.hline(ry, right, W - PAD)
    _compare(card, miss, x0=right, x1=W - PAD, y=ry + 18)
    _footer(card, words.get("miss_footer", ""))
    return card


def _readout(miss: Mapping[str, Any]) -> str | None:
    value = miss.get("value")
    for key in miss.get("strategies") or []:
        if key in READOUT and value is not None:
            return READOUT[key].format(v=float(value))
    return None


def _compare(card: Card, miss: Mapping[str, Any], *, x0: float, x1: float, y: float) -> None:
    """FotMob-style head to head: value, label, value, and a bar split from the middle."""
    stats = miss.get("stats") or []
    if not stats:
        return
    card.text((x0, y), miss.get("team_name") or "", size=14, weight=800)
    card.text((x1, y), miss.get("other_name") or "", size=14, weight=800, fill=INK2, anchor="ra")
    mid = (x0 + x1) / 2
    row_y = y + 34
    for stat in stats[:5]:
        own, other = int(stat["own"]), int(stat["other"])
        unit = "%" if stat.get("percent") else ""
        card.text((x0, row_y), f"{own}{unit}", size=16, weight=800)
        card.text((mid, row_y), stat["label"], size=15, fill=INK2, anchor="ma")
        card.text((x1, row_y), f"{other}{unit}", size=16, weight=800, anchor="ra")
        total = max(own + other, 1)
        by = row_y + 26
        card.rect((x0, by, mid - 3, by + 7), fill=TRACK, radius=3.5)
        card.rect((mid + 3, by, x1, by + 7), fill=TRACK, radius=3.5)
        own_w = (mid - 3 - x0) * own / total
        other_w = (x1 - mid - 3) * other / total
        if own_w:
            card.rect(
                (mid - 3 - own_w, by, mid - 3, by + 7),
                fill=INK if own >= other else MISS,
                radius=3.5,
            )
        if other_w:
            card.rect(
                (mid + 3, by, mid + 3 + other_w, by + 7),
                fill=INK if other > own else MISS,
                radius=3.5,
            )
        row_y += 54


# ---------------------------------------------------------------- daily


def _daily(data: Mapping[str, Any], words: Mapping[str, str]) -> Card:
    calls: Sequence[Mapping[str, Any]] = (data.get("calls") or [])[:4]
    card = Card([(_flagged_colour(calls[0] if calls else None), (40, 640)), (GOAL, (1140, 30))])
    _header(card, words)
    left, lw, right = PAD, 360.0, 452.0

    card.caps((left, 112), words.get("kicker", ""), size=14, fill=GOAL)
    y = _headline(card, words, x=left, y=134, width=lw)
    y = card.wrap(
        (left, y + 8), words.get("cover_line", ""), width=lw, size=18, fill=INK2, max_lines=3
    )

    ring_y = max(y + 24, 430.0)
    ring_text = words.get("ring_value", "").strip()
    text_x = left
    if ring_text:
        _ring(card, (left + 56, ring_y + 56), 46, ring_text)
        text_x = left + 132
    card.wrap(
        (text_x, ring_y + 18),
        words.get("fastest_title", ""),
        width=left + lw - text_x,
        size=19,
        weight=800,
        leading=1.2,
        max_lines=2,
    )
    card.wrap(
        (text_x, ring_y + 46),
        words.get("fastest_line", ""),
        width=left + lw - text_x,
        size=15,
        fill=INK2,
        leading=1.35,
        max_lines=3,
    )

    if calls:
        top, bottom, gap = 108.0, 605.0, 10.0
        row_h = min(124.0, (bottom - top - gap * (len(calls) - 1)) / len(calls))
        for index, call in enumerate(calls):
            y0 = top + index * (row_h + gap)
            card.tile((right, y0, W - PAD, y0 + row_h), radius=16)
            crest = 44.0
            cy = y0 + row_h / 2
            card.paste(
                _crest(call.get("home_logo"), call.get("home"), crest), (right + 16, cy - crest / 2)
            )
            card.text(
                (right + 16 + crest + 31, cy),
                _clean(call.get("settle_score") or ""),
                size=22,
                weight=800,
                anchor="mm",
            )
            card.paste(
                _crest(call.get("away_logo"), call.get("away"), crest),
                (right + 16 + crest + 62, cy - crest / 2),
            )
            tx = right + 16 + 2 * crest + 84
            tw = W - PAD - 18 - tx
            name = call.get("team_name") or f"{call.get('home')} v {call.get('away')}"
            name_w = card.text((tx, y0 + 14), name, size=17, weight=800)
            card.text(
                (tx + name_w + 8, y0 + 17),
                call.get("league") or "",
                size=13,
                weight=600,
                fill=MUTED,
            )
            pill = f"{' '.join(str(m) + chr(39) for m in call.get('flags') or [call['minute']])} → {call.get('goal_minute')}'"
            pill_w = card.width(pill, size=13, weight=800) + 20
            card.rect(
                (W - PAD - 18 - pill_w, y0 + 40, W - PAD - 18, y0 + 62), fill=GOAL_SOFT, radius=11
            )
            card.text(
                (W - PAD - 18 - pill_w / 2, y0 + 51),
                pill,
                size=13,
                weight=800,
                fill=GOAL,
                anchor="mm",
            )
            _timeline(
                card,
                (tx, W - PAD - 30 - pill_w, y0 + 51),
                flags=call.get("flags") or [call["minute"]],
                goal=call.get("goal_minute"),
                height=8,
            )
            card.wrap(
                (tx, y0 + 70),
                words.get(f"call_{index + 1}", ""),
                width=tw,
                size=14.5,
                fill=INK2,
                leading=1.38,
                max_lines=2 if row_h >= 110 else 1,
            )

    _footer(card, words.get("day_footer", ""))
    return card


def ring_share(text: str) -> float:
    """How full the ring is, read from what the admin typed: "55%", "17/31" or "0.55"."""
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return 0.0
    if "/" in text and len(numbers) >= 2 and numbers[1]:
        share = numbers[0] / numbers[1]
    elif "%" in text or numbers[0] > 1:
        share = numbers[0] / 100
    else:
        share = numbers[0]
    return max(0.0, min(share, 1.0))


def _ring(card: Card, center: tuple[float, float], radius: float, text: str) -> None:
    cx, cy = center
    share = ring_share(text)
    box = [_s(cx - radius), _s(cy - radius), _s(cx + radius), _s(cy + radius)]
    card.draw.ellipse(box, outline=TRACK, width=_s(12))
    if share > 0:
        card.draw.arc(box, start=-90, end=-90 + 360 * share, fill=GOAL, width=_s(12))
    size = card.fit(text, width=radius * 1.5, size=22, weight=800, smallest=12)
    card.text((cx, cy), text, size=size, weight=800, anchor="mm")
