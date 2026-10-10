"""Versus JPEG for Telegram sendPhoto.

520x168 (~3.1:1) is cropped on mobile Telegram, which clips crests and
names at the sides. 16:9 fills the chat photo bubble without that crop.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from io import BytesIO
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("kalchas.bot.banner")

WIDTH = 800
HEIGHT = 450
BG = (11, 28, 51)
CREAM = (243, 234, 210)
MUTED = (139, 154, 171)
CREST = 112
PAD_X = 52
_FONT_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\segoeui.ttf",
)
_FONT_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "C:\\Windows\\Fonts\\segoeuib.ttf",
)


def render_alert_photo(row: Mapping[str, Any]) -> BytesIO | None:
    """Build a 16:9 versus card, or None if Pillow cannot draw it."""
    try:
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload) if payload.strip() else {}
        if not isinstance(payload, Mapping):
            payload = {}
        home = str(row.get("home_team") or payload.get("home") or "Home")
        away = str(row.get("away_team") or payload.get("away") or "Away")
        score = str(row.get("score") or "").replace("–", "-") or "0-0"
        minute = row.get("minute")
        try:
            clock = f"{int(minute)}'"
        except (TypeError, ValueError):
            clock = f"{minute}'" if minute not in (None, "") else ""
        status = str(payload.get("status_short") or "").strip()
        if status:
            clock = f"{clock} {status}".strip()
        league = str(payload.get("league") or "").strip().upper()
        home_logo = str(payload.get("home_logo") or "")
        away_logo = str(payload.get("away_logo") or "")

        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)
        title_font = _font(18, bold=False)
        score_font = _font(64, bold=True)
        name_font = _font(22, bold=False)
        clock_font = _font(20, bold=False)

        league_h = 0
        if league:
            lb = draw.textbbox((0, 0), league, font=title_font)
            league_h = (lb[3] - lb[1]) + 18

        name_h = 28
        block_h = league_h + CREST + 14 + name_h
        y = max(PAD_X // 2, int((HEIGHT - block_h) / 2))

        if league:
            bbox = draw.textbbox((0, 0), league, font=title_font)
            draw.text(
                ((WIDTH - (bbox[2] - bbox[0])) / 2, y),
                league,
                font=title_font,
                fill=MUTED,
            )
            y += league_h

        left = _crest(home_logo, home)
        right = _crest(away_logo, away)
        left_x = PAD_X
        right_x = WIDTH - PAD_X - CREST
        img.paste(left, (left_x, y), left)
        img.paste(right, (right_x, y), right)

        sb = draw.textbbox((0, 0), score, font=score_font)
        score_w = sb[2] - sb[0]
        clock_box = (
            draw.textbbox((0, 0), clock, font=clock_font) if clock else (0, 0, 0, 0)
        )
        score_h = sb[3] - sb[1]
        clock_h = (clock_box[3] - clock_box[1] + 8) if clock else 0
        block = score_h + clock_h
        score_y = y + max(0, (CREST - block) / 2) - sb[1]
        mid = WIDTH / 2
        draw.text((mid - score_w / 2, score_y), score, font=score_font, fill=CREAM)
        if clock:
            draw.text(
                (mid - (clock_box[2] - clock_box[0]) / 2, score_y + sb[3] + 6),
                clock,
                font=clock_font,
                fill=MUTED,
            )

        name_y = y + CREST + 12
        name_max = int(WIDTH / 2 - PAD_X - 16)
        _fitted(draw, home, left_x + CREST / 2, name_y, name_font, CREAM, name_max)
        _fitted(draw, away, right_x + CREST / 2, name_y, name_font, CREAM, name_max)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        buf.seek(0)
        buf.name = "alert.jpg"
        return buf
    except Exception:
        logger.exception("versus banner failed")
        return None


def _font(size: int, *, bold: bool) -> ImageFont.ImageFont:
    paths = _FONT_BOLD if bold else _FONT_REGULAR
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    if bold:
        return _font(size, bold=False)
    return ImageFont.load_default()


def _fitted(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: float,
    y: float,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    max_width: int,
) -> None:
    label = _ellipsize(draw, text, font, max_width)
    bbox = draw.textbbox((0, 0), label, font=font)
    draw.text((cx - (bbox[2] - bbox[0]) / 2, y), label, font=font, fill=fill)


def _ellipsize(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> str:
    if max_width <= 0:
        return text
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    stem = text
    while len(stem) > 1:
        stem = stem[:-1]
        label = stem.rstrip() + "..."
        if draw.textbbox((0, 0), label, font=font)[2] <= max_width:
            return label
    return "..."


def _crest(url: str, name: str) -> Image.Image:
    raw = _fetch(url) if url.startswith("http") else None
    if raw is not None:
        try:
            crest = Image.open(BytesIO(raw)).convert("RGBA")
            crest.thumbnail((CREST, CREST), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (CREST, CREST), (0, 0, 0, 0))
            canvas.paste(
                crest,
                ((CREST - crest.width) // 2, (CREST - crest.height) // 2),
                crest,
            )
            return canvas
        except Exception:  # noqa: BLE001 - fall through to letter badge
            logger.debug("crest decode failed for %s", name)
    return _letter_badge(name)


def _letter_badge(name: str) -> Image.Image:
    canvas = Image.new("RGBA", (CREST, CREST), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, CREST - 1, CREST - 1), radius=28, fill=(24, 48, 78))
    letter = (name.strip()[:1] or "?").upper()
    font = _font(56, bold=True)
    bbox = draw.textbbox((0, 0), letter, font=font)
    draw.text(
        ((CREST - (bbox[2] - bbox[0])) / 2, (CREST - (bbox[3] - bbox[1])) / 2 - 4),
        letter,
        font=font,
        fill=CREAM,
    )
    return canvas


def _fetch(url: str) -> bytes | None:
    try:
        req = Request(  # noqa: S310 - HTTPS team badges from the football feed
            url,
            headers={"User-Agent": "Kalchas/3.0"},
        )
        with urlopen(req, timeout=4) as resp:  # noqa: S310
            data = resp.read(400_000)
        return data or None
    except Exception:  # noqa: BLE001
        return None
