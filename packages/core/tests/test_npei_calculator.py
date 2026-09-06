"""NPEI efficiency computation.

New in 3.0. Kalchas 2.2 had no tests for `utils/npei_calculator.py`: computing
a score required `strategy_weights.resolve`, and therefore Postgres.
"""

from __future__ import annotations

import pytest
from conftest import timeline_from
from kalchas_core.match import MatchTimeline, Side
from kalchas_core.npei import NPEI_CAP, cap_signal, compute_npei
from kalchas_core.weights import WeightSet


def timeline_with(
    *,
    home_start: dict[str, int] | None = None,
    home_end: dict[str, int] | None = None,
    away_start: dict[str, int] | None = None,
    away_end: dict[str, int] | None = None,
) -> MatchTimeline:
    """A two-snapshot timeline five minutes apart, at minutes 15 and 20."""
    return timeline_from(
        {
            15: {"home": home_start or {}, "away": away_start or {}},
            20: {"home": home_end or {}, "away": away_end or {}},
        },
        current_minute=20,
    )


class TestScoring:
    def test_perfect_conversion_scores_the_cap(self) -> None:
        """Every attack dangerous, every shot on target, a shot per attack."""
        timeline = timeline_with(
            home_start={"attacks": 0, "dangerous_attacks": 0, "shots_on_target": 0},
            home_end={"attacks": 10, "dangerous_attacks": 10, "shots_on_target": 10},
        )
        snapshot = compute_npei(timeline)

        assert snapshot is not None
        assert snapshot.home.score == pytest.approx(100.0)
        assert snapshot.home.zone.label == "Highly Efficient"

    def test_no_activity_scores_zero(self) -> None:
        snapshot = compute_npei(timeline_with())
        assert snapshot is not None
        assert snapshot.home.score == 0.0

    def test_ratios_are_reported_alongside_the_score(self) -> None:
        timeline = timeline_with(
            home_end={
                "attacks": 20,
                "dangerous_attacks": 10,
                "shots_on_target": 3,
                "shots_off_target": 3,
            },
        )
        snapshot = compute_npei(timeline)

        assert snapshot is not None
        assert snapshot.home.attack_conversion == pytest.approx(0.5)
        assert snapshot.home.shot_accuracy == pytest.approx(0.5)
        assert snapshot.home.shot_creation == pytest.approx(0.3)

    def test_score_is_the_weighted_blend_of_the_three_ratios(self) -> None:
        timeline = timeline_with(
            home_end={
                "attacks": 20,
                "dangerous_attacks": 10,
                "shots_on_target": 3,
                "shots_off_target": 3,
            },
        )
        snapshot = compute_npei(timeline)

        expected = 100.0 * (0.35 * 0.5 + 0.40 * 0.5 + 0.25 * 0.3)
        assert snapshot is not None
        assert snapshot.home.score == pytest.approx(expected)

    def test_teams_are_scored_independently(self) -> None:
        timeline = timeline_with(
            home_end={"attacks": 10, "dangerous_attacks": 10, "shots_on_target": 10},
            away_end={"attacks": 10, "dangerous_attacks": 0, "shots_on_target": 0},
        )
        snapshot = compute_npei(timeline)

        assert snapshot is not None
        assert snapshot.home.score > snapshot.away.score
        assert snapshot.leader is Side.HOME

    def test_leader_is_none_when_teams_are_level(self) -> None:
        snapshot = compute_npei(timeline_with())
        assert snapshot is not None
        assert snapshot.leader is None


class TestActivityGuards:
    """A ratio off one or two events is noise, not a conversion rate."""

    def test_ratio_is_dropped_below_the_attack_guard(self) -> None:
        timeline = timeline_with(home_end={"attacks": 2, "dangerous_attacks": 2})
        snapshot = compute_npei(timeline)

        assert snapshot is not None
        assert snapshot.home.attack_conversion is None
        assert "attack_conversion" in snapshot.home.dropped_ratios

    def test_ratio_is_kept_at_the_guard(self) -> None:
        timeline = timeline_with(home_end={"attacks": 3, "dangerous_attacks": 3})
        snapshot = compute_npei(timeline)

        assert snapshot is not None
        assert snapshot.home.attack_conversion == pytest.approx(1.0)

    def test_shot_guard_is_independent_of_the_attack_guard(self) -> None:
        timeline = timeline_with(
            home_end={"attacks": 10, "dangerous_attacks": 5, "shots_on_target": 1},
        )
        snapshot = compute_npei(timeline)

        assert snapshot is not None
        assert snapshot.home.attack_conversion is not None
        assert snapshot.home.shot_accuracy is None

    def test_a_complete_reading_reports_no_dropped_ratios(self) -> None:
        timeline = timeline_with(
            home_end={
                "attacks": 10,
                "dangerous_attacks": 5,
                "shots_on_target": 2,
                "shots_off_target": 2,
            },
        )
        snapshot = compute_npei(timeline)

        assert snapshot is not None
        assert not snapshot.home.is_partial


class TestDroppedRatiosDepressTheScore:
    """Product rule: missing ratios contribute 0; no weight redistribution."""

    def test_flawless_shooting_below_the_attack_guard_is_capped_at_the_r2_weight(self) -> None:
        timeline = timeline_with(
            home_end={"attacks": 2, "dangerous_attacks": 2, "shots_on_target": 5},
        )
        snapshot = compute_npei(timeline)

        assert snapshot is not None
        assert snapshot.home.shot_accuracy == pytest.approx(1.0)
        assert snapshot.home.score == pytest.approx(40.0)
        assert snapshot.home.score < 100.0
        assert snapshot.home.is_partial

    def test_dropped_ratios_are_named_so_the_caller_can_tell(self) -> None:
        timeline = timeline_with(home_end={"attacks": 2, "shots_on_target": 5})
        snapshot = compute_npei(timeline)

        assert snapshot is not None
        assert set(snapshot.home.dropped_ratios) == {"attack_conversion", "shot_creation"}


class TestTuning:
    def test_weights_shift_the_blend(self) -> None:
        timeline = timeline_with(
            home_end={
                "attacks": 20,
                "dangerous_attacks": 20,
                "shots_on_target": 0,
                "shots_off_target": 10,
            },
        )
        accuracy_biased = WeightSet.from_preset("npei", "Accuracy-biased")

        assert (default := compute_npei(timeline)) is not None
        assert (tuned := compute_npei(timeline, weights=accuracy_biased)) is not None
        assert tuned.home.score < default.home.score

    def test_activity_guards_are_tunable(self) -> None:
        timeline = timeline_with(home_end={"attacks": 2, "dangerous_attacks": 2})
        permissive = WeightSet.from_overrides({"npei": {"min_attacks": 1.0}})

        assert (strict := compute_npei(timeline)) is not None
        assert strict.home.attack_conversion is None

        assert (loose := compute_npei(timeline, weights=permissive)) is not None
        assert loose.home.attack_conversion == pytest.approx(1.0)

    def test_zone_bounds_follow_the_same_weight_set(self) -> None:
        """One WeightSet drives both the score and the band it is labelled with."""
        timeline = timeline_with(
            home_end={"attacks": 10, "dangerous_attacks": 10, "shots_on_target": 4},
        )
        assert (default := compute_npei(timeline)) is not None
        assert default.home.score == pytest.approx(85.0)
        assert default.home.zone.label == "Highly Efficient"

        lenient = WeightSet.from_overrides({"npei": {"zone_max_efficient": 90.0}})
        assert (tuned := compute_npei(timeline, weights=lenient)) is not None
        assert tuned.home.score == pytest.approx(85.0)
        assert tuned.home.zone.label == "Efficient"


class TestNoReading:
    def test_returns_none_when_no_window_resolves(self) -> None:
        assert compute_npei(timeline_from({1: {}, 2: {}}, current_minute=2)) is None

    def test_window_bounds_are_reported(self) -> None:
        snapshot = compute_npei(timeline_with())
        assert snapshot is not None
        assert snapshot.window_start_minute == 15
        assert snapshot.window_end_minute == 20


class TestCapSignal:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(-10.0, 0.0), (0.0, 0.0), (50.0, 50.0), (100.0, 100.0), (120.0, 100.0)],
    )
    def test_clamps_into_range(self, value: float, expected: float) -> None:
        assert cap_signal(value) == expected

    def test_unusable_values_read_as_zero(self) -> None:
        assert cap_signal("nonsense") == 0.0  # type: ignore[arg-type]

    def test_cap_is_the_documented_maximum(self) -> None:
        assert NPEI_CAP == 100.0
