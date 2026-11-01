"""Versus JPEG used by sendPhoto."""

from __future__ import annotations

from io import BytesIO

from kalchas_bot.banner import (
    CREST,
    GLOW_LUMA,
    HEIGHT,
    WIDTH,
    _country_label,
    _ellipsize,
    _even_glow,
    _fit_logo,
    _team_colour,
    render_alert_photo,
)
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
    assert CREST == 180


def test_fit_logo_fills_crest_from_a_small_raster():
    src = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    draw = ImageDraw.Draw(src)
    draw.ellipse((4, 4, 43, 43), fill=(180, 40, 40, 255))
    fitted = _fit_logo(src, CREST)
    assert fitted.size == (CREST, CREST)
    assert fitted.getbbox() is not None


def test_banner_renders_with_country_and_league():
    buf = render_alert_photo(
        {
            "home_team": "Kastamonuspor",
            "away_team": "Elazigspor",
            "minute": 16,
            "score": "0-0",
            "payload": {
                "league": "2. Lig - 2. Lig White Group",
                "country": "Turkey",
                "status_short": "1H",
            },
        }
    )
    assert buf is not None
    assert Image.open(BytesIO(buf.getvalue())).size == (WIDTH, HEIGHT)


def test_country_label_skips_international_and_repeats():
    assert _country_label("Turkey", "2. LIG") == "TURKEY"
    assert _country_label("intl", "UEFA CHAMPIONS LEAGUE") == ""
    assert _country_label("World", "FRIENDLIES") == ""
    assert _country_label("Argentina", "LIGA PROFESIONAL ARGENTINA") == ""
    assert _country_label(None, "SERIE B") == ""


def test_fit_logo_clears_a_white_jpeg_square():
    src = Image.new("RGB", (60, 60), (255, 255, 255))
    ImageDraw.Draw(src).ellipse((10, 10, 49, 49), fill=(200, 30, 30))
    fitted = _fit_logo(src, CREST)
    assert fitted.getpixel((2, 2))[3] == 0
    assert fitted.getpixel((CREST // 2, CREST // 2))[3] == 255


def test_fit_logo_keeps_a_coloured_square():
    src = Image.new("RGB", (60, 60), (20, 60, 160))
    fitted = _fit_logo(src, CREST)
    assert fitted.getpixel((2, 2))[3] == 255


def test_team_colour_reads_the_crest_and_skips_monochrome():
    red = Image.new("RGBA", (CREST, CREST), (0, 0, 0, 0))
    ImageDraw.Draw(red).ellipse((20, 20, 160, 160), fill=(210, 30, 40, 255))
    r, g, b = _team_colour(red) or (0, 0, 0)
    assert r > 150 and g < 80 and b < 80
    grey = Image.new("RGBA", (CREST, CREST), (128, 128, 128, 255))
    assert _team_colour(grey) is None


def test_glows_share_one_brightness():
    def luma(rgb):
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

    for colour in ((255, 220, 0), (20, 30, 120), (210, 30, 40), (30, 160, 60)):
        assert abs(luma(_even_glow(colour)) - GLOW_LUMA) < 4


def test_long_names_ellipsize_to_the_column():
    draw = ImageDraw.Draw(Image.new("RGB", (800, 450)))
    font = ImageFont.load_default()
    label = _ellipsize(draw, "Universitario de Vinto", font, 40)
    assert label.endswith("...")
    assert draw.textbbox((0, 0), label, font=font)[2] <= 40
