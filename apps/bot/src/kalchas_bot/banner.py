"""Versus JPEG for Telegram sendPhoto.

520x168 (~3.1:1) is cropped on mobile Telegram, which clips crests and
names at the sides. 16:9 fills the chat photo bubble without that crop.

Identity only: crests, names, score, clock, country and league. Every
number that explains a fire stays in the caption.
"""

from __future__ import annotations

import colorsys
import json
import logging
from collections import Counter
from collections.abc import Mapping
from io import BytesIO
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

logger = logging.getLogger("kalchas.bot.banner")

WIDTH = 800
HEIGHT = 450
BG = (11, 28, 51)
BG_TOP = (16, 37, 64)
CREAM = (243, 234, 210)
MUTED = (139, 154, 171)
NEUTRAL_GLOW = (70, 104, 146)
GLOW_LUMA = 100.0  # every glow is moved to this brightness, whatever its hue
CREST = 180  # 112 * 1.6; names stay the same size
PAD_X = 52
# The feed's code for cross-border competitions; the league name says enough.
_NO_COUNTRY = {"intl", "world", "international"}
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
        country = _country_label(payload.get("country"), league)
        home_logo = str(payload.get("home_logo") or "")
        away_logo = str(payload.get("away_logo") or "")

        left, left_glow = _crest(home_logo, home)
        right, right_glow = _crest(away_logo, away)

        title_font = _font(18, bold=False)
        country_font = _font(18, bold=True)
        score_font = _font(64, bold=False)
        name_font = _font(22, bold=False)
        clock_font = _font(20, bold=False)

        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        league_h = 0
        if league or country:
            lb = probe.textbbox((0, 0), league or country, font=title_font)
            league_h = (lb[3] - lb[1]) + 18

        name_h = 28
        crest_gap = 16
        block_h = league_h + CREST + crest_gap + name_h
        y = max(PAD_X // 2, int((HEIGHT - block_h) / 2))
        left_x = PAD_X
        right_x = WIDTH - PAD_X - CREST
        crest_y = y + league_h
        mid = WIDTH / 2

        img = _backdrop(
            (left_x + CREST / 2, crest_y + CREST / 2, left_glow),
            (right_x + CREST / 2, crest_y + CREST / 2, right_glow),
            centre=(mid, crest_y + CREST / 2),
            header_y=y if (league or country) else crest_y,
        )
        draw = ImageDraw.Draw(img)

        if league or country:
            _header(draw, country, league, y, country_font, title_font)
        y = crest_y

        img.paste(left, (left_x, y), left)
        img.paste(right, (right_x, y), right)

        sb = draw.textbbox((0, 0), score, font=score_font)
        score_w = sb[2] - sb[0]
        clock_box = draw.textbbox((0, 0), clock, font=clock_font) if clock else (0, 0, 0, 0)
        score_h = sb[3] - sb[1]
        clock_h = (clock_box[3] - clock_box[1] + 8) if clock else 0
        block = score_h + clock_h
        score_y = y + max(0, (CREST - block) / 2) - sb[1]
        draw.text((mid - score_w / 2, score_y), score, font=score_font, fill=CREAM)
        if clock:
            draw.text(
                (mid - (clock_box[2] - clock_box[0]) / 2, score_y + sb[3] + 6),
                clock,
                font=clock_font,
                fill=MUTED,
            )

        name_y = y + CREST + crest_gap
        name_max = int(WIDTH / 2 - PAD_X - 16)
        _fitted(draw, home, left_x + CREST / 2, name_y, name_font, CREAM, name_max)
        _fitted(draw, away, right_x + CREST / 2, name_y, name_font, CREAM, name_max)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=95, subsampling=0, optimize=True)
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


def _country_label(raw: object, league: str) -> str:
    """Upper-case country, or "" when it adds nothing to the league name."""
    country = str(raw or "").strip()
    if not country or country.lower() in _NO_COUNTRY:
        return ""
    country = country.upper()
    return "" if country in league else country


def _header(
    draw: ImageDraw.ImageDraw,
    country: str,
    league: str,
    y: float,
    country_font: ImageFont.ImageFont,
    league_font: ImageFont.ImageFont,
) -> None:
    """ "COUNTRY · LEAGUE" centred, country in cream, league muted."""
    room = WIDTH - 2 * PAD_X
    lead = f"{country}  ·  " if country and league else country
    lead_w = draw.textlength(lead, font=country_font) if lead else 0
    tail = _ellipsize(draw, league, league_font, int(room - lead_w)) if league else ""
    total = lead_w + (draw.textlength(tail, font=league_font) if tail else 0)
    x = (WIDTH - total) / 2
    if lead:
        draw.text((x, y), lead, font=country_font, fill=CREAM)
    if tail:
        draw.text((x + lead_w, y), tail, font=league_font, fill=MUTED)


def _backdrop(
    *glows: tuple[float, float, tuple[int, int, int] | None],
    centre: tuple[float, float],
    header_y: float,
) -> Image.Image:
    """Navy gradient, a soft team-colour glow behind each crest, faint pitch lines.

    The halfway line stops short of the header so it never strikes through it.
    """
    column = Image.linear_gradient("L").resize((1, HEIGHT))
    img = Image.composite(
        Image.new("RGB", (1, HEIGHT), BG),
        Image.new("RGB", (1, HEIGHT), BG_TOP),
        column,
    ).resize((WIDTH, HEIGHT))

    light = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    paint = ImageDraw.Draw(light)
    for cx, cy, colour in glows:
        tint = _even_glow(colour or NEUTRAL_GLOW)
        r = CREST * 0.82
        paint.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*tint, 92))
    light = light.filter(ImageFilter.GaussianBlur(62))
    img = Image.alpha_composite(img.convert("RGBA"), light)

    lines = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    pen = ImageDraw.Draw(lines)
    ink = (*CREAM, 16)
    cx, cy = centre
    ring = 96
    pen.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=ink, width=2)
    if header_y - 14 > 0:
        pen.line((cx, 0, cx, header_y - 14), fill=ink, width=2)
    pen.line((cx, cy + ring, cx, HEIGHT), fill=ink, width=2)
    return Image.alpha_composite(img, lines).convert("RGB")


def _luma(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _even_glow(colour: tuple[int, int, int]) -> tuple[int, int, int]:
    """Same hue, brightness moved to GLOW_LUMA so yellow and navy glow alike."""
    h, _, s = colorsys.rgb_to_hls(*(c / 255 for c in colour))
    s = min(s, 0.8)
    lo, hi = 0.0, 1.0
    rgb = colour
    for _ in range(18):
        mid = (lo + hi) / 2
        rgb = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, mid, s))
        if _luma(rgb) < GLOW_LUMA:
            lo = mid
        else:
            hi = mid
    return rgb  # type: ignore[return-value]


def _crest(url: str, name: str) -> tuple[Image.Image, tuple[int, int, int] | None]:
    """Crest on a transparent square, plus its dominant colour for the glow."""
    raw = _fetch(url) if url.startswith("http") else None
    if raw is not None:
        try:
            logo = _fit_logo(Image.open(BytesIO(raw)), CREST)
            return logo, _team_colour(logo)
        except Exception:  # noqa: BLE001 - fall through to letter badge
            logger.debug("crest decode failed for %s", name)
    return _letter_badge(name), None


def _fit_logo(src: Image.Image, size: int) -> Image.Image:
    """Fill the crest box, keeping transparency so the glow shows around it."""
    src = _clear_flat_background(src.convert("RGBA"))
    # Premultiplied while resampling, so clear edges do not pick up dark fringes.
    hi = ImageOps.contain(src.convert("RGBa"), (size * 2, size * 2), Image.Resampling.LANCZOS)
    if min(src.width, src.height) < size:
        hi = hi.filter(ImageFilter.GaussianBlur(0.55))
    fitted = hi.resize(
        (max(1, round(hi.width / 2)), max(1, round(hi.height / 2))),
        Image.Resampling.LANCZOS,
    ).convert("RGBA")
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(
        fitted,
        ((size - fitted.width) // 2, (size - fitted.height) // 2),
    )
    return canvas


def _clear_flat_background(src: Image.Image) -> Image.Image:
    """Drop the white square some feed badges ship with (JPEGs, no alpha).

    Only when all four corners are opaque and near-white: flood from each
    corner, then pull the alpha in a pixel to lose the JPEG halo.
    """
    w, h = src.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    pixels = [src.getpixel(xy) for xy in corners]
    if not all(p[3] > 250 and min(p[:3]) > 215 for p in pixels):
        return src
    out = src.copy()
    for xy in corners:
        if out.getpixel(xy)[3]:
            ImageDraw.floodfill(out, xy, (255, 255, 255, 0), thresh=48)
    alpha = out.getchannel("A").filter(ImageFilter.MinFilter(3))
    out.putalpha(alpha.filter(ImageFilter.GaussianBlur(0.6)))
    return out


def _team_colour(logo: Image.Image) -> tuple[int, int, int] | None:
    """Most common saturated colour in the crest, or None for white/black/grey crests."""
    small = logo.resize((48, 48), Image.Resampling.BILINEAR)
    buckets: Counter[tuple[int, int, int]] = Counter()
    sums: dict[tuple[int, int, int], list[int]] = {}
    opaque = 0
    for r, g, b, a in small.get_flattened_data():
        if a < 200:
            continue
        opaque += 1
        _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.35 or v < 0.25:
            continue
        key = (r // 32, g // 32, b // 32)
        buckets[key] += 1
        acc = sums.setdefault(key, [0, 0, 0])
        acc[0] += r
        acc[1] += g
        acc[2] += b
    if not buckets:
        return None
    key, count = buckets.most_common(1)[0]
    if count < opaque * 0.04:
        return None
    r, g, b = sums[key]
    return (r // count, g // count, b // count)


def _letter_badge(name: str) -> Image.Image:
    canvas = Image.new("RGBA", (CREST, CREST), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    radius = max(8, round(CREST * 28 / 112))
    draw.rounded_rectangle((0, 0, CREST - 1, CREST - 1), radius=radius, fill=(24, 48, 78))
    letter = (name.strip()[:1] or "?").upper()
    font = _font(max(24, round(CREST * 56 / 112)), bold=True)
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
