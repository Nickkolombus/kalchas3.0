"""Thermal parlay slip PNG renders and looks like a receipt."""

from __future__ import annotations

from io import BytesIO

from kalchas_bot.parlay_slip import render_parlay_slip
from PIL import Image


def _legs(n: int = 3) -> list[dict]:
    out = []
    for i in range(n):
        out.append(
            {
                "match_id": str(100 + i),
                "kickoff": f"2026-11-07T{14 + i:02d}:00:00+03:00",
                "home": {"name": f"Home{i}"},
                "away": {"name": f"Away{i}"},
                "label": "Over 2.5 goals",
                "price": 1.5 + i * 0.1,
            }
        )
    return out


def test_slip_is_png_with_receipt_width() -> None:
    png = render_parlay_slip(_legs(), slot="today", style="balanced", day="2026-11-07")
    img = Image.open(BytesIO(png))
    assert img.format == "PNG"
    assert img.size[0] == 540
    assert img.size[1] > 200


def test_nightly_slip_renders() -> None:
    legs = [
        {
            "match_id": "1",
            "kickoff": "2026-11-08T02:00:00+03:00",
            "home": {"name": "Boca"},
            "away": {"name": "River"},
            "label": "Both teams score",
            "price": 1.8,
        },
        {
            "match_id": "2",
            "kickoff": "2026-11-08T03:15:00+03:00",
            "home": {"name": "Flamengo"},
            "away": {"name": "Palmeiras"},
            "label": "Over 2.5 goals",
            "price": 1.7,
        },
        {
            "match_id": "3",
            "kickoff": "2026-11-08T04:00:00+03:00",
            "home": {"name": "América"},
            "away": {"name": "Chivas"},
            "label": "Favourite to win",
            "price": 2.0,
        },
    ]
    png = render_parlay_slip(legs, slot="nightly", style="safer", day="2026-11-08")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_settled_lost_banner() -> None:
    png = render_parlay_slip(
        _legs(3),
        slot="today",
        style="bolder",
        day="2026-11-07",
        settled={"100": "landed", "101": "missed", "102": "landed"},
    )
    assert len(png) > 500
