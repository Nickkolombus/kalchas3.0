"""Versus JPEG used by sendPhoto."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from kalchas_bot.banner import HEIGHT, WIDTH, render_alert_photo


def test_banner_renders_without_crests():
    buf = render_alert_photo(
        {
            "home_team": "Patriotas",
            "away_team": "Boca Juniors",
            "minute": 45,
            "score": "1-2",
            "payload": {"league": "Primera B", "status_short": "1H"},
        }
    )
    assert buf is not None
    assert buf.getvalue()[:2] == b"\xff\xd8"
    assert buf.name == "alert.jpg"
    img = Image.open(BytesIO(buf.getvalue()))
    assert img.size == (WIDTH, HEIGHT)
    assert img.size == (520, 168)
