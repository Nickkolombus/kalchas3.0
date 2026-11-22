"""K-Index (Strategy 7): the chance, in %, that a team scores inside the window.

Rebuilt 2026-11-22 from a logit blend of other strategies into a calibrated
chance. These tests pin the arithmetic and the behaviours the recipe was
fitted for; calibration itself was checked on `match_history`.
"""

from __future__ import annotations

import math

import pytest
from conftest import timeline_from
from kalchas_core import chance
from kalchas_core.match import MatchTimeline, Side
from kalchas_core.strategies.kscore import (
    DEFAULT_RATES,
    DEFAULT_THRESHOLD,
    UNREALISED_CAP,
    evaluate,
    live_boost,
    recent_shots,
)
from kalchas_core.weights import WeightSet

DEFAULTS = WeightSet.defaults()
EVEN = {"home_odds": 2.5, "draw_odds": 3.3, "away_odds": 2.9}


def quiet(minute: int) -> MatchTimeline:
    return timeline_from({minute - 10: {}, minute: {}}, current_minute=minute)


def shooting(minute: int, *, home_shots: int = 0, away_shots: int = 0) -> MatchTimeline:
    return timeline_from(
        {
            minute - 10: {},
            minute: {
                "home": {"shots_off_target": home_shots},
                "away": {"shots_off_target": away_shots},
            },
        },
        current_minute=minute,
    )


def weights(**overrides: float) -> WeightSet:
    return WeightSet.from_overrides({"kscore": overrides})


class TestRecipe:
    def test_quiet_minute_is_the_priced_base(self) -> None:
        result = evaluate(quiet(60), first_half=False, weights=weights(), **EVEN)
        home_rate, _ = chance.goal_rates(2.5, 3.3, 2.9)
        expected = home_rate * chance.window_goal_share(60, 20, first_half=False) * 0.92
        assert result.home.probability == pytest.approx(1 - math.exp(-expected))
        assert result.home.live_boost == 1.0
        assert result.home.score == round(100 * (1 - math.exp(-expected)))
        assert result.priced

    def test_reads_as_a_percentage(self) -> None:
        result = evaluate(quiet(30), **EVEN)
        assert 0 <= result.home.score <= 100
        assert result.home.score == round(result.home.probability * 100)

    def test_default_threshold_is_forty(self) -> None:
        assert DEFAULT_THRESHOLD == 40.0

    def test_favourite_reads_higher(self) -> None:
        result = evaluate(quiet(55), home_odds=1.4, draw_odds=4.8, away_odds=8.0)
        assert result.home.score > result.away.score

    def test_team_behind_reads_a_little_higher(self) -> None:
        level = evaluate(quiet(60), **EVEN)
        behind = evaluate(quiet(60), home_goals=0, away_goals=1, **EVEN)
        assert behind.home.probability > level.home.probability
        assert behind.away.probability < level.away.probability

    def test_less_time_left_reads_lower(self) -> None:
        early = evaluate(quiet(60), first_half=False, **EVEN)
        late = evaluate(quiet(85), first_half=False, **EVEN)
        assert late.home.probability < early.home.probability

    def test_window_stops_at_half_time(self) -> None:
        """At 44' only the rest of the first half counts, not the second."""
        at_44 = evaluate(
            quiet(44), first_half=True, weights=weights(first_half_multiplier=1.0), **EVEN
        )
        home_rate, _ = chance.goal_rates(2.5, 3.3, 2.9)
        rest_of_half = chance.remaining_goal_share(44, first_half=True) - sum(
            chance.GOAL_SHARE_BY_QUARTER_HOUR[3:]
        )
        expected = home_rate * rest_of_half * 0.92
        assert at_44.home.probability == pytest.approx(1 - math.exp(-expected))

    def test_match_score_is_either_team(self) -> None:
        result = evaluate(quiet(50), **EVEN)
        either = 1 - (1 - result.home.probability) * (1 - result.away.probability)
        assert result.match_score == round(100 * either)

    def test_no_prices_falls_back_to_an_average_match(self) -> None:
        result = evaluate(quiet(60), first_half=False)
        expected = DEFAULT_RATES[0] * chance.window_goal_share(60, 20, first_half=False) * 0.92
        assert result.home.probability == pytest.approx(1 - math.exp(-expected))
        assert not result.priced

    def test_horizon_is_tunable(self) -> None:
        short = evaluate(quiet(60), weights=weights(horizon_minutes=10), **EVEN)
        long = evaluate(quiet(60), weights=weights(horizon_minutes=30), **EVEN)
        assert short.home.probability < long.home.probability
        assert short.horizon_minutes == 10


class TestLiveBoost:
    def test_unrealised_goals_raise_it(self) -> None:
        calm = evaluate(quiet(60), **EVEN)
        overdue = evaluate(quiet(60), home_unrealised=2.0, **EVEN)
        assert overdue.home.live_boost == pytest.approx(1 + 0.07 * 2)
        assert overdue.home.probability > calm.home.probability

    def test_unrealised_is_capped_and_floored(self) -> None:
        assert live_boost(
            unrealised_goals=9.0, shots_last_10=0, first_half=False, weights=DEFAULTS
        ) == pytest.approx(1 + 0.07 * UNREALISED_CAP)
        assert live_boost(
            unrealised_goals=-1.5, shots_last_10=0, first_half=False, weights=DEFAULTS
        ) == pytest.approx(1.0)

    def test_recent_shots_raise_it(self) -> None:
        result = evaluate(shooting(70, home_shots=5), first_half=False, **EVEN)
        assert result.home.recent_shots == 5
        assert result.home.live_boost == pytest.approx(6**0.08)
        assert result.away.live_boost == 1.0

    def test_first_half_multiplier(self) -> None:
        assert live_boost(
            unrealised_goals=0, shots_last_10=0, first_half=True, weights=DEFAULTS
        ) == pytest.approx(1.28)

    def test_boost_is_capped(self) -> None:
        capped = live_boost(
            unrealised_goals=4,
            shots_last_10=30,
            first_half=True,
            weights=weights(unrealised_boost=0.5, max_live_boost=1.5),
        )
        assert capped == pytest.approx(1.5)

    def test_switching_live_terms_off_leaves_the_base(self) -> None:
        w = weights(unrealised_boost=0, recent_shots_power=0, first_half_multiplier=1.0)
        result = evaluate(shooting(30, home_shots=6), home_unrealised=3, weights=w, **EVEN)
        assert result.home.probability == pytest.approx(result.home.baseline)


class TestRecentShots:
    def test_counts_shots_on_and_off_target(self) -> None:
        tl = timeline_from(
            {60: {}, 70: {"home": {"shots_on_target": 2, "shots_off_target": 3}}},
            current_minute=70,
        )
        assert recent_shots(tl, Side.HOME) == 5
        assert recent_shots(tl, Side.AWAY) == 0

    def test_does_not_reach_back_into_the_first_half(self) -> None:
        """The feed numbers first-half stoppage 46-50, so the second half starts at 51."""
        tl = timeline_from(
            {
                40: {},
                48: {"home": {"shots_off_target": 6}},
                52: {"home": {"shots_off_target": 6}},
                55: {"home": {"shots_off_target": 7}},
            },
            current_minute=55,
        )
        assert recent_shots(tl, Side.HOME) == 1

    def test_gap_in_polling_uses_the_nearest_earlier_minute(self) -> None:
        tl = timeline_from(
            {20: {}, 35: {"home": {"shots_off_target": 4}}},
            current_minute=35,
        )
        assert recent_shots(tl, Side.HOME) == 4


class TestTrigger:
    def test_nothing_triggers_below_threshold(self) -> None:
        result = evaluate(quiet(60), **EVEN)
        assert result.triggering_team is None
        assert result.trigger_value == 0.0

    def test_higher_team_triggers(self) -> None:
        result = evaluate(quiet(20), threshold=1, home_odds=1.3, draw_odds=5.5, away_odds=10.0)
        assert result.triggering_team is Side.HOME
        assert result.trigger_value == float(result.home.score)

    def test_ties_go_home(self) -> None:
        result = evaluate(quiet(20), threshold=1, home_odds=2.6, draw_odds=3.2, away_odds=2.6)
        if result.home.score == result.away.score:
            assert result.triggering_team is Side.HOME


def test_old_weight_keys_are_ignored() -> None:
    """Saved rows for the retired blend (trust_*, bias, phi_floor...) drop out."""
    w = WeightSet.from_overrides({"kscore": {"bias": -2.3, "trust_momentum": 1.8}})
    assert w.get("kscore", "base_multiplier") == pytest.approx(0.92)
    assert evaluate(quiet(60), weights=w, **EVEN).home.probability == pytest.approx(
        evaluate(quiet(60), **EVEN).home.probability
    )


class TestTooEarly:
    def test_no_reading_before_minute_ten(self) -> None:
        result = evaluate(quiet(3), threshold=1, home_odds=1.3, draw_odds=5.0, away_odds=9.0)
        assert result.too_early
        assert (result.home.score, result.away.score, result.match_score) == (0, 0, 0)
        assert result.triggering_team is None

    def test_reads_from_minute_ten(self) -> None:
        result = evaluate(quiet(10), home_odds=1.3, draw_odds=5.0, away_odds=9.0)
        assert not result.too_early
        assert result.home.score > 0
