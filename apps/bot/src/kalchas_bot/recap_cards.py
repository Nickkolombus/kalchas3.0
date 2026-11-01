"""The weekly recap as three PNG cards: the week, three calls, the miss.

Direction A ("match sheet"): warm paper, Manrope, one green for goals and
hatching for no goal, the same on every card. Drawn on a 1200x675 grid and
rendered at 1.5x so X, Telegram and Discord all get a crisp 16:9 image.

Numbers come from the recap ``data``; every sentence comes from ``texts``,
which the admin has edited and approved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 675
SCALE = 1.5
PAD = 52

BG = (247, 246, 242)
INK = (18, 21, 26)
INK2 = (75, 82, 96)
MUTED = (138, 144, 155)
LINE = (226, 224, 216)
TRACK = (233, 231, 225)
GOAL = (15, 138, 92)
MISS = (163, 168, 177)
RED = (194, 65, 58)

_HERE = Path(__file__).parent
FONT_PATH = _HERE / "fonts" / "Manrope-Variable.ttf"
MARK_PATH = _HERE / "assets" / "kalchas-mark.png"
_fonts: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}

STRATEGY_READOUT: dict[str, tuple[str, str]] = {
    "delta_goal": ("+{v:.1f}", "goals owed on form"),
    "delta_5min": ("{v:.1f}", "5-minute pressure, out of 12"),
    "pressure_index": ("{v:.0f}", "sustained pressure, out of 100"),
    "rule_of_three": ("{v:.1f}", "unrealised goals"),
    "kscore": ("{v:.0f}", "K-Score, out of 100"),
}


def render_recap_cards(data: Mapping[str, Any], texts: Mapping[str, Any]) -> list[bytes]:
    """PNG bytes for each card that has something to say (the cover always does)."""
    cards = [_cover(data, texts)]
    if data.get("calls"):
        cards.append(_calls(data, texts))
    if data.get("miss"):
        cards.append(_miss(data, texts))
    out = []
    for card in cards:
        buf = BytesIO()
        card.image.save(buf, format="PNG", optimize=True)
        out.append(buf.getvalue())
    return out


# ---------------------------------------------------------------- canvas


def _font(size: float, weight: int = 500) -> ImageFont.FreeTypeFont:
    px = round(size * SCALE)
    key = (px, weight)
    if key not in _fonts:
        font = ImageFont.truetype(str(FONT_PATH), px)
        font.set_variation_by_axes([weight])
        _fonts[key] = font
    return _fonts[key]


def _s(value: float) -> int:
    return round(value * SCALE)


class Card:
    """Draws in 1200x675 units; everything is scaled on the way to the image."""

    def __init__(self) -> None:
        self.image = Image.new("RGB", (_s(W), _s(H)), BG)
        self.draw = ImageDraw.Draw(self.image)

    def text(
        self,
        xy: tuple[float, float],
        value: str,
        *,
        size: float,
        weight: int = 500,
        fill: tuple[int, int, int] = INK,
        anchor: str = "la",
    ) -> float:
        """Draws one line; returns its width in card units."""
        font = _font(size, weight)
        clean = _clean(value)
        self.draw.text((_s(xy[0]), _s(xy[1])), clean, font=font, fill=fill, anchor=anchor)
        return font.getlength(clean) / SCALE

    def width(self, value: str, *, size: float, weight: int = 500) -> float:
        return _font(size, weight).getlength(_clean(value)) / SCALE

    def wrap(
        self,
        xy: tuple[float, float],
        value: str,
        *,
        width: float,
        size: float,
        weight: int = 500,
        fill: tuple[int, int, int] = INK,
        leading: float = 1.45,
        max_lines: int | None = None,
    ) -> float:
        """Word-wrapped paragraph; returns the y just below it."""
        x, y = xy
        for line in self.lines(value, width=width, size=size, weight=weight, max_lines=max_lines):
            self.text((x, y), line, size=size, weight=weight, fill=fill)
            y += size * leading
        return y

    def lines(
        self, value: str, *, width: float, size: float, weight: int, max_lines: int | None = None
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
            out.append(current)
        if max_lines is not None and len(out) > max_lines:
            out = out[:max_lines]
            out[-1] = out[-1].rstrip(".,;:") + "…"
        return out

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

    def hline(self, y: float, x0: float = PAD, x1: float = W - PAD) -> None:
        self.draw.line([(_s(x0), _s(y)), (_s(x1), _s(y))], fill=LINE, width=_s(1))

    def vline(self, x: float, y0: float, y1: float) -> None:
        self.draw.line([(_s(x), _s(y0)), (_s(x), _s(y1))], fill=LINE, width=_s(1))

    def hatch(self, box: tuple[float, float, float, float], *, radius: float) -> None:
        """Diagonal stripes clipped to a rounded box: the "no goal" fill."""
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


# ---------------------------------------------------------------- shared parts


def _header(card: Card, data: Mapping[str, Any]) -> None:
    mark = _mark(38)
    if mark is not None:
        card.image.paste(mark, (_s(PAD), _s(32)), mark)
    card.text((PAD + 50, 51), "Kalchas", size=22, weight=800, anchor="lm")
    span = f" · {_week_span(data)}"
    span_w = card.width(span, size=16, weight=500)
    card.text((W - PAD, 51), span, size=16, weight=500, fill=INK2, anchor="rm")
    card.text((W - PAD - span_w, 51), "The week in signals", size=16, weight=700, anchor="rm")
    card.hline(84)


def _footer(card: Card, note: str) -> None:
    card.hline(H - 52)
    card.text((PAD, H - 26), note, size=16, weight=500, fill=INK2, anchor="lm")
    card.text((W - PAD, H - 26), "kalchas.live", size=16, weight=700, anchor="rm")


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


def _timeline(
    card: Card,
    box: tuple[float, float, float],
    *,
    signal: int,
    goal: int | None,
    height: float = 10,
) -> None:
    """A 0-90 bar: a tick where we posted, green to the goal, hatched if none came."""
    x0, x1, cy = box
    span = x1 - x0

    def at(minute: float) -> float:
        return x0 + span * max(0.0, min(minute, 90)) / 90

    top, bottom = cy - height / 2, cy + height / 2
    card.rect((x0, top, x1, bottom), fill=TRACK, radius=height / 2)
    half = at(45)
    card.draw.line([(_s(half), _s(top - 3)), (_s(half), _s(bottom + 3))], fill=MISS, width=_s(1))
    if goal is None:
        card.hatch((at(signal), top, x1, bottom), radius=height / 2)
    else:
        card.rect(
            (at(signal), top, max(at(goal), at(signal) + 8), bottom), fill=GOAL, radius=height / 2
        )
    card.rect((at(signal) - 1.5, top - 5, at(signal) + 1.5, bottom + 5), fill=INK, radius=1.5)
    if goal is not None:
        card.dot((at(goal), cy), 11, BG)
        card.dot((at(goal), cy), 8, GOAL)


# ---------------------------------------------------------------- cover


def _cover(data: Mapping[str, Any], texts: Mapping[str, Any]) -> Card:
    card = Card()
    _header(card, data)
    left, right = PAD, 460

    card.text((left, 112), "EVERY SIGNAL WE SENT", size=14, weight=700, fill=GOAL)
    settled = int(data["goals"]) + int(data["misses"])
    lead = f"{data['goals']} of {settled}"
    y = 138.0
    # A busy week ("273 of 516") is wider than the column: shrink to fit, never spill.
    natural = card.width(f"{lead} signals", size=50, weight=800) + 12
    size = min(50.0, 50.0 * 360 / natural)
    lead_w = card.text((left, y), lead, size=size, weight=800, fill=GOAL)
    card.text((left + lead_w + 12 * size / 50, y), "signals", size=size, weight=800)
    card.text((left, y + size * 1.02), "found a goal", size=size, weight=800)
    y = card.wrap(
        (left, y + size * 2.44),
        str(texts.get("cover_line") or ""),
        width=360,
        size=20,
        fill=INK2,
        max_lines=3,
    )

    facts = _facts(data)
    fy = max(y + 18, 440.0)
    for label, value in facts:
        card.hline(fy, left, left + 360)
        card.text((left, fy + 20), label, size=16, fill=INK2, anchor="lm")
        card.text((left + 360, fy + 20), value, size=16, weight=700, anchor="rm")
        fy += 40

    # How long until the goal
    card.text((right, 112), "How long until the goal", size=16, weight=700)
    card.text((W - PAD, 112), f"{data['total']} signals", size=14, fill=INK2, anchor="ra")
    waits = [(w["label"], int(w["count"]), True) for w in data.get("waits") or []]
    waits.append(("No goal", int(data["misses"]), False))
    most = max([n for _, n, _ in waits] + [1])
    bar_x0, bar_x1 = right + 134, W - PAD - 54
    by = 150.0
    for label, n, is_goal in waits:
        card.text(
            (right, by), label, size=15, weight=500, fill=INK if is_goal else MUTED, anchor="lm"
        )
        card.rect((bar_x0, by - 9, bar_x1, by + 9), fill=TRACK, radius=5)
        end = bar_x0 + (bar_x1 - bar_x0) * n / most
        if n:
            if is_goal:
                card.rect((bar_x0, by - 9, end, by + 9), fill=GOAL, radius=5)
            else:
                card.hatch((bar_x0, by - 9, end, by + 9), radius=5)
        card.text(
            (W - PAD, by), str(n), size=15, weight=700, fill=INK if is_goal else MUTED, anchor="rm"
        )
        by += 30
    if data["goals"]:
        say = f"{data['within_10']} of the {data['goals']} goals"
        say_w = card.text((right, by + 2), say, size=15, weight=700)
        card.text(
            (right + say_w + 5, by + 2), "came within 10 minutes of the signal.", size=15, fill=INK2
        )

    # Day by day
    dy = by + 46
    card.text((right, dy), "Day by day", size=16, weight=700)
    card.text((W - PAD, dy), "goals / signals", size=14, fill=INK2, anchor="ra")
    days = data.get("days") or []
    busiest = max([int(d["total"]) for d in days] + [1])
    col_w, col_h = 44.0, 104.0
    span = (W - PAD - right) / max(len(days), 1)
    top = dy + 32
    for index, day in enumerate(days):
        cx = right + span * index + span / 2
        x0, x1 = cx - col_w / 2, cx + col_w / 2
        card.rect((x0, top, x1, top + col_h), fill=TRACK, radius=6)
        goals, total = int(day["goals"]), int(day["total"])
        g_h = col_h * goals / busiest
        m_h = col_h * (total - goals) / busiest
        if m_h:
            card.hatch((x0, top + col_h - g_h - m_h, x1, top + col_h - g_h), radius=4)
        if g_h:
            card.rect((x0, top + col_h - g_h, x1, top + col_h), fill=GOAL, radius=6)
        card.text((cx, top + col_h + 8), f"{goals}/{total}", size=15, weight=700, anchor="ma")
        card.text((cx, top + col_h + 28), str(day["day"]), size=13, fill=MUTED, anchor="ma")

    _footer(card, "Every signal is posted live, before the goal.")
    return card


def _facts(data: Mapping[str, Any]) -> list[tuple[str, str]]:
    out = []
    if data.get("fastest") is not None:
        fastest = int(data["fastest"])
        out.append(
            (
                "Fastest goal",
                "Same minute as the signal"
                if fastest == 0
                else f"{_mins(fastest)} after the signal",
            )
        )
    if data.get("average_wait") is not None:
        out.append(("Average wait for a goal", f"{data['average_wait']} min"))
    worst = data.get("worst_day")
    if worst:
        out.append(
            ("Toughest day", f"{_day_name(worst['day'])}, {worst['goals']} of {worst['total']}")
        )
    return out


# ---------------------------------------------------------------- calls


def _calls(data: Mapping[str, Any], texts: Mapping[str, Any]) -> Card:
    card = Card()
    _header(card, data)
    calls: Sequence[Mapping[str, Any]] = data["calls"]
    stories: Sequence[str] = texts.get("calls") or []
    title = "Three we got right" if len(calls) == 3 else "What we got right"
    card.text((PAD, 108), title, size=40, weight=800)
    card.text(
        (W - PAD, 126),
        "The side we flagged scored, soon after the signal.",
        size=16,
        fill=INK2,
        anchor="rm",
    )

    col_w = (W - 2 * PAD) / len(calls)
    for index, call in enumerate(calls):
        x = PAD + col_w * index + (30 if index else 0)
        inner = col_w - (60 if index else 30)
        if index:
            card.vline(PAD + col_w * index, 180, H - 76)
        gap = int(call.get("gap") or 0)
        num_w = card.text((x, 182), f"{gap} min", size=50, weight=800, fill=GOAL)
        card.text((x + num_w + 10, 210), "from signal to goal", size=16, fill=INK2)
        _timeline(
            card, (x, x + inner, 268), signal=int(call["minute"]), goal=call.get("goal_minute")
        )
        when_w = card.text((x, 286), "Signal ", size=15, fill=INK2)
        when_w += card.text((x + when_w, 286), f"{call['minute']}'", size=15, weight=700)
        when_w += card.text((x + when_w, 286), "  →  Goal ", size=15, fill=INK2)
        card.text((x + when_w, 286), f"{call.get('goal_minute')}'", size=15, weight=700)
        y = card.wrap(
            (x, 322),
            f"{call['home']} v {call['away']}",
            width=inner,
            size=24,
            weight=700,
            leading=1.2,
            max_lines=2,
        )
        card.text((x, y + 2), str(call.get("league") or ""), size=14, fill=MUTED)
        story = stories[index] if index < len(stories) else ""
        card.wrap((x, y + 32), story, width=inner, size=18, leading=1.5, max_lines=6)

    _footer(card, str(texts.get("honourable") or "Every signal is posted live, before the goal."))
    return card


# ---------------------------------------------------------------- miss


def _miss(data: Mapping[str, Any], texts: Mapping[str, Any]) -> Card:
    card = Card()
    _header(card, data)
    miss: Mapping[str, Any] = data["miss"]
    left_w, right = 640.0, 752.0

    card.text((PAD, 112), "THE ONE THAT GOT AWAY", size=14, weight=700, fill=RED)
    y = card.wrap(
        (PAD, 136),
        f"{miss['home']} v {miss['away']}",
        width=left_w,
        size=42,
        weight=800,
        leading=1.12,
        max_lines=2,
    )
    meta = " · ".join(
        p for p in (miss.get("league"), f"Signal at {miss['minute']}'", "No goal") if p
    )
    card.text((PAD, y + 4), meta, size=16, fill=INK2)
    _timeline(card, (PAD, PAD + left_w, y + 46), signal=int(miss["minute"]), goal=None)
    y = card.wrap(
        (PAD, y + 68), str(texts.get("miss") or ""), width=left_w, size=20, leading=1.5, max_lines=5
    )
    lesson = str(texts.get("lesson") or "").strip()
    if lesson:
        lines = card.lines(lesson, width=left_w - 36, size=20, weight=700, max_lines=3)
        box_h = 48 + 27 * len(lines)
        top = min(y + 14, H - 70 - box_h)
        card.rect((PAD, top, PAD + left_w, top + box_h), fill=TRACK, radius=10)
        card.text((PAD + 18, top + 16), "WHAT WE LEARNED", size=12, weight=700, fill=INK2)
        for i, line in enumerate(lines):
            card.text((PAD + 18, top + 38 + 27 * i), line, size=20, weight=700)

    card.vline(right - 30, 112, H - 76)
    readout = _readout(miss)
    if readout:
        big, small = readout
        big_w = card.text((right, 106), big, size=60, weight=800)
        card.wrap(
            (right + big_w + 16, 118),
            f"{small} at {miss['minute']}'. Our most confident signal this week.",
            width=W - PAD - right - big_w - 16,
            size=15,
            fill=INK2,
            leading=1.35,
            max_lines=3,
        )
    _compare(card, miss, x0=right, x1=W - PAD, y=210)
    _footer(card, "We post the misses too.")
    return card


def _readout(miss: Mapping[str, Any]) -> tuple[str, str] | None:
    value = miss.get("value")
    keys = miss.get("strategies") or []
    for key in keys:
        if key in STRATEGY_READOUT and value is not None:
            fmt, label = STRATEGY_READOUT[key]
            return fmt.format(v=float(value)), label
    return None


def _compare(card: Card, miss: Mapping[str, Any], *, x0: float, x1: float, y: float) -> None:
    """FotMob-style head to head: value, label, value, and a bar split from the middle."""
    stats = miss.get("stats") or []
    if not stats:
        return
    card.hline(y - 14, x0, x1)
    card.text((x0, y), str(miss.get("team_name") or ""), size=14, weight=700)
    card.text(
        (x1, y), str(miss.get("other_name") or ""), size=14, weight=700, fill=INK2, anchor="ra"
    )
    mid = (x0 + x1) / 2
    row_y = y + 38
    for stat in stats[:5]:
        own, other = int(stat["own"]), int(stat["other"])
        unit = "%" if stat.get("percent") else ""
        card.text((x0, row_y), f"{own}{unit}", size=16, weight=700)
        card.text((mid, row_y), str(stat["label"]), size=15, fill=INK2, anchor="ma")
        card.text((x1, row_y), f"{other}{unit}", size=16, weight=700, anchor="ra")
        total = max(own + other, 1)
        by = row_y + 28
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
        row_y += 58


# ---------------------------------------------------------------- words


def _clean(value: str) -> str:
    # Manrope has no prime glyph; 76' is how most football graphics write it anyway.
    return str(value).replace("′", "'")


def _mins(gap: Any) -> str:
    n = int(gap or 0)
    return "1 min" if n == 1 else f"{n} min"


def _day_name(short: str) -> str:
    names = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday"}
    names |= {"Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}
    return names.get(short, short)


def _week_span(data: Mapping[str, Any]) -> str:
    first = date.fromisoformat(str(data["week_start"]))
    last = date.fromisoformat(str(data["week_end"]))
    return f"{first:%a} {first.day} {first:%b} – {last:%a} {last.day} {last:%b}"
