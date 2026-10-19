"""K-Score (Strategy 7).

New in 3.0; 2.2 had no unit tests for the blend. Verified historically against
2.2 over 800 signal pairs (`scripts/verify_kscore_port.py`). Product SSOT:
Omega always contributes via the full TeamOmega triple.
"""

from __future__ import annotations

import math

import pytest
from kalchas_core.match import Side
from kalchas_core.strategies.kscore import (
    DEFAULT_THRESHOLD,
    MatchContext,
    TeamSignals,
    consultant_votes,
    context_logit_delta,
    evaluate,
    evaluate_team,
    focus,
    omega_vote,
    sigmoid,
)
from kalchas_core.weights import WeightSet

DEFAULTS = WeightSet.defaults()


def signals(**kwargs: float) -> TeamSignals:
    return TeamSignals(**kwargs)


class TestSigmoid:
    def test_midpoint(self) -> None:
        assert sigmoid(0.0) == pytest.approx(0.5)

    def test_is_monotonic_and_bounded(self) -> None:
        values = [sigmoid(x) for x in (-20, -1, 0, 1, 20)]
        assert values == sorted(values)
        assert all(0.0 < v < 1.0 for v in values)

    def test_extreme_inputs_stay_finite(self) -> None:
        assert math.isfinite(sigmoid(1e6))
        assert math.isfinite(sigmoid(-1e6))


class TestOmegaVote:
    def test_incomplete_omega_is_neutral(self) -> None:
        """Accel without baseline/level must not apply the old truncated drag."""
        for accel in (0, 1, 10, 50, 200, 1e6):
            assert omega_vote(acceleration=accel) == pytest.approx(0.5)

    def test_full_omega_can_produce_a_supporting_vote(self) -> None:
        vote = omega_vote(acceleration=0.6, baseline=0.3, level=60.0)
        assert vote > 0.5

    def test_full_omega_with_zero_level_stays_at_floor_band(self) -> None:
        vote = omega_vote(acceleration=5.0, baseline=0.0, level=0.0)
        assert vote == pytest.approx(0.145, abs=0.001)
        assert vote < 0.5

    def test_legacy_angle_form_when_acceleration_is_absent(self) -> None:
        assert omega_vote(theta=0.0, alpha=0.0) == pytest.approx(0.5)
        rising = omega_vote(theta=45.0, alpha=30.0)
        assert rising > 0.5

    def test_negative_acceleration_is_floored_at_zero(self) -> None:
        assert omega_vote(acceleration=-10.0, baseline=2.0, level=50.0) == omega_vote(
            acceleration=0.0, baseline=2.0, level=50.0
        )


class TestConsultantVotes:
    def test_quiet_signals_sit_near_or_below_neutral(self) -> None:
        votes = consultant_votes(signals(), DEFAULTS)
        assert votes["momentum"] == pytest.approx(0.5)
        assert votes["pressure"] == 0.0
        assert votes["rule3"] == pytest.approx(0.3 / 1.3)
        # No acceleration → legacy sine form at (0,0) → 0.5
        assert votes["omega"] == pytest.approx(0.5)

    def test_strong_signals_approach_one(self) -> None:
        votes = consultant_votes(
            signals(
                delta_5min=40.0,
                pressure_index=100.0,
                rule_of_three=1.0,
                omega_acceleration=50.0,
                omega_baseline=5.0,
                omega_level=100.0,
            ),
            DEFAULTS,
        )
        assert votes["momentum"] > 0.99
        assert votes["pressure"] == 1.0
        assert votes["rule3"] == 1.0
        assert votes["omega"] > 0.8

    def test_momentum_scale_is_tunable(self) -> None:
        quiet_scale = WeightSet.from_overrides({"kscore": {"momentum_scale": 2.0}})
        wide_scale = WeightSet.from_overrides({"kscore": {"momentum_scale": 30.0}})
        s = signals(delta_5min=8.0)
        assert (
            consultant_votes(s, quiet_scale)["momentum"]
            > consultant_votes(s, wide_scale)["momentum"]
        )


class TestFocus:
    def test_zero_npei_returns_the_floor(self) -> None:
        assert focus(0.0, DEFAULTS) == pytest.approx(DEFAULTS.get("kscore", "phi_floor"))

    def test_full_npei_returns_one(self) -> None:
        assert focus(100.0, DEFAULTS) == pytest.approx(1.0)

    def test_npei_is_linear_between_floor_and_one(self) -> None:
        mid = focus(50.0, DEFAULTS)
        floor = DEFAULTS.get("kscore", "phi_floor")
        assert mid == pytest.approx(floor + (1.0 - floor) * 0.5)


class TestContext:
    def test_missing_context_contributes_nothing(self) -> None:
        assert context_logit_delta(Side.HOME, None, DEFAULTS) == 0.0

    def test_red_cards_penalise(self) -> None:
        ctx = MatchContext(home_red_cards=2)
        assert context_logit_delta(Side.HOME, ctx, DEFAULTS) < 0
        assert context_logit_delta(Side.AWAY, ctx, DEFAULTS) == 0.0

    def test_red_cards_cap_at_two(self) -> None:
        two = context_logit_delta(Side.HOME, MatchContext(home_red_cards=2), DEFAULTS)
        three = context_logit_delta(Side.HOME, MatchContext(home_red_cards=3), DEFAULTS)
        assert two == three

    def test_trailing_late_boosts(self) -> None:
        ctx = MatchContext(minute=85, home_score=0, away_score=2)
        assert context_logit_delta(Side.HOME, ctx, DEFAULTS) > 0
        assert context_logit_delta(Side.AWAY, ctx, DEFAULTS) == 0.0

    def test_trailing_before_the_late_minute_does_nothing(self) -> None:
        ctx = MatchContext(minute=50, home_score=0, away_score=2)
        assert context_logit_delta(Side.HOME, ctx, DEFAULTS) == 0.0

    def test_kickoff_favourite_gets_a_positive_prior(self) -> None:
        ctx = MatchContext(home_kickoff_odds=1.4, away_kickoff_odds=7.0)
        assert context_logit_delta(Side.HOME, ctx, DEFAULTS) > 0
        assert context_logit_delta(Side.AWAY, ctx, DEFAULTS) < 0

    def test_even_odds_contribute_nothing(self) -> None:
        ctx = MatchContext(home_kickoff_odds=2.5, away_kickoff_odds=2.5)
        assert context_logit_delta(Side.HOME, ctx, DEFAULTS) == pytest.approx(0.0)


class TestEvaluate:
    def test_strong_home_signals_score_higher_than_quiet(self) -> None:
        strong = evaluate(
            signals(
                delta_5min=30.0,
                pressure_index=90.0,
                rule_of_three=1.0,
                npei=80.0,
                omega_acceleration=20.0,
                omega_baseline=3.0,
                omega_level=70.0,
            ),
            signals(),
        )
        quiet = evaluate(signals(), signals())
        assert strong.home.score > quiet.home.score

    def test_match_score_is_the_or_of_both_probabilities(self) -> None:
        result = evaluate(
            signals(delta_5min=20.0, pressure_index=80.0, npei=70.0),
            signals(delta_5min=20.0, pressure_index=80.0, npei=70.0),
        )
        expected = 1.0 - (1.0 - result.home.probability) * (1.0 - result.away.probability)
        assert result.match_score == max(0, min(100, round(100.0 * expected)))

    def test_scores_are_integers_in_zero_to_one_hundred(self) -> None:
        result = evaluate(
            signals(delta_5min=50.0, pressure_index=100.0, rule_of_three=2.0, npei=100.0),
            signals(),
        )
        for score in (result.home.score, result.away.score, result.match_score):
            assert isinstance(score, int)
            assert 0 <= score <= 100

    def test_a_team_above_threshold_triggers(self) -> None:
        result = evaluate(
            signals(
                delta_5min=40.0,
                pressure_index=100.0,
                rule_of_three=1.0,
                npei=100.0,
                omega_acceleration=40.0,
                omega_baseline=5.0,
                omega_level=90.0,
            ),
            signals(),
            threshold=DEFAULT_THRESHOLD,
        )
        assert result.home.score >= DEFAULT_THRESHOLD
        assert result.triggering_team is Side.HOME
        assert result.trigger_value == float(result.home.score)

    def test_neither_team_above_threshold_does_not_trigger(self) -> None:
        result = evaluate(signals(), signals(), threshold=60.0)
        assert result.triggering_team is None
        assert result.trigger_value == 0.0

    def test_tie_on_score_goes_to_the_home_team(self) -> None:
        identical = signals(
            delta_5min=40.0,
            pressure_index=100.0,
            rule_of_three=1.0,
            npei=100.0,
            omega_acceleration=40.0,
            omega_baseline=5.0,
            omega_level=90.0,
        )
        result = evaluate(identical, identical, threshold=50.0)
        assert result.home.score == result.away.score
        assert result.home.score >= 50.0
        assert result.triggering_team is Side.HOME

    def test_focus_scales_the_raw_probability(self) -> None:
        high = evaluate_team(signals(delta_5min=20.0, pressure_index=80.0, npei=100.0))
        low = evaluate_team(signals(delta_5min=20.0, pressure_index=80.0, npei=0.0))
        assert high.probability > low.probability
        assert high.probability_raw == pytest.approx(low.probability_raw)


class TestOmegaSsot:
    """Full TeamOmega is the only supporting path; incomplete is neutral."""

    def test_accel_only_does_not_change_the_score(self) -> None:
        without = evaluate_team(signals(delta_5min=15.0, pressure_index=60.0, npei=50.0))
        incomplete = evaluate_team(
            signals(
                delta_5min=15.0,
                pressure_index=60.0,
                npei=50.0,
                omega_acceleration=50.0,
            )
        )
        assert incomplete.votes["omega"] == pytest.approx(0.5)
        assert incomplete.score == without.score

    def test_full_omega_signals_can_raise_the_score(self) -> None:
        without = evaluate_team(signals(delta_5min=15.0, pressure_index=60.0, npei=50.0))
        with_full = evaluate_team(
            signals(
                delta_5min=15.0,
                pressure_index=60.0,
                npei=50.0,
                omega_acceleration=50.0,
                omega_baseline=5.0,
                omega_level=90.0,
            )
        )
        assert with_full.votes["omega"] > 0.5
        assert with_full.score >= without.score


class TestRemovedDeadControls:
    def test_horizon_is_not_in_the_registry(self) -> None:
        """2.2 showed a horizon slider that the formula never read."""
        assert "horizon" not in WeightSet.defaults().for_strategy("kscore")


class TestWeightTuning:
    def test_raising_momentum_trust_amplifies_a_strong_delta(self) -> None:
        heavy = WeightSet.from_overrides({"kscore": {"trust_momentum": 3.0}})
        light = WeightSet.from_overrides({"kscore": {"trust_momentum": 0.1}})
        s = signals(delta_5min=40.0, npei=100.0)
        assert evaluate_team(s, weights=heavy).score > evaluate_team(s, weights=light).score

    def test_a_preset_applies(self) -> None:
        preset = WeightSet.from_preset("kscore", "Momentum-led")
        assert evaluate_team(signals(delta_5min=20.0, npei=50.0), weights=preset).score >= 0

    def test_context_weights_at_zero_disable_the_terms(self) -> None:
        off = WeightSet.from_overrides(
            {
                "kscore": {
                    "ctx_red_card": 0.0,
                    "ctx_trailing": 0.0,
                    "ctx_ko_prior": 0.0,
                }
            }
        )
        ctx = MatchContext(
            minute=85,
            home_score=0,
            away_score=2,
            home_red_cards=2,
            home_kickoff_odds=1.3,
            away_kickoff_odds=6.0,
        )
        assert context_logit_delta(Side.HOME, ctx, off) == 0.0
