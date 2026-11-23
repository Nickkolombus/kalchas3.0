"""Goal before half-time from the Over/Under 2.5 price.

Rebuilt 2026-11-23: on 5,973 frozen watchlist matches the teams' and the
league's first-half record added nothing once the price was known.
"""

from __future__ import annotations

import math

import pytest
from kalchas_core.watchlist import build_team_profile, list_row, match_patterns
from kalchas_core.watchlist.first_half import (
    BADGE_MIN,
    INTERCEPT,
    SLOPE,
    expected_goals,
    first_half_chance,
)
from kalchas_core.watchlist.patterns import watch_score
from test_watchlist import AWAY, HOME, both_score_teams, norms, season

HIGH = {"over_2_5": 1.35, "under_2_5": 3.1}
EVEN = {"over_2_5": 1.95, "under_2_5": 1.85}
LOW = {"over_2_5": 2.6, "under_2_5": 1.5}


def test_expected_goals_matches_the_over_2_5_price_without_margin() -> None:
    goals = expected_goals(1.95, 1.85)
    assert goals is not None
    over = (1 / 1.95) / (1 / 1.95 + 1 / 1.85)
    assert 1 - math.exp(-goals) * (1 + goals + goals**2 / 2) == pytest.approx(over, abs=1e-6)


def test_needs_both_prices() -> None:
    assert expected_goals(1.9, None) is None
    assert expected_goals("x", 1.9) is None
    assert expected_goals(1.0, 1.9) is None
    assert first_half_chance(None) is None
    assert first_half_chance({"home": 2.0}) is None


def test_chance_formula_and_order() -> None:
    goals = expected_goals(1.35, 3.1)
    assert goals is not None
    assert first_half_chance(HIGH) == pytest.approx(
        1 / (1 + math.exp(-(INTERCEPT + SLOPE * math.log(goals))))
    )
    high, even, low = (first_half_chance(o) for o in (HIGH, EVEN, LOW))
    assert high is not None and even is not None and low is not None
    assert high > BADGE_MIN > even > low
    assert 0.64 < even < 0.74  # a coin-flip over 2.5 line: about 2.6 goals expected


def quiet_pair():
    """Teams with an ordinary first-half record: the price alone decides."""
    home = build_team_profile(
        season(HOME, [(1, 1), (2, 0), (0, 1), (1, 0), (1, 2)] * 2), HOME, name="A"
    )
    away = build_team_profile(
        season(AWAY, [(0, 1), (1, 1), (2, 1), (0, 0), (1, 0)] * 2, start=50), AWAY, name="B"
    )
    return home, away


def test_pattern_comes_from_the_price() -> None:
    home, away = quiet_pair()
    found = {p.key: p for p in match_patterns(home, away, norms(), league="Ligue 2", odds=HIGH)}
    early = found["first_half_goal"]
    assert early.title == "A goal before half-time looks likely."
    assert "Over 2.5 goals is priced 1.35" in early.detail
    assert "the Ligue 2 average of 72%" in early.detail
    assert early.brief.startswith("Priced for goals: a first-half goal about 8")


def test_no_price_or_an_ordinary_price_says_nothing() -> None:
    home, away = quiet_pair()
    for odds in (None, EVEN, LOW):
        keys = {p.key for p in match_patterns(home, away, norms(), league="", odds=odds)}
        assert "first_half_goal" not in keys


def test_it_shares_the_goals_family() -> None:
    home, away = both_score_teams()
    patterns = match_patterns(home, away, norms(btts=0.5), league="", odds=HIGH)
    assert "first_half_goal" in {p.key for p in patterns}
    without = [p for p in patterns if p.key != "first_half_goal"]
    assert watch_score(patterns) == watch_score(without)


def test_list_row_carries_the_chance() -> None:
    page = {
        "match_id": "1",
        "kickoff": "2026-11-23T20:00:00+00:00",
        "home": {"name": "A", "badge": None, "position": None},
        "away": {"name": "B", "badge": None, "position": None},
        "odds": {"home": 2.0, "draw": 3.4, "away": 3.6, **HIGH},
        "watch": "quiet",
        "score": 0.1,
        "patterns": [],
    }
    row = list_row(page, "1:L")
    assert row["first_half"]["over_2_5"] == 1.35
    assert row["first_half"]["chance"] == round(first_half_chance(HIGH) or 0, 3)
    assert list_row({**page, "odds": {"home": 2.0}}, "1:L")["first_half"] is None
