"""Omega (Strategy 6).

New in 3.0; originally verified against 2.2 by differential comparison. Accel
and baseline are now window-normalised (intentional 3.0 divergence — see
module docstring and `scripts/verify_omega_port.py`).
"""

from __future__ import annotations

import math

import pytest
from conftest import timeline_from
from kalchas_core.match import MatchTimeline, Side
from kalchas_core.strategies.omega import (
    DEFAULT_ANGLE_SCALE,
    DEFAULT_MIN_ACCELERATION,
    FLAT_BAND_DEGREES,
    OmegaSettings,
    OmegaState,
    TeamOmega,
    classify,
    degrees_to_slope,
    evaluate,
    slope_to_degrees,
)
from kalchas_core.weights import WeightSet

DEFAULTS = OmegaSettings()
LOOSE = OmegaSettings(min_acceleration=0.01, min_baseline_slope=-1.0, min_level=0.0)


def shaped(minute: int, rate) -> MatchTimeline:
    """A timeline where home activity per minute follows `rate(progress)`.

    Rates are kept low on purpose. Pressure is square-root scaled and clamped
    at 100, so a busy fixture saturates both windows and the acceleration
    inverts. The shapes below were picked by sweeping activity profiles and
    reading off the resulting acceleration.
    """
    minutes: dict[int, dict] = {}
    totals = {"shots_on_target": 0.0, "dangerous_attacks": 0.0, "corners": 0.0}

    for m in range(1, minute + 1):
        step = rate(m / minute)
        totals["shots_on_target"] += step * 0.3
        totals["dangerous_attacks"] += step * 1.2
        totals["corners"] += step * 0.15
        minutes[m] = {
            "home": {stat: int(value) for stat, value in totals.items()},
            "away": {},
        }
    return timeline_from(minutes, current_minute=minute)


def surging(minute: int = 40) -> MatchTimeline:
    """A gradual quadratic build, which is what actually accelerates."""
    return shaped(minute, lambda p: 1.5 * p**2)


def steady(minute: int = 40) -> MatchTimeline:
    return shaped(minute, lambda _: 1.0)


def fading(minute: int = 40) -> MatchTimeline:
    return shaped(minute, lambda p: 1.5 * (1.0 - p) ** 2)


def late_burst(minute: int = 40, *, length: int = 5, rate: float = 2.0) -> MatchTimeline:
    """Nothing, then a sharp burst confined to the last few minutes."""
    return shaped(minute, lambda p: rate if p > 1 - length / minute else 0.0)


class TestAngleConversion:
    def test_the_conversions_are_inverses(self) -> None:
        for slope in (-12.0, -1.0, 0.0, 3.7, 20.0):
            degrees = slope_to_degrees(slope, DEFAULT_ANGLE_SCALE)
            assert degrees_to_slope(degrees, DEFAULT_ANGLE_SCALE) == pytest.approx(slope)

    def test_zero_slope_is_zero_degrees(self) -> None:
        assert slope_to_degrees(0.0, DEFAULT_ANGLE_SCALE) == 0.0

    def test_the_default_threshold_is_about_twenty_degrees(self) -> None:
        """The linear default was chosen to match the angle it replaced."""
        assert slope_to_degrees(DEFAULT_MIN_ACCELERATION, DEFAULT_ANGLE_SCALE) == pytest.approx(
            20.0, abs=0.05
        )

    def test_angles_stay_bounded_however_steep_the_slope(self) -> None:
        assert abs(slope_to_degrees(1e9, DEFAULT_ANGLE_SCALE)) < 90.0

    def test_a_zero_scale_does_not_divide_by_zero(self) -> None:
        assert math.isfinite(slope_to_degrees(5.0, 0.0))

    def test_a_larger_scale_flattens_the_angle(self) -> None:
        assert slope_to_degrees(5.0, 30.0) < slope_to_degrees(5.0, 10.0)


class TestStateClassification:
    def test_rising_and_accelerating_is_a_confirmed_surge(self) -> None:
        assert classify(20.0, 10.0) is OmegaState.CONFIRMED_SURGE

    def test_accelerating_against_a_falling_trend_is_only_a_spike(self) -> None:
        assert classify(20.0, -10.0) is OmegaState.SPIKE_ONLY

    def test_rising_but_decelerating_is_softening(self) -> None:
        assert classify(-20.0, 10.0) is OmegaState.SOFTENING

    def test_falling_on_both_measures_is_collapsing(self) -> None:
        assert classify(-20.0, -10.0) is OmegaState.COLLAPSING

    def test_small_movements_on_both_measures_are_flat(self) -> None:
        assert classify(1.0, 1.0) is OmegaState.FLAT

    def test_the_flat_band_is_configurable(self) -> None:
        assert classify(10.0, 3.0, flat_band=FLAT_BAND_DEGREES) is OmegaState.CONFIRMED_SURGE
        assert classify(10.0, 3.0, flat_band=20.0) is OmegaState.FLAT

    def test_a_zero_baseline_with_positive_acceleration_is_a_spike(self) -> None:
        assert classify(20.0, 0.0) is OmegaState.SPIKE_ONLY


class TestSettings:
    def test_the_slow_window_is_forced_above_the_fast_one(self) -> None:
        """Their derivatives are differenced, so equal windows would cancel."""
        settings = OmegaSettings.from_stored(fast_window=12, slow_window=4)
        assert settings.slow_window > settings.fast_window

    def test_windows_are_bounded(self) -> None:
        settings = OmegaSettings.from_stored(fast_window=999, slow_window=999)
        assert settings.fast_window == 30
        assert settings.slow_window == 45

    def test_the_angle_scale_cannot_be_zero(self) -> None:
        assert OmegaSettings.from_stored(angle_scale=0.0).angle_scale > 0

    def test_an_angle_threshold_converts_to_a_slope(self) -> None:
        """Saved settings predate the linear thresholds, so both shapes work."""
        settings = OmegaSettings.from_stored(theta_threshold=20.0, angle_scale=DEFAULT_ANGLE_SCALE)
        assert settings.min_acceleration == pytest.approx(DEFAULT_MIN_ACCELERATION, abs=0.01)

    def test_a_linear_threshold_wins_over_an_angle(self) -> None:
        settings = OmegaSettings.from_stored(min_acceleration=0.9, theta_threshold=45.0)
        assert settings.min_acceleration == 0.9

    def test_the_angle_conversion_uses_the_bounded_scale(self) -> None:
        """Order matters: the scale is clamped before the angle is converted."""
        settings = OmegaSettings.from_stored(theta_threshold=20.0, angle_scale=9999.0)
        assert settings.angle_scale == 50.0
        # 20° at k=50 is ~18 PI/min; the normalised accel ceiling clamps it.
        assert settings.min_acceleration == 10.0

    def test_thresholds_are_bounded(self) -> None:
        settings = OmegaSettings.from_stored(
            min_acceleration=1e6, min_baseline_slope=-1e6, min_level=1e6
        )
        assert settings.min_acceleration == 10.0
        assert settings.min_baseline_slope == -5.0
        assert settings.min_level == 100.0

    def test_the_angle_properties_round_trip_the_thresholds(self) -> None:
        settings = OmegaSettings()
        assert settings.theta_threshold == pytest.approx(20.0, abs=0.05)
        assert settings.alpha_floor == 0.0

    def test_the_minimum_minute_covers_both_windows(self) -> None:
        settings = OmegaSettings(slow_window=10, derivative_window=3)
        assert settings.minimum_minute == 13


class TestEvaluate:
    def test_a_surge_is_detected(self) -> None:
        result = evaluate(surging(), settings=LOOSE)
        assert result is not None
        assert result.triggering_team is Side.HOME

    def test_the_quiet_team_does_not_trigger(self) -> None:
        result = evaluate(surging(), settings=LOOSE)
        assert result is not None
        away = result.away
        assert away is not None
        assert not away.meets(LOOSE)

    def test_a_surge_accelerates(self) -> None:
        result = evaluate(surging(), settings=LOOSE)
        assert result is not None
        assert result.home is not None
        assert result.home.acceleration > 0

    def test_fading_pressure_does_not_trigger(self) -> None:
        result = evaluate(fading(), settings=LOOSE)
        assert result is not None
        assert result.home is not None
        assert not result.home.meets(LOOSE)

    def test_steady_pressure_is_not_a_surge(self) -> None:
        result = evaluate(steady(), settings=DEFAULTS)
        assert result is not None
        assert result.triggering_team is None

    def test_the_trigger_value_is_the_acceleration(self) -> None:
        result = evaluate(surging(), settings=LOOSE)
        assert result is not None
        side = result.triggering_team
        assert side is not None
        reading = result.team(side)
        assert reading is not None
        assert result.trigger_value == reading.acceleration

    def test_nothing_qualifying_gives_a_zero_trigger_value(self) -> None:
        result = evaluate(steady(), settings=DEFAULTS)
        assert result is not None
        assert result.trigger_value == 0.0

    def test_the_angles_agree_with_the_slopes(self) -> None:
        result = evaluate(surging(), settings=LOOSE)
        assert result is not None
        home = result.home
        assert home is not None
        assert home.theta == pytest.approx(
            round(slope_to_degrees(home.acceleration, LOOSE.angle_scale), 2), abs=0.02
        )


class TestTriggerGate:
    def _reading(self, acceleration: float, baseline: float, level: float) -> TeamOmega:
        return TeamOmega(
            acceleration=acceleration,
            baseline_slope=baseline,
            level=level,
            theta=0.0,
            alpha=0.0,
            fast_slope=0.0,
            slow_slope=baseline,
            fast_level=0.0,
            state=OmegaState.CONFIRMED_SURGE,
        )

    def test_all_three_conditions_are_required(self) -> None:
        settings = OmegaSettings(min_acceleration=0.2, min_baseline_slope=0.0, min_level=20.0)
        assert self._reading(0.3, 0.1, 30.0).meets(settings)
        assert not self._reading(0.1, 0.1, 30.0).meets(settings), "acceleration too low"
        assert not self._reading(0.3, -0.1, 30.0).meets(settings), "baseline falling"
        assert not self._reading(0.3, 0.1, 10.0).meets(settings), "level too low"

    def test_acceleration_must_exceed_rather_than_meet_the_threshold(self) -> None:
        settings = OmegaSettings(min_acceleration=0.2, min_baseline_slope=0.0, min_level=0.0)
        assert not self._reading(0.2, 0.1, 50.0).meets(settings)
        assert self._reading(0.201, 0.1, 50.0).meets(settings)

    def test_the_level_floor_is_inclusive(self) -> None:
        settings = OmegaSettings(min_acceleration=0.05, min_baseline_slope=0.0, min_level=20.0)
        assert self._reading(0.1, 0.1, 20.0).meets(settings)

    def test_a_spike_on_a_falling_baseline_is_rejected(self) -> None:
        """The point of the baseline gate: a blip inside a fade is not a surge."""
        settings = OmegaSettings(min_acceleration=0.05, min_baseline_slope=0.0, min_level=0.0)
        assert not self._reading(2.0, -0.05, 90.0).meets(settings)


class TestDataClamp:
    """Omega evaluates at the last recorded minute, not the live minute."""

    def test_it_evaluates_at_the_last_recorded_minute(self) -> None:
        timeline = surging(40)
        stale = MatchTimeline(minutes=timeline.minutes, current_minute=55)
        result = evaluate(stale, settings=LOOSE)
        assert result is not None
        assert result.minute == 40

    def test_a_reading_survives_a_polling_gap(self) -> None:
        timeline = surging(40)
        stale = MatchTimeline(minutes=timeline.minutes, current_minute=52)
        assert evaluate(stale, settings=LOOSE) is not None

    def test_minutes_beyond_the_live_clock_are_ignored(self) -> None:
        timeline = surging(40)
        early = MatchTimeline(minutes=timeline.minutes, current_minute=20)
        result = evaluate(early, settings=LOOSE)
        assert result is not None
        assert result.minute == 20


class TestNoReading:
    def test_a_match_too_young_for_the_slow_window(self) -> None:
        assert evaluate(surging(10), settings=DEFAULTS) is None

    def test_an_empty_timeline(self) -> None:
        assert evaluate(MatchTimeline.from_raw({}, 60)) is None

    def test_a_timeline_with_no_minutes_at_or_below_the_clock(self) -> None:
        timeline = surging(40)
        assert evaluate(MatchTimeline(minutes=timeline.minutes, current_minute=0)) is None

    def test_a_wider_slow_window_raises_the_minimum_minute(self) -> None:
        settings = OmegaSettings(fast_window=10, slow_window=30, derivative_window=5)
        assert evaluate(surging(20), settings=settings) is None
        assert evaluate(surging(50), settings=settings) is not None


class TestWeightTuning:
    def test_the_flat_band_comes_from_the_weight_set(self) -> None:
        timeline = steady(40)
        wide = WeightSet.from_overrides({"omega": {"flat_band": 20.0}})
        result = evaluate(timeline, settings=LOOSE, weights=wide)
        assert result is not None
        assert result.home is not None
        assert result.home.state is OmegaState.FLAT

    def test_the_flat_band_does_not_affect_firing(self) -> None:
        """The state label is diagnostic; the thresholds decide."""
        timeline = surging()
        wide = WeightSet.from_overrides({"omega": {"flat_band": 89.0}})
        assert (
            evaluate(timeline, settings=LOOSE, weights=wide).triggering_team
            == evaluate(timeline, settings=LOOSE).triggering_team
        )


class TestZeroAccelerationWithRisingBaseline:
    """Zero accel + rising baseline is softening, not collapsing."""

    def test_the_bare_classifier_agrees(self) -> None:
        assert classify(0.0, 30.0) is OmegaState.SOFTENING
        assert classify(-1.0, 30.0) is OmegaState.SOFTENING
        assert classify(0.0, -30.0) is OmegaState.COLLAPSING


class TestLateBurstIsPositiveAcceleration:
    """A burst confined to the fast window used to read as zero accel.

    Both raw slopes matched, so unnormalised accel cancelled. After dividing
    by window length the same raw slope is a higher *rate* on the fast window,
    which is the correct surge reading.
    """

    def test_a_burst_inside_the_fast_window_accelerates(self) -> None:
        result = evaluate(late_burst(), settings=LOOSE)
        assert result is not None
        home = result.home
        assert home is not None
        assert home.fast_slope == pytest.approx(home.slow_slope)
        assert home.acceleration > 0
        assert home.baseline_slope > 0

    def test_and_is_labelled_a_confirmed_surge(self) -> None:
        result = evaluate(late_burst(), settings=LOOSE)
        assert result is not None
        home = result.home
        assert home is not None
        assert home.state is OmegaState.CONFIRMED_SURGE


class TestWindowNormalisation:
    """Slopes are divided by window length before differencing.

    A flat activity rate should sit near zero accel (not strongly negative).
    A quadratic surge should read positive.
    """

    def test_the_slow_window_still_sits_above_the_fast_one(self) -> None:
        result = evaluate(steady(), settings=LOOSE)
        assert result is not None
        home = result.home
        assert home is not None
        assert home.level > home.fast_level

    def test_steady_activity_is_near_zero_acceleration(self) -> None:
        result = evaluate(steady(), settings=LOOSE)
        assert result is not None
        home = result.home
        assert home is not None
        assert abs(home.acceleration) < 0.15

    def test_a_quadratic_surge_reads_positive(self) -> None:
        result = evaluate(surging(), settings=LOOSE)
        assert result is not None
        home = result.home
        assert home is not None
        assert home.baseline_slope > 0
        assert home.acceleration > 0


class TestRounding:
    """2.2 rounded before testing the thresholds, so rounding can decide a fire."""

    def test_readings_are_rounded(self) -> None:
        result = evaluate(surging(), settings=LOOSE)
        assert result is not None
        home = result.home
        assert home is not None
        assert home.acceleration == round(home.acceleration, 3)
        assert home.level == round(home.level, 1)
        assert home.theta == round(home.theta, 2)
