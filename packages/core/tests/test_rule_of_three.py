"""Rule of Three (Strategy 1).

New in 3.0. Kalchas 2.2 had no tests for this strategy despite it being the
oldest one in the system.

The port was additionally verified against 2.2 by differential comparison over
9,600 match situations (`scripts/verify_rule_of_three_port.py`), which agreed
to within 1e-9 on both teams' values and the legacy points band. These tests
describe the behaviour; that script proved it did not move.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from kalchas_core.match import Side, TeamStats
from kalchas_core.strategies.rule_of_three import (
    RuleOfThreeResult,
    TeamShotProfile,
    evaluate,
    game_state_modifier,
    legacy_points,
    odds_difficulty_factor,
    possession_adjustment,
    shot_quality_factor,
    time_of_match_multiplier,
)
from kalchas_core.weights import WeightSet

DEFAULTS = WeightSet.defaults()


def profile(**kwargs: object) -> TeamShotProfile:
    return TeamShotProfile(**kwargs)  # type: ignore[arg-type]


class TestShotQuality:
    def test_no_shots_is_neutral(self) -> None:
        assert shot_quality_factor(0, 0, DEFAULTS) == 1.0

    def test_perfect_accuracy_is_base_plus_full_slope(self) -> None:
        assert shot_quality_factor(5, 0, DEFAULTS) == pytest.approx(0.8 + 0.4)

    def test_no_accuracy_is_base_only(self) -> None:
        assert shot_quality_factor(0, 5, DEFAULTS) == pytest.approx(0.8)

    def test_quality_rises_with_accuracy(self) -> None:
        assert shot_quality_factor(1, 9, DEFAULTS) < shot_quality_factor(9, 1, DEFAULTS)


class TestGameState:
    def test_level_scoreline_is_neutral(self) -> None:
        assert game_state_modifier(1, 1, 60) == 1.0

    def test_a_one_goal_lead_eases_off(self) -> None:
        assert game_state_modifier(1, 0, 60) == 0.90

    def test_a_one_goal_deficit_pushes(self) -> None:
        assert game_state_modifier(0, 1, 60) == 1.05

    def test_a_settled_two_goal_lead_discounts_harder_than_a_plain_one(self) -> None:
        """3-1 reads as settled in a way 2-0 does not."""
        assert game_state_modifier(3, 1, 70) < game_state_modifier(2, 0, 70)

    def test_leads_discount_further_as_time_runs_down(self) -> None:
        assert game_state_modifier(2, 0, 85) < game_state_modifier(2, 0, 10)

    def test_two_down_late_is_worth_less_than_two_down_early(self) -> None:
        assert game_state_modifier(0, 2, 85) < game_state_modifier(0, 2, 10)

    @pytest.mark.parametrize("minute", [0, None])
    def test_no_clock_means_no_time_decay(self, minute: int) -> None:
        assert game_state_modifier(2, 0, minute) == pytest.approx(0.75)


class TestTimeMultiplier:
    @pytest.mark.parametrize(
        ("minute", "expected"),
        [(15, 0.90), (30, 0.90), (31, 1.00), (60, 1.00), (61, 1.10), (75, 1.10), (76, 1.20)],
    )
    def test_bands(self, minute: int, expected: float) -> None:
        assert time_of_match_multiplier(minute, DEFAULTS) == pytest.approx(expected)

    @pytest.mark.parametrize("minute", [None, 0, -5])
    def test_unknown_or_impossible_minute_is_neutral(self, minute: int | None) -> None:
        assert time_of_match_multiplier(minute, DEFAULTS) == 1.0


class TestPossessionAdjustment:
    def test_no_reading_is_neutral(self) -> None:
        assert possession_adjustment(None, DEFAULTS) == 0.0

    @pytest.mark.parametrize("share", [50, 65, 100])
    def test_majority_possession_earns_no_bonus(self, share: float) -> None:
        assert possession_adjustment(share, DEFAULTS) == 0.0

    def test_low_possession_is_penalised(self) -> None:
        assert possession_adjustment(30, DEFAULTS) < 0

    def test_penalty_scales_with_the_shortfall(self) -> None:
        assert possession_adjustment(20, DEFAULTS) < possession_adjustment(40, DEFAULTS)


class TestOddsFactor:
    @pytest.mark.parametrize(
        ("own", "opponent"),
        [(None, None), (2.0, None), (None, 2.0), (0, 2.0)],
    )
    def test_missing_prices_are_neutral(self, own: float | None, opponent: float | None) -> None:
        assert odds_difficulty_factor(own, opponent) == 1.0

    def test_evenly_matched_is_near_neutral(self) -> None:
        assert odds_difficulty_factor(2.0, 2.0) == pytest.approx(1.0, abs=0.2)

    def test_the_favourite_is_boosted(self) -> None:
        """A short-priced side dominating without scoring is truly overdue."""
        assert odds_difficulty_factor(1.5, 6.0) > 1.0

    def test_the_underdog_is_discounted(self) -> None:
        assert odds_difficulty_factor(6.0, 1.5) < 1.0

    def test_the_factor_moves_monotonically_with_superiority(self) -> None:
        assert (
            odds_difficulty_factor(4.0, 2.0)
            < odds_difficulty_factor(2.0, 2.0)
            < odds_difficulty_factor(2.0, 4.0)
        )

    def test_the_curve_is_bounded_at_both_extremes(self) -> None:
        """Log scaling keeps a 20-to-1 shot from being rewarded twentyfold."""
        assert 0.5 <= odds_difficulty_factor(50.0, 1.01) <= 1.6
        assert 0.5 <= odds_difficulty_factor(1.01, 50.0) <= 1.6


class TestEvaluate:
    def test_shots_without_goals_produce_unrealised_potential(self) -> None:
        result = evaluate(profile(shots_on_target=9, goals=0), profile(), minute=60)
        assert result.home.unrealised_goals > 0

    def test_goals_already_scored_cancel_the_potential(self) -> None:
        overdue = evaluate(profile(shots_on_target=9, goals=0), profile(), minute=60)
        converted = evaluate(profile(shots_on_target=9, goals=3), profile(), minute=60)
        assert converted.home.unrealised_goals < overdue.home.unrealised_goals

    def test_a_quiet_team_is_not_overdue(self) -> None:
        result = evaluate(profile(shots_on_target=0, goals=1), profile(), minute=60)
        assert result.home.unrealised_goals < 0

    def test_trigger_value_is_the_more_overdue_team(self) -> None:
        result = evaluate(profile(shots_on_target=9), profile(shots_on_target=1), minute=60)
        assert result.trigger_value == result.home.unrealised_goals
        assert result.leader is Side.HOME

    def test_leader_is_none_when_teams_are_identical(self) -> None:
        result = evaluate(profile(shots_on_target=4), profile(shots_on_target=4), minute=60)
        assert result.leader is None

    def test_total_sums_both_teams(self) -> None:
        result = evaluate(profile(shots_on_target=5), profile(shots_on_target=3), minute=60)
        assert result.total == pytest.approx(
            result.home.unrealised_goals + result.away.unrealised_goals
        )

    def test_the_contributing_factors_are_reported(self) -> None:
        """2.2 returned one float; the factors behind it were unrecoverable."""
        result = evaluate(
            profile(shots_on_target=6, shots_off_target=4, possession=35, kickoff_odds=1.6),
            profile(kickoff_odds=5.0),
            minute=80,
        )
        assert result.home.shot_quality > 1.0
        assert result.home.possession_adjustment < 0
        assert result.home.odds_factor > 1.0
        assert result.home.time_multiplier == pytest.approx(1.20)

    def test_team_lookup_by_side(self) -> None:
        result = evaluate(profile(shots_on_target=5), profile(), minute=60)
        assert result.team(Side.HOME) is result.home
        assert result.team(Side.AWAY) is result.away

    def test_weights_change_the_outcome(self) -> None:
        home, away = profile(shots_on_target=8, shots_off_target=2), profile()
        shot_heavy = WeightSet.from_preset("rule_of_three", "Shot-heavy")

        assert (
            evaluate(home, away, minute=60, weights=shot_heavy).home.unrealised_goals
            > evaluate(home, away, minute=60).home.unrealised_goals
        )

    def test_inputs_are_not_mutated(self) -> None:
        """2.2 wrote its per-team detail into the caller's dictionary."""
        home = profile(shots_on_target=5, goals=1)
        evaluate(home, profile(), minute=60)
        assert home == profile(shots_on_target=5, goals=1)


class TestRuleOfThreeArithmetic:
    def test_shots_off_target_count_a_sixth(self) -> None:
        assert profile(shots_on_target=3, shots_off_target=6).effective_shots_on_target == 4.0

    def test_three_effective_shots_make_one_expected_goal(self) -> None:
        assert profile(shots_on_target=9).expected_goals == pytest.approx(3.0)

    def test_derived_values_reach_the_result(self) -> None:
        result = evaluate(profile(shots_on_target=9, shots_off_target=6), profile(), minute=60)
        assert result.home.effective_shots_on_target == pytest.approx(10.0)
        assert result.home.expected_goals == pytest.approx(10.0 / 3.0)


class TestBuildingFromTimelineStats:
    def test_profile_from_a_snapshot_stat_line(self) -> None:
        stats = TeamStats(shots_on_target=4, shots_off_target=6, possession=62.0)
        built = TeamShotProfile.from_stats(stats, goals=1, kickoff_odds=2.4)

        assert built.shots_on_target == 4
        assert built.shots_off_target == 6
        assert built.goals == 1
        assert built.possession == 62.0
        assert built.kickoff_odds == 2.4

    def test_absent_possession_reads_as_no_reading_not_zero(self) -> None:
        """Zero possession is not a real measurement; it means unreported."""
        assert TeamShotProfile.from_stats(TeamStats()).possession is None


class TestLegacyPoints:
    @pytest.mark.parametrize(
        ("total", "expected"),
        [(-2.0, 0), (0.0, 0), (0.5, 5), (1.0, 5), (2.0, 10), (3.0, 15), (10.0, 25)],
    )
    def test_bands(self, total: float, expected: int) -> None:
        assert legacy_points(_result_totalling(total)) == expected

    def test_the_band_is_capped(self) -> None:
        assert legacy_points(_result_totalling(500.0)) == 25


def _result_totalling(total: float) -> RuleOfThreeResult:
    """A result whose two teams sum to `total`, for exercising the banding."""
    baseline = evaluate(profile(), profile()).home
    half = replace(baseline, unrealised_goals=total / 2)
    return RuleOfThreeResult(home=half, away=half, minute=60)
