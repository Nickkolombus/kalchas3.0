"""Versus JPEG used by sendPhoto."""

from __future__ import annotations

from io import BytesIO

from kalchas_bot.banner import HEIGHT, WIDTH, _ellipsize, render_alert_photo
from PIL import Image, ImageDraw, ImageFont


def test_banner_is_sixteen_by_nine():
    buf = render_alert_photo(
        {
            "home_team": "Vizela",
            "away_team": "Sporting CP B",
            "minute": 69,
            "score": "0-2",
            "payload": {"league": "Segunda Liga", "status_short": "2H"},
        }
    )
    assert buf is not None
    assert buf.getvalue()[:2] == b"\xff\xd8"
    assert buf.name == "alert.jpg"
    img = Image.open(BytesIO(buf.getvalue()))
    assert img.size == (WIDTH, HEIGHT)
    assert img.size == (800, 450)
    assert WIDTH / HEIGHT == 16 / 9


def test_long_names_ellipsize_to_the_column():
    draw = ImageDraw.Draw(Image.new("RGB", (800, 450)))
    font = ImageFont.load_default()
    label = _ellipsize(draw, "Universitario de Vinto", font, 40)
    assert label.endswith("...")
    assert draw.textbbox((0, 0), label, font=font)[2] <= 40
