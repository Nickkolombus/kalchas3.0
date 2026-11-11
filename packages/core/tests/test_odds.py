"""Favourite detection from kickoff odds payloads."""

from __future__ import annotations

import pytest
from kalchas_core.odds import (
    detect_favourite_from_payload,
    detect_favourite_side,
    extract_1x2_odds,
    is_short_price,
    kickoff_home_away,
)


@pytest.mark.parametrize(
    ("odds_data", "expected"),
    [
        (
            [
                {
                    "bookmaker": "Bet365",
                    "bets": [
                        {
                            "name": "Match Winner",
                            "values": [
                                {"value": "Home", "odd": "1.60"},
                                {"value": "Draw", "odd": "3.60"},
                                {"value": "Away", "odd": "5.00"},
                            ],
                        }
                    ],
                }
            ],
            "home",
        ),
        (
            [
                {
                    "bookmakers": [
                        {
                            "name": "Bet365",
                            "bets": [
                                {
                                    "name": "1x2",
                                    "values": [
                                        {"value": "Home", "odd": "4.20"},
                                        {"value": "Draw", "odd": "3.20"},
                                        {"value": "Away", "odd": "1.70"},
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ],
            "away",
        ),
    ],
)
def test_detect_favourite_from_payload(odds_data, expected) -> None:
    assert detect_favourite_from_payload(odds_data) == expected


def test_threshold_boundary() -> None:
    assert detect_favourite_side(1.78, 3.0) is None
    assert detect_favourite_side(1.77, 3.0) == "home"
    assert detect_favourite_side(3.0, 1.77) == "away"


def test_extract_1x2_odds_direct_bookmaker() -> None:
    odds = extract_1x2_odds(
        [
            {
                "bets": [
                    {
                        "name": "Match Winner",
                        "values": [
                            {"value": "Home", "odd": "1.60"},
                            {"value": "Draw", "odd": "3.60"},
                            {"value": "Away", "odd": "5.00"},
                        ],
                    }
                ]
            }
        ]
    )
    assert odds == {"home": 1.60, "draw": 3.60, "away": 5.00}


def test_extract_1x2_odds_empty() -> None:
    assert extract_1x2_odds([]) is None
    assert extract_1x2_odds(None) is None


def test_is_short_price_strictly_under_168() -> None:
    assert is_short_price(1.29) is True
    assert is_short_price(1.67) is True
    assert is_short_price(1.68) is False
    assert is_short_price(1.78) is False
    assert is_short_price(1.0) is False
    assert is_short_price(None) is False


def test_kickoff_home_away_prefers_nested() -> None:
    assert kickoff_home_away(
        {
            "home": 2.1,
            "away": 3.4,
            "kickoff": {"home": 1.29, "draw": 6.0, "away": 11.0},
        }
    ) == (1.29, 11.0)
    assert kickoff_home_away({"home": 1.50, "away": 6.0}) == (1.50, 6.0)
    assert kickoff_home_away(None) == (None, None)


def test_fresh_live_line_keeps_recent_stamped_lines_only() -> None:
    from datetime import UTC, datetime

    from kalchas_core.odds import LIVE_ODDS_MAX_AGE_SEC, fresh_live_line

    now = datetime(2026, 11, 3, 21, 24, 10, tzinfo=UTC)
    line = {"home": 3.1, "draw": 2.0, "away": 4.8}

    def record(stamp: str | None) -> dict:
        live = dict(line)
        if stamp is not None:
            live["fetched_at"] = stamp
        return {"live": live}

    assert fresh_live_line(record("2026-11-03T21:23:00+00:00"), now=now) is not None
    # Naive stamps are read as UTC.
    assert fresh_live_line(record("2026-11-03T21:23:00"), now=now) is not None
    # Just inside / outside the age limit.
    assert LIVE_ODDS_MAX_AGE_SEC == 180
    assert fresh_live_line(record("2026-11-03T21:21:10Z"), now=now) is not None
    assert fresh_live_line(record("2026-11-03T21:21:09Z"), now=now) is None
    # Unstamped, unparseable, or from the future beyond clock skew.
    assert fresh_live_line(record(None), now=now) is None
    assert fresh_live_line(record("yesterday"), now=now) is None
    assert fresh_live_line(record("2026-11-03T21:30:00Z"), now=now) is None
    assert fresh_live_line({"kickoff": line}, now=now) is None
    assert fresh_live_line(None, now=now) is None
