"""Versus header JPEG for Telegram sendPhoto."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from io import BytesIO
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("kalchas.bot.banner")

WIDTH = 520
HEIGHT = 168
BG = (11, 28, 51)
CREAM = (243, 234, 210)
MUTED = (139, 154, 171)
CREST = 80
PAD_X = 24
PAD_Y = 10
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\segoeui.ttf",
)


def render_alert_photo(row: Mapping[str, Any]) -> BytesIO | None:
    """Build a compact versus card, or None if Pillow cannot draw it."""
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
        title_font = _font(16)
        score_font = _font(48)
        name_font = _font(20)
        clock_font = _font(16)

        y = PAD_Y
        if league:
            bbox = draw.textbbox((0, 0), league, font=title_font)
            draw.text(
                ((WIDTH - (bbox[2] - bbox[0])) / 2, y),
                league,
                font=title_font,
                fill=MUTED,
            )
            y += (bbox[3] - bbox[1]) + 10

        left = _crest(home_logo, home)
        right = _crest(away_logo, away)
        sb = draw.textbbox((0, 0), score, font=score_font)
        score_w = sb[2] - sb[0]
        mid = WIDTH / 2
        left_x = PAD_X
        right_x = WIDTH - PAD_X - CREST
        img.paste(left, (left_x, y), left)
        img.paste(right, (right_x, y), right)

        clock_box = (
            draw.textbbox((0, 0), clock, font=clock_font) if clock else (0, 0, 0, 0)
        )
        score_h = sb[3] - sb[1]
        clock_h = (clock_box[3] - clock_box[1] + 8) if clock else 0
        block_h = score_h + clock_h
        score_y = y + max(0, (CREST - block_h) / 2) - sb[1]
        draw.text(
            (mid - score_w / 2, score_y),
            score,
            font=score_font,
            fill=CREAM,
        )
        if clock:
            draw.text(
                (mid - (clock_box[2] - clock_box[0]) / 2, score_y + sb[3] + 6),
                clock,
                font=clock_font,
                fill=MUTED,
            )

        name_y = y + CREST + 8
        _centered(draw, home, left_x + CREST / 2, name_y, name_font, CREAM)
        _centered(draw, away, right_x + CREST / 2, name_y, name_font, CREAM)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=88)
        buf.seek(0)
        buf.name = "alert.jpg"
        return buf
    except Exception:
        logger.exception("versus banner failed")
        return None


def _font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: float,
    y: float,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    label = text if len(text) <= 18 else text[:17] + "..."
    bbox = draw.textbbox((0, 0), label, font=font)
    draw.text((cx - (bbox[2] - bbox[0]) / 2, y), label, font=font, fill=fill)


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
    draw.rounded_rectangle((0, 0, CREST - 1, CREST - 1), radius=24, fill=(24, 48, 78))
    letter = (name.strip()[:1] or "?").upper()
    font = _font(48)
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
