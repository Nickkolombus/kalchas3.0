"""K-Index (Strategy 7): rises only with play, read as a chance to score soon.

Rebuilt 2026-11-22. These tests pin the arithmetic and the behaviours asked
for: no shots reads 0, the price decides what a shot is worth, and the first
minutes need an extraordinary burst. Calibration was checked on
`match_history`.
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
    SHOTS_PER_GOAL,
    early_brake,
    evaluate,
    evidence,
    recent_shots,
)
from kalchas_core.weights import WeightSet

DEFAULTS = WeightSet.defaults()
EVEN = {"home_odds": 2.5, "draw_odds": 3.3, "away_odds": 2.9}
STRONG_HOME = {"home_odds": 1.3, "draw_odds": 5.0, "away_odds": 9.0}


def shooting(
    minute: int,
    *,
    home: int = 0,
    away: int = 0,
    home_recent: int = 0,
    away_recent: int = 0,
) -> MatchTimeline:
    """`home`/`away` shots in total by `minute`, of which `*_recent` in the last 10'."""
    return timeline_from(
        {
            minute - 10: {
                "home": {"shots_off_target": home - home_recent},
                "away": {"shots_off_target": away - away_recent},
            },
            minute: {"home": {"shots_off_target": home}, "away": {"shots_off_target": away}},
        },
        current_minute=minute,
    )


def weights(**overrides: float) -> WeightSet:
    return WeightSet.from_overrides({"kscore": overrides})


class TestRisesOnlyWithPlay:
    def test_no_shots_reads_zero_even_for_a_big_favourite(self) -> None:
        result = evaluate(shooting(60), first_half=False, **STRONG_HOME)
        assert (result.home.score, result.away.score) == (0, 0)
        assert result.home.priced_chance > 0.3  # the price alone would say a lot

    def test_shots_raise_it(self) -> None:
        few = evaluate(shooting(60, home=4), first_half=False, **EVEN)
        many = evaluate(shooting(60, home=14), first_half=False, **EVEN)
        assert 0 < few.home.score < many.home.score

    def test_favourite_climbs_faster_on_the_same_shooting(self) -> None:
        result = evaluate(shooting(60, home=8, away=8), first_half=False, **STRONG_HOME)
        assert result.home.score > result.away.score

    def test_recent_shots_count_extra(self) -> None:
        old = evaluate(shooting(60, home=6, home_recent=0), first_half=False, **EVEN)
        fresh = evaluate(shooting(60, home=6, home_recent=6), first_half=False, **EVEN)
        assert fresh.home.recent_shots == 6
        assert fresh.home.probability > old.home.probability

    def test_formula(self) -> None:
        result = evaluate(
            shooting(60, home=9, home_recent=3), first_half=False, weights=weights(), **EVEN
        )
        rate, _ = chance.goal_rates(2.5, 3.3, 2.9)
        priced = rate * chance.window_goal_share(60, 20, first_half=False)
        pace = (9 + 0.4 * 3) / (60 + 15)
        shown = min(2.0, (pace / (rate / 90 * SHOTS_PER_GOAL)) ** 0.5)
        assert result.home.evidence == pytest.approx(shown)
        assert result.home.probability == pytest.approx(1 - math.exp(-1.25 * priced * shown))
        assert result.home.score == round(100 * result.home.probability)


class TestEarlyMinutes:
    def test_brake(self) -> None:
        assert early_brake(5, DEFAULTS) == pytest.approx(0.25)
        assert early_brake(1, DEFAULTS) == pytest.approx(0.01)
        assert early_brake(10, DEFAULTS) == 1.0
        assert early_brake(70, DEFAULTS) == 1.0

    def test_a_normal_start_stays_low(self) -> None:
        result = evaluate(shooting(4, home=2, home_recent=2), first_half=True, **STRONG_HOME)
        assert result.home.score < 15

    def test_only_an_extraordinary_start_breaks_through(self) -> None:
        result = evaluate(shooting(8, home=12, home_recent=12), first_half=True, **STRONG_HOME)
        assert result.home.score >= DEFAULT_THRESHOLD

    def test_settling_minutes_damp_an_early_burst(self) -> None:
        early = evidence(minute=12, shots=4, shots_last_10=0, full_match_rate=1.5, weights=DEFAULTS)
        later = evidence(
            minute=12,
            shots=4,
            shots_last_10=0,
            full_match_rate=1.5,
            weights=weights(settling_minutes=0),
        )
        assert early < later


class TestSettings:
    def test_power_zero_is_the_price_alone(self) -> None:
        w = weights(evidence_power=0)
        result = evaluate(shooting(60), first_half=False, weights=w, **EVEN)
        rate, _ = chance.goal_rates(2.5, 3.3, 2.9)
        priced = rate * chance.window_goal_share(60, 20, first_half=False)
        assert result.home.probability == pytest.approx(1 - math.exp(-1.25 * priced))

    def test_evidence_is_capped(self) -> None:
        assert evidence(
            minute=30, shots=60, shots_last_10=20, full_match_rate=1.0, weights=DEFAULTS
        ) == pytest.approx(2.0)

    def test_first_half_multiplier(self) -> None:
        w = weights(first_half_multiplier=1.0)
        plain = evaluate(shooting(30, home=6), first_half=True, weights=w, **EVEN)
        boosted = evaluate(shooting(30, home=6), first_half=True, **EVEN)
        assert boosted.home.probability > plain.home.probability

    def test_horizon(self) -> None:
        short = evaluate(shooting(60, home=8), weights=weights(horizon_minutes=10), **EVEN)
        long = evaluate(shooting(60, home=8), weights=weights(horizon_minutes=30), **EVEN)
        assert short.home.probability < long.home.probability
        assert short.horizon_minutes == 10

    def test_old_weight_keys_are_ignored(self) -> None:
        w = WeightSet.from_overrides({"kscore": {"bias": -2.3, "unrealised_boost": 0.3}})
        assert evaluate(shooting(60, home=8), weights=w, **EVEN).home.probability == (
            pytest.approx(evaluate(shooting(60, home=8), **EVEN).home.probability)
        )


class TestMatchState:
    def test_window_stops_at_half_time(self) -> None:
        at_44 = evaluate(shooting(44, home=8), first_half=True, **EVEN)
        rate, _ = chance.goal_rates(2.5, 3.3, 2.9)
        rest = chance.remaining_goal_share(44, first_half=True) - sum(
            chance.GOAL_SHARE_BY_QUARTER_HOUR[3:]
        )
        assert at_44.home.priced_chance == pytest.approx(1 - math.exp(-rate * rest))

    def test_team_behind_reads_a_little_higher(self) -> None:
        level = evaluate(shooting(60, home=8), **EVEN)
        behind = evaluate(shooting(60, home=8), home_goals=0, away_goals=1, **EVEN)
        assert behind.home.probability > level.home.probability

    def test_no_prices_falls_back_to_an_average_match(self) -> None:
        result = evaluate(shooting(60, home=8), first_half=False)
        assert not result.priced
        assert result.home.priced_chance == pytest.approx(
            1 - math.exp(-DEFAULT_RATES[0] * chance.window_goal_share(60, 20, first_half=False))
        )

    def test_match_score_is_either_team(self) -> None:
        result = evaluate(shooting(50, home=7, away=5), **EVEN)
        either = 1 - (1 - result.home.probability) * (1 - result.away.probability)
        assert result.match_score == round(100 * either)


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
        tl = timeline_from({20: {}, 35: {"home": {"shots_off_target": 4}}}, current_minute=35)
        assert recent_shots(tl, Side.HOME) == 4


class TestTrigger:
    def test_default_threshold_is_forty(self) -> None:
        assert DEFAULT_THRESHOLD == 40.0

    def test_nothing_triggers_below_threshold(self) -> None:
        result = evaluate(shooting(60, home=2), **EVEN)
        assert result.triggering_team is None
        assert result.trigger_value == 0.0

    def test_higher_team_triggers(self) -> None:
        result = evaluate(shooting(30, home=9, away=2), threshold=1, **STRONG_HOME)
        assert result.triggering_team is Side.HOME
        assert result.trigger_value == float(result.home.score)
