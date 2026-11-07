"""Thermal betshop parlay slip — PNG for admin share preview and posts.

Looks like a high-street receipt: narrow stock, monospace, dashed rules,
fixed illustrative stake of 10, a small Kalchas mark, and a dim diagonal
watermark across the whole slip. The style (Safer / Balanced / Bolder) is
explained in the post caption, not printed here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

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
) -> bytes:
    """PNG bytes of the thermal slip. ``settled`` maps match_id → landed|missed.

    ``style`` is accepted for call-site symmetry; it is deliberately not printed.
    """
    del style
    results = settled or {}
    lines = _layout(legs, slot=slot, day=day, settled=results)
    height = PAD_Y * 2 + sum(block[0] for block in lines) + 8
    img = Image.new("RGB", (WIDTH, max(height, 200)), PAPER)
    logo = _logo()
    if logo is not None:
        img.paste(logo, ((WIDTH - LOGO_PX) // 2, PAD_Y), logo)
    draw = ImageDraw.Draw(img)
    y = PAD_Y
    for h, paint in lines:
        paint(draw, y)
        y += h
    img = _watermark(img)
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
    settled: Mapping[str, str],
) -> list[tuple[int, Any]]:
    title_f = _font(18, bold=True)
    sub_f = _font(11)
    body_f = _font(13)
    small_f = _font(11)
    big_f = _font(16, bold=True)

    combined = 1.0
    for leg in legs:
        combined *= float(leg.get("price") or 1)
    combined = round(combined, 2)
    returns = round(STAKE * combined, 2)
    day_label = _day_label(day)
    slot_label = _SLOT_TITLE.get(slot, "TODAY")
    lost = next((mid for mid, out in settled.items() if out == "missed"), None)
    won = (
        bool(settled)
        and all(out == "landed" for out in settled.values())
        and len(settled) == len(legs)
    )

    blocks: list[tuple[int, Any]] = []

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

    blocks.append((top + (72 if slot == "nightly" else 58), header))

    def rule1(draw: ImageDraw.ImageDraw, y: int) -> None:
        _dash(draw, y + 4)

    blocks.append((14, rule1))

    def meta(draw: ImageDraw.ImageDraw, y: int) -> None:
        draw.text((PAD_X, y), day_label, font=small_f, fill=MUTED)
        stake = f"STAKE {STAKE:.2f}"
        draw.text((WIDTH - PAD_X, y), stake, font=small_f, fill=MUTED, anchor="rt")

    blocks.append((18, meta))
    blocks.append((14, rule1))

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
        outcome = settled.get(mid)
        outcome_bit = ""
        if outcome == "landed":
            outcome_bit = " · LANDED"
        elif outcome == "missed":
            outcome_bit = " · MISSED"

        def leg_paint(
            draw: ImageDraw.ImageDraw,
            y: int,
            *,
            n: int = i,
            match_name: str = match,
            px: float = price,
            kick_s: str = kick,
            market_s: str = market,
            bit: str = outcome_bit,
        ) -> None:
            left = f"{n:02d}  {_fit(draw, match_name, body_f, WIDTH - PAD_X * 2 - 56)}"
            draw.text((PAD_X, y), left, font=body_f, fill=INK)
            draw.text((WIDTH - PAD_X, y), f"{px:.2f}", font=body_f, fill=INK, anchor="rt")
            detail = f"{kick_s} · {market_s}{bit}" if kick_s else f"{market_s}{bit}"
            draw.text(
                (PAD_X + 28, y + 18),
                _fit(draw, detail, small_f, WIDTH - PAD_X * 2 - 28),
                font=small_f,
                fill=MUTED,
            )

        blocks.append((40, leg_paint))

    blocks.append((14, rule1))

    def totals(draw: ImageDraw.ImageDraw, y: int) -> None:
        draw.text((PAD_X, y), "COMBINED", font=big_f, fill=INK)
        draw.text((WIDTH - PAD_X, y), f"{combined:.2f}", font=big_f, fill=INK, anchor="rt")
        draw.text((PAD_X, y + 24), "RETURNS", font=body_f, fill=MUTED)
        draw.text((WIDTH - PAD_X, y + 24), f"{returns:.2f}", font=big_f, fill=INK, anchor="rt")

    blocks.append((48, totals))

    if settled:
        blocks.append((14, rule1))

        def banner(draw: ImageDraw.ImageDraw, y: int) -> None:
            if won:
                text = "*** CAME IN ***"
            elif lost:
                # Find leg number for the miss.
                num = next(
                    (
                        idx
                        for idx, leg in enumerate(legs, start=1)
                        if str(leg.get("match_id")) == lost
                    ),
                    0,
                )
                text = f"*** LOST · LEG {num:02d} ***" if num else "*** LOST ***"
            else:
                text = "*** SETTLED ***"
            draw.text((WIDTH / 2, y + 4), text, font=big_f, fill=INK, anchor="mt")

        blocks.append((28, banner))

    blocks.append((14, rule1))

    def footer(draw: ImageDraw.ImageDraw, y: int) -> None:
        draw.text((WIDTH / 2, y), SITE, font=body_f, fill=INK, anchor="mt")
        draw.text((WIDTH / 2, y + 18), DISCLAIMER, font=small_f, fill=MUTED, anchor="mt")

    blocks.append((40, footer))
    return blocks


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
