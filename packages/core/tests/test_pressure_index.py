"""Pressure Index (Strategy 2).

New in 3.0. Kalchas 2.2 had no tests for this strategy; its service object was
constructed at module import and read a JSON config file in the constructor,
so importing it touched the filesystem.

The port was additionally verified against 2.2 by differential comparison over
342 generated timelines spanning both halves, extra time, gapped polling, and
every scoreline band (`scripts/verify_pressure_index_port.py`), agreeing to
within 1e-9 on both teams.
"""

from __future__ import annotations

import pytest
from conftest import timeline_from
from kalchas_core.match import MatchTimeline, Side, TeamDeltas
from kalchas_core.strategies.pressure_index import (
    MAX_PRESSURE,
    MINIMUM_MINUTE,
    TeamPressure,
    evaluate,
    game_state_modifier,
    pressure_series,
    raw_pressure,
    time_multiplier,
)
from kalchas_core.weights import WeightSet

DEFAULTS = WeightSet.defaults()


def deltas(**kwargs: int) -> TeamDeltas:
    base = {
        "attacks": 0,
        "dangerous_attacks": 0,
        "shots": 0,
        "shots_on_target": 0,
        "corners": 0,
    }
    return TeamDeltas(**{**base, **kwargs})


def busy_timeline(
    *,
    start_minute: int = 10,
    end_minute: int = 20,
    home: dict[str, int] | None = None,
    away: dict[str, int] | None = None,
) -> MatchTimeline:
    """A timeline where the given activity happens between the two minutes."""
    return timeline_from(
        {
            start_minute: {"home": {}, "away": {}},
            end_minute: {"home": home or {}, "away": away or {}},
        },
        current_minute=end_minute,
    )


class TestRawPressure:
    def test_no_activity_is_no_pressure(self) -> None:
        assert raw_pressure(deltas(), DEFAULTS) == 0.0

    def test_shots_on_target_are_the_biggest_contributor(self) -> None:
        one_of_each = {
            "shots_on_target": raw_pressure(deltas(shots=1, shots_on_target=1), DEFAULTS),
            "shots_off_target": raw_pressure(deltas(shots=1), DEFAULTS),
            "corners": raw_pressure(deltas(corners=1), DEFAULTS),
            "dangerous_attacks": raw_pressure(deltas(dangerous_attacks=1), DEFAULTS),
        }
        assert one_of_each["shots_on_target"] == max(one_of_each.values())
        assert one_of_each["dangerous_attacks"] == min(one_of_each.values())

    def test_scaling_has_diminishing_returns(self) -> None:
        """Square-rooted, so four shots is twice one shot, not four times."""
        one = raw_pressure(deltas(shots=1, shots_on_target=1), DEFAULTS)
        four = raw_pressure(deltas(shots=4, shots_on_target=4), DEFAULTS)
        assert four == pytest.approx(2 * one)

    def test_shots_off_target_are_derived_from_the_shot_totals(self) -> None:
        assert raw_pressure(deltas(shots=5, shots_on_target=2), DEFAULTS) == pytest.approx(
            raw_pressure(deltas(shots=2, shots_on_target=2), DEFAULTS)
            + raw_pressure(deltas(shots=3), DEFAULTS)
        )

    def test_pressure_is_capped(self) -> None:
        assert raw_pressure(deltas(shots=999, shots_on_target=999, corners=999), DEFAULTS) == (
            MAX_PRESSURE
        )

    def test_weights_change_the_balance(self) -> None:
        shots = deltas(shots=4, shots_on_target=4)
        emphasised = WeightSet.from_preset("pressure_index", "Shots emphasized")
        assert raw_pressure(shots, emphasised) > raw_pressure(shots, DEFAULTS)


class TestGameState:
    def test_level_is_neutral(self) -> None:
        assert game_state_modifier(1, 1) == 1.0

    def test_chasing_counts_for_more_than_leading(self) -> None:
        assert game_state_modifier(0, 1) > 1.0 > game_state_modifier(1, 0)

    def test_a_bigger_lead_discounts_further(self) -> None:
        assert game_state_modifier(3, 0) < game_state_modifier(1, 0)

    def test_two_down_is_worth_slightly_less_than_one_down(self) -> None:
        """Two behind is a bigger hill, so the signal is trusted marginally less."""
        assert game_state_modifier(0, 2) < game_state_modifier(0, 1)


class TestTimeMultiplier:
    @pytest.mark.parametrize(
        ("minute", "expected"),
        [(30, 0.90), (31, 1.00), (60, 1.00), (61, 1.10), (75, 1.10), (76, 1.20)],
    )
    def test_bands(self, minute: int, expected: float) -> None:
        assert time_multiplier(minute, DEFAULTS) == pytest.approx(expected)

    @pytest.mark.parametrize("minute", [None, 0])
    def test_unknown_minute_is_neutral(self, minute: int | None) -> None:
        assert time_multiplier(minute, DEFAULTS) == 1.0


class TestEvaluate:
    def test_activity_produces_pressure(self) -> None:
        result = evaluate(busy_timeline(home={"shots_on_target": 3, "corners": 2}))
        assert result is not None
        assert result.home.pressure > 0
        assert result.away.pressure == 0

    def test_teams_are_scored_independently(self) -> None:
        result = evaluate(busy_timeline(home={"shots_on_target": 4}, away={"shots_on_target": 1}))
        assert result is not None
        assert result.home.pressure > result.away.pressure
        assert result.leader is Side.HOME

    def test_total_is_the_trigger_value(self) -> None:
        result = evaluate(busy_timeline(home={"shots_on_target": 3}, away={"corners": 2}))
        assert result is not None
        assert result.total == pytest.approx(result.home.pressure + result.away.pressure)

    def test_leader_is_none_when_level(self) -> None:
        result = evaluate(busy_timeline(home={"shots_on_target": 2}, away={"shots_on_target": 2}))
        assert result is not None
        assert result.leader is None

    def test_the_scoreline_shapes_the_reading(self) -> None:
        timeline = busy_timeline(home={"shots_on_target": 3})

        chasing = evaluate(timeline, home_goals=0, away_goals=1)
        leading = evaluate(timeline, home_goals=1, away_goals=0)

        assert chasing is not None and leading is not None
        assert chasing.home.pressure > leading.home.pressure

    def test_the_contributing_factors_are_reported(self) -> None:
        result = evaluate(
            busy_timeline(end_minute=80, home={"shots_on_target": 3}),
            home_goals=0,
            away_goals=1,
        )
        assert result is not None
        assert result.home.game_state_modifier == pytest.approx(1.15)
        assert result.home.time_multiplier == pytest.approx(1.20)
        assert result.home.deltas.shots_on_target == 3

    def test_pressure_is_capped_after_the_modifiers(self) -> None:
        """A maxed raw score times a chasing team's 1.15 must still land at 100."""
        result = evaluate(
            busy_timeline(end_minute=80, home={"shots_on_target": 99, "shots_off_target": 99}),
            home_goals=0,
            away_goals=1,
        )
        assert result is not None
        assert result.home.raw_pressure == MAX_PRESSURE
        assert result.home.pressure == MAX_PRESSURE

    def test_window_bounds_are_reported(self) -> None:
        result = evaluate(busy_timeline(start_minute=12, end_minute=20))
        assert result is not None
        assert result.window_start_minute == 12
        assert result.window_end_minute == 20
        assert result.window_minutes == 8

    def test_team_lookup_by_side(self) -> None:
        result = evaluate(busy_timeline(home={"shots_on_target": 1}))
        assert result is not None
        assert result.team(Side.HOME) is result.home
        assert isinstance(result.team(Side.AWAY), TeamPressure)


class TestBurst:
    def test_a_recent_surge_registers(self) -> None:
        timeline = timeline_from(
            {
                10: {"home": {}},
                18: {"home": {"shots_on_target": 1}},
                20: {"home": {"shots_on_target": 5, "corners": 3}},
            },
            current_minute=20,
        )
        result = evaluate(timeline)
        assert result is not None
        assert result.home.burst > 0

    def test_steady_early_activity_does_not_register_as_a_burst(self) -> None:
        timeline = timeline_from(
            {
                10: {"home": {}},
                12: {"home": {"shots_on_target": 5}},
                20: {"home": {"shots_on_target": 5}},
            },
            current_minute=20,
        )
        result = evaluate(timeline)
        assert result is not None
        assert result.home.pressure > 0
        assert result.home.burst == 0.0


class TestNoReading:
    """None means no reading, not a reading of zero pressure."""

    def test_a_match_younger_than_the_minimum(self) -> None:
        timeline = timeline_from({1: {}, 2: {}}, current_minute=2)
        assert timeline.current_minute < MINIMUM_MINUTE
        assert evaluate(timeline) is None

    def test_a_partial_window_is_still_a_reading(self) -> None:
        """The ten-minute window must not blank the first ten minutes of a match."""
        result = evaluate(busy_timeline(start_minute=1, end_minute=6, home={"corners": 2}))
        assert result is not None
        assert result.home.pressure > 0

    def test_current_minute_never_recorded(self) -> None:
        assert evaluate(timeline_from({10: {}, 11: {}}, current_minute=40)) is None

    def test_no_earlier_minute_at_all(self) -> None:
        assert evaluate(timeline_from({20: {}}, current_minute=20)) is None

    def test_a_stale_snapshot_is_still_used_within_the_fallback(self) -> None:
        """A gap in polling degrades the reading rather than dropping it."""
        result = evaluate(
            timeline_from(
                {28: {"home": {}}, 40: {"home": {"shots_on_target": 3}}}, current_minute=40
            )
        )
        assert result is not None
        assert result.window_start_minute == 28


class TestPeriodClamp:
    def test_a_window_after_the_interval_excludes_the_first_half(self) -> None:
        """The ten-minute lookback must not count first-half events as current."""
        timeline = timeline_from(
            {
                44: {"home": {"shots_on_target": 0}},
                48: {"home": {"shots_on_target": 0}},
                51: {"home": {"shots_on_target": 0}},
                55: {"home": {"shots_on_target": 4}},
            },
            current_minute=55,
        )
        result = evaluate(timeline)

        assert result is not None
        assert result.window_start_minute == 51, "window reached back across half-time"

    def test_the_clamp_lifts_once_the_half_is_underway(self) -> None:
        timeline = timeline_from({m: {"home": {}} for m in range(51, 71)}, current_minute=70)
        result = evaluate(timeline)

        assert result is not None
        assert result.window_start_minute == 60


class TestPressureSeries:
    def test_series_length_matches_up_to_minute(self) -> None:
        timeline = busy_timeline(
            start_minute=10,
            end_minute=20,
            home={"shots_on_target": 3, "dangerous_attacks": 8},
        )
        series = pressure_series(timeline, Side.HOME, up_to_minute=20, window_minutes=10)
        assert len(series) == 21
        assert series[9] == 0.0  # no snapshot before activity
        assert series[20] > 0.0

    def test_negative_up_to_returns_empty(self) -> None:
        timeline = busy_timeline()
        assert pressure_series(timeline, Side.HOME, up_to_minute=-1, window_minutes=10) == []

    def test_missing_minutes_read_as_zero(self) -> None:
        timeline = timeline_from(
            {10: {"home": {}}, 20: {"home": {"shots_on_target": 2}}},
            current_minute=20,
        )
        series = pressure_series(timeline, Side.HOME, up_to_minute=20, window_minutes=10)
        assert series[15] == 0.0
        assert series[20] > 0.0
