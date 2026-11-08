"""Thermal betshop parlay slip — PNG for admin share preview and posts.

Looks like a high-street receipt: narrow stock, monospace, dashed rules,
fixed illustrative stake of 10, a small Kalchas mark, and a dim diagonal
watermark across the whole slip. The style (Safer / Balanced / Bolder) is
explained in the post caption, not printed here.

Once the matches are played the same printed slip comes back marked up by hand
in blue ballpoint: a tick or a cross by each leg, void legs struck through, and
the total circled or crossed out (see ``ballpen``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from kalchas_bot.ballpen import Pen

Slot = Literal["today", "tomorrow", "nightly"]

PAPER = (242, 239, 230)
INK = (22, 22, 20)
MUTED = (90, 88, 82)
RULE = (160, 156, 148)
WIDTH = 540
PAD_X = 28
PAD_Y = 28
STAKE = 10.0
LOGO_PX = 80
SITE = "kalchas.live"
DISCLAIMER = "For research & football enthusiast purposes only"
WATERMARK_TEXT = "www.kalchas.live"
WATERMARK_ALPHA = 26

MARK_PATH = Path(__file__).parent / "assets" / "kalchas-mark.png"

_SLOT_TITLE = {
    "today": "TODAY",
    "tomorrow": "TOMORROW",
    "nightly": "NIGHTLY",
}

_MONO_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"),
)


def render_parlay_slip(
    legs: Sequence[Mapping[str, Any]],
    *,
    slot: Slot = "today",
    style: str = "balanced",
    day: str | None = None,
    settled: Mapping[str, str] | None = None,
    seed: str | None = None,
) -> bytes:
    """PNG bytes of the thermal slip.

    ``settled`` maps match_id to ``landed``, ``missed`` or ``void``; when given,
    the slip comes back marked in ballpoint. ``seed`` keeps the hand marks the
    same every time one slip is drawn. ``style`` is accepted for call-site
    symmetry; it is deliberately not printed.
    """
    del style
    lines = _layout(legs, slot=slot, day=day)
    height = PAD_Y * 2 + sum(block[0] for block in lines) + 8
    img = Image.new("RGB", (WIDTH, max(height, 200)), PAPER)
    logo = _logo()
    if logo is not None:
        img.paste(logo, ((WIDTH - LOGO_PX) // 2, PAD_Y), logo)
    draw = ImageDraw.Draw(img)
    y = PAD_Y
    where: dict[str, int] = {}
    for h, paint, tag in lines:
        paint(draw, y)
        if tag:
            where[tag] = y
        y += h
    img = _watermark(img)
    if settled:
        key = seed or "|".join(str(leg.get("match_id")) for leg in legs)
        img = _mark_up(img, legs, settled, where, seed=key)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=1)
def _logo() -> Image.Image | None:
    """The round Kalchas mark, cropped to its circle and dithered to ink dots."""
    if not MARK_PATH.is_file():
        return None
    mark = Image.open(MARK_PATH).convert("RGB")
    bbox = ImageOps.invert(mark.convert("L")).point(lambda v: 255 if v > 12 else 0).getbbox()
    if bbox:
        mark = mark.crop(bbox)
    grey = ImageOps.grayscale(mark).resize((LOGO_PX, LOGO_PX), Image.LANCZOS)
    grey = ImageEnhance.Contrast(ImageOps.equalize(grey)).enhance(1.4)
    grey = grey.point(lambda v: int(255 * (v / 255) ** 0.8))
    dots = grey.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    ink = ImageOps.invert(dots.convert("L"))
    circle = Image.new("L", (LOGO_PX * 4, LOGO_PX * 4), 0)
    ImageDraw.Draw(circle).ellipse((0, 0, LOGO_PX * 4 - 1, LOGO_PX * 4 - 1), fill=255)
    circle = circle.resize((LOGO_PX, LOGO_PX), Image.LANCZOS)
    alpha = Image.composite(ink, Image.new("L", ink.size, 0), circle)
    out = Image.new("RGBA", (LOGO_PX, LOGO_PX), (*INK, 0))
    out.putalpha(alpha)
    return out


def _watermark(img: Image.Image) -> Image.Image:
    """Dim KALCHAS text tiled across the whole slip at 45 degrees."""
    w, h = img.size
    side = int((w * w + h * h) ** 0.5) + 40
    layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    font = _font(22, bold=True)
    step_x = int(pen.textlength(WATERMARK_TEXT, font=font)) + 70
    step_y = 70
    for row, y in enumerate(range(0, side, step_y)):
        offset = (step_x // 2) if row % 2 else 0
        for x in range(-step_x + offset, side, step_x):
            pen.text((x, y), WATERMARK_TEXT, font=font, fill=(*INK, WATERMARK_ALPHA))
    layer = layer.rotate(45, resample=Image.BICUBIC)
    left = (side - w) // 2
    top = (side - h) // 2
    layer = layer.crop((left, top, left + w, top + h))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    if bold:
        bold_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")
        if bold_path.is_file():
            return ImageFont.truetype(str(bold_path), size)
    for path in _MONO_CANDIDATES:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _dash(draw: ImageDraw.ImageDraw, y: int) -> None:
    x = PAD_X
    while x < WIDTH - PAD_X:
        draw.line((x, y, min(x + 6, WIDTH - PAD_X), y), fill=RULE, width=1)
        x += 10


def _fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    out = text
    while out and draw.textlength(out + ell, font=font) > max_w:
        out = out[:-1]
    return (out + ell) if out else ell


def _layout(
    legs: Sequence[Mapping[str, Any]],
    *,
    slot: Slot,
    day: str | None,
) -> list[tuple[int, Any, str | None]]:
    title_f = _font(18, bold=True)
    sub_f = _font(11)
    body_f = _font(13)
    small_f = _font(11)
    big_f = _font(16, bold=True)

    product = 1.0
    for leg in legs:
        product *= float(leg.get("price") or 1)
    # Same arithmetic as the page and the caption: round only for display.
    combined = round(product, 2)
    returns = round(STAKE * product, 2)
    day_label = _day_label(day)
    slot_label = _SLOT_TITLE.get(slot, "TODAY")
    blocks: list[tuple[int, Any, str | None]] = []

    top = LOGO_PX + 8

    def header(draw: ImageDraw.ImageDraw, y: int) -> None:
        y += top
        draw.text((WIDTH / 2, y), "KALCHAS", font=title_f, fill=INK, anchor="mt")
        draw.text(
            (WIDTH / 2, y + 24), "LIVE MATCH INTELLIGENCE", font=sub_f, fill=MUTED, anchor="mt"
        )
        draw.text(
            (WIDTH / 2, y + 42),
            f"BETTING SLIP · {slot_label} · {len(legs)} LEGS",
            font=sub_f,
            fill=MUTED,
            anchor="mt",
        )
        if slot == "nightly":
            draw.text((WIDTH / 2, y + 58), "00:00–07:00 GMT+3", font=sub_f, fill=MUTED, anchor="mt")

    blocks.append((top + (72 if slot == "nightly" else 58), header, None))

    def rule1(draw: ImageDraw.ImageDraw, y: int) -> None:
        _dash(draw, y + 4)

    blocks.append((14, rule1, None))

    def meta(draw: ImageDraw.ImageDraw, y: int) -> None:
        draw.text((PAD_X, y), day_label, font=small_f, fill=MUTED)
        stake = f"STAKE {STAKE:.2f}"
        draw.text((WIDTH - PAD_X, y), stake, font=small_f, fill=MUTED, anchor="rt")

    blocks.append((18, meta, None))
    blocks.append((14, rule1, None))

    for i, leg in enumerate(legs, start=1):
        mid = str(leg.get("match_id") or "")
        home = (leg.get("home") or {}).get("name") if isinstance(leg.get("home"), Mapping) else ""
        away = (leg.get("away") or {}).get("name") if isinstance(leg.get("away"), Mapping) else ""
        if not home and not away:
            # API may already flatten, or tests pass plain strings via label only.
            home = str(leg.get("home_name") or "")
            away = str(leg.get("away_name") or "")
        if home or away:
            match = f"{home} v {away}"
        else:
            match = str(leg.get("match") or mid)
        market = str(leg.get("label") or leg.get("market") or "")
        price = float(leg.get("price") or 0)
        kick = _kick_hm(str(leg.get("kickoff") or ""))

        def leg_paint(
            draw: ImageDraw.ImageDraw,
            y: int,
            *,
            n: int = i,
            match_name: str = match,
            px: float = price,
            kick_s: str = kick,
            market_s: str = market,
        ) -> None:
            left = f"{n:02d}  {_fit(draw, match_name, body_f, WIDTH - PAD_X * 2 - 56)}"
            draw.text((PAD_X, y), left, font=body_f, fill=INK)
            draw.text((WIDTH - PAD_X, y), f"{px:.2f}", font=body_f, fill=INK, anchor="rt")
            detail = f"{kick_s} · {market_s}" if kick_s else market_s
            draw.text(
                (PAD_X + 28, y + 18),
                _fit(draw, detail, small_f, WIDTH - PAD_X * 2 - 28),
                font=small_f,
                fill=MUTED,
            )

        blocks.append((40, leg_paint, f"leg:{mid}"))

    blocks.append((14, rule1, None))

    def totals(draw: ImageDraw.ImageDraw, y: int) -> None:
        draw.text((PAD_X, y), "COMBINED", font=big_f, fill=INK)
        draw.text((WIDTH - PAD_X, y), f"{combined:.2f}", font=big_f, fill=INK, anchor="rt")
        draw.text((PAD_X, y + 24), "RETURNS", font=body_f, fill=MUTED)
        draw.text((WIDTH - PAD_X, y + 24), f"{returns:.2f}", font=big_f, fill=INK, anchor="rt")

    blocks.append((48, totals, "totals"))
    blocks.append((14, rule1, None))

    def footer(draw: ImageDraw.ImageDraw, y: int) -> None:
        draw.text((WIDTH / 2, y), SITE, font=body_f, fill=INK, anchor="mt")
        draw.text((WIDTH / 2, y + 18), DISCLAIMER, font=small_f, fill=MUTED, anchor="mt")

    blocks.append((40, footer, "footer"))
    return blocks


def _mark_up(
    img: Image.Image,
    legs: Sequence[Mapping[str, Any]],
    settled: Mapping[str, str],
    where: Mapping[str, int],
    *,
    seed: str,
) -> Image.Image:
    """The checker's pass over a played slip, in blue ballpoint."""
    pen = Pen(img.size, seed)
    probe = ImageDraw.Draw(img)
    body_f, big_f = _font(13), _font(16, bold=True)
    right = WIDTH - PAD_X

    missed_n: list[int] = []
    voids = 0
    for i, leg in enumerate(legs, start=1):
        mid = str(leg.get("match_id") or "")
        y = where.get(f"leg:{mid}")
        state = settled.get(mid)
        if y is None or state is None:
            continue
        price_w = probe.textlength(f"{float(leg.get('price') or 0):.2f}", font=body_f)
        if state == "landed":
            pen.tick(15, y + 9, size=22)
        elif state == "missed":
            missed_n.append(i)
            pen.cross(14, y + 9, size=17)
            pen.strike(PAD_X + 26, right - price_w - 10, y + 8, wavy=True)
        elif state == "void":
            voids += 1
            pen.strike(PAD_X - 4, right + 4, y + 8)
            pen.write((right - 2, y + 25), "void", size=24, anchor="rm", tilt=5)

    # The total is only marked once every leg is: a half-checked slip has no verdict.
    total_y = where.get("totals")
    every = all(str(leg.get("match_id")) in settled for leg in legs)
    if total_y is not None and every:
        live = [leg for leg in legs if settled.get(str(leg.get("match_id"))) != "void"]
        combined = 1.0
        for leg in live:
            combined *= float(leg.get("price") or 1)
        returns = STAKE * combined
        old = probe.textbbox(
            (right, total_y + 24), f"{_printed_returns(legs):.2f}", font=big_f, anchor="rt"
        )
        old_odds = probe.textbbox(
            (right, total_y), f"{_printed_combined(legs):.2f}", font=big_f, anchor="rt"
        )
        middle = (PAD_X + 120 + old[0]) / 2
        if voids and live:
            # Voided legs pay at evens: the odds and returns get rewritten by hand.
            pen.strike(old_odds[0] - 4, old_odds[2] + 4, (old_odds[1] + old_odds[3]) / 2 + 1)
            pen.write(
                (old_odds[0] - 10, total_y + 9), f"{combined:.2f}", size=28, anchor="rm", tilt=3
            )
        if missed_n:
            pen.strike(old[0] - 6, old[2] + 6, (old[1] + old[3]) / 2 + 1)
            legs_word = "leg" if len(missed_n) == 1 else "legs"
            nums = ", ".join(str(n) for n in missed_n[:-1])
            nums = f"{nums} & {missed_n[-1]}" if nums else str(missed_n[-1])
            pen.write(
                (middle, total_y + 36), f"lost · {legs_word} {nums}", size=27, anchor="mm", tilt=4
            )
        elif live:
            if voids:
                # Strike the printed total and write the real one beside it, ringed.
                pen.strike(old[0] - 4, old[2] + 4, (old[1] + old[3]) / 2 + 1)
                new = f"{returns:.2f}"
                end = old[0] - 22
                width = pen.text_width(new, 28)
                pen.write((end, total_y + 33), new, size=28, anchor="rm", tilt=3)
                ring = (end - width, old[1] - 1, end, old[3] + 3)
                middle = (PAD_X + 110 + ring[0]) / 2
            else:
                ring = old
            pen.ring(ring)
            pen.write((middle - 6, total_y + 34), "came in!", size=30, anchor="mm", tilt=6)
        else:
            pen.write((middle, total_y + 34), "all void", size=28, anchor="mm", tilt=4)

    foot = where.get("footer")
    if foot is not None and every:
        pen.write((PAD_X - 6, foot + 4), "checked", size=20, anchor="lt", tilt=8)
    return pen.apply(img)


def _product(legs: Sequence[Mapping[str, Any]]) -> float:
    total = 1.0
    for leg in legs:
        total *= float(leg.get("price") or 1)
    return total


def _printed_combined(legs: Sequence[Mapping[str, Any]]) -> float:
    return round(_product(legs), 2)


def _printed_returns(legs: Sequence[Mapping[str, Any]]) -> float:
    return round(STAKE * _product(legs), 2)


def _day_label(day: str | None) -> str:
    if not day:
        return datetime.now().strftime("%d %b %Y").upper()
    try:
        return datetime.strptime(day, "%Y-%m-%d").strftime("%d %b %Y").upper()
    except ValueError:
        return day.upper()


def _kick_hm(kickoff: str) -> str:
    raw = (kickoff or "").strip()
    if not raw:
        return ""
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:5]
    return when.strftime("%H:%M")
