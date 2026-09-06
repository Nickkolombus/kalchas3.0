"""Delta 5min (Strategy 4).

New in 3.0. Kalchas 2.2 had no tests for this strategy, and could not easily
have had any: the arithmetic lived in `utils/delta_calculator.py`, which
mutated a match dictionary in place, and the strategy read the result back out
of that dictionary. Testing the pair meant running them in the right order.

The port was verified against 2.2 by differential comparison over 1,520
timelines -- covering 483 negative-delta cases and 347 possession-fallback
cases -- agreeing on every value, gate decision, and trigger choice
(`scripts/verify_delta_5min_port.py`).
"""

from __future__ import annotations

import pytest
from conftest import timeline_from
from kalchas_core.match import Side
from kalchas_core.strategies.delta_5min import (
    IMPLAUSIBLE_DELTA,
    MINIMUM_MINUTE,
    POSSESSION_FALLBACK_WEIGHT,
    SecondarySignal,
    evaluate,
    passes_corroboration,
)
from kalchas_core.weights import WeightSet

DEFAULTS = WeightSet.defaults()


def window(
    *,
    start: dict[str, int] | None = None,
    end: dict[str, int] | None = None,
    away_start: dict[str, int] | None = None,
    away_end: dict[str, int] | None = None,
    minute: int = 20,
):
    """A five-minute window ending at `minute`, with the given home/away stats."""
    return timeline_from(
        {
            minute - 5: {"home": start or {}, "away": away_start or {}},
            minute: {"home": end or {}, "away": away_end or {}},
        },
        current_minute=minute,
    )


def surge(**stats: int) -> dict[str, int]:
    """Cumulative stats at the end of a window where the home team surged."""
    return {"shots_on_target": 2, "dangerous_attacks": 6, **stats}


class TestCorroborationGate:
    """Dangerous attacks are the noisiest signal, so a spike needs support."""

    def test_shots_plus_enough_secondary_passes(self) -> None:
        assert passes_corroboration(1, 4, DEFAULTS)

    def test_too_little_secondary_fails_regardless_of_shots(self) -> None:
        assert not passes_corroboration(5, 3, DEFAULTS)

    def test_plenty_of_secondary_passes_without_any_shots(self) -> None:
        assert passes_corroboration(0, 4, DEFAULTS)

    def test_nothing_passes_on_no_activity(self) -> None:
        assert not passes_corroboration(0, 0, DEFAULTS)

    def test_the_gate_is_tunable(self) -> None:
        strict = WeightSet.from_preset("delta_5min", "Strict gate")
        assert passes_corroboration(1, 4, DEFAULTS)
        assert not passes_corroboration(1, 4, strict)

    def test_a_permissive_gate_admits_less(self) -> None:
        permissive = WeightSet.from_preset("delta_5min", "Permissive gate")
        assert not passes_corroboration(1, 3, DEFAULTS)
        assert passes_corroboration(1, 3, permissive)


class TestPressure:
    def test_pressure_weights_shots_above_the_secondary_signal(self) -> None:
        """One shot on target counts for more than one dangerous attack.

        The away team is given a shot in both cases so the shots-on-target
        presence check passes and the possession fallback stays out of it.
        """
        one_shot = evaluate(window(end={"shots_on_target": 1}, away_end={"shots_on_target": 1}))
        one_attack = evaluate(window(end={"dangerous_attacks": 1}, away_end={"shots_on_target": 1}))

        assert one_shot is not None and one_attack is not None
        assert one_shot.home.pressure > one_attack.home.pressure

    def test_pressure_is_the_weighted_sum_of_the_two_deltas(self) -> None:
        result = evaluate(window(end=surge()))
        assert result is not None
        assert result.home.pressure == pytest.approx(2 * 2.0 + 6 * 0.5)

    def test_the_coefficients_are_tunable(self) -> None:
        """2.2 hardcoded these and never read the registry, so the slider was dead."""
        timeline = window(end=surge())
        tuned = WeightSet.from_overrides({"delta_5min": {"da_weight": 1.0}})

        assert (default := evaluate(timeline)) is not None
        assert (heavier := evaluate(timeline, weights=tuned)) is not None
        assert heavier.home.pressure > default.home.pressure

    def test_components_are_reported(self) -> None:
        result = evaluate(window(end=surge()))
        assert result is not None
        assert result.home.shots_on_target_delta == 2
        assert result.home.secondary_delta == 6


class TestTriggering:
    def test_a_corroborated_home_surge_triggers(self) -> None:
        result = evaluate(window(end=surge()))
        assert result is not None
        assert result.triggering_team is Side.HOME
        assert result.trigger_value == result.home.pressure

    def test_an_uncorroborated_surge_does_not_trigger(self) -> None:
        result = evaluate(window(end={"shots_on_target": 3, "dangerous_attacks": 1}))
        assert result is not None
        assert result.home.pressure > 0
        assert not result.home.passes_gate
        assert result.triggering_team is None
        assert result.trigger_value == 0.0

    def test_the_away_team_can_trigger(self) -> None:
        result = evaluate(window(away_end=surge()))
        assert result is not None
        assert result.triggering_team is Side.AWAY

    def test_a_tie_on_pressure_goes_to_the_home_team(self) -> None:
        result = evaluate(window(end=surge(), away_end=surge()))
        assert result is not None
        assert result.triggering_team is Side.HOME


class TestAsymmetricTriggerLogic:
    """2.2's branching is asymmetric, and it decides which alerts go out.

    The home team is tested only when it leads on pressure; the away team is
    the sole fallback. Both consequences are pinned here so that neither can
    be "tidied up" into symmetry without a failing test.
    """

    def test_a_leading_home_team_that_fails_the_gate_hands_off_to_away(self) -> None:
        result = evaluate(
            window(
                end={"shots_on_target": 5, "dangerous_attacks": 1},
                away_end={"shots_on_target": 1, "dangerous_attacks": 5},
            )
        )
        assert result is not None
        assert result.home.pressure > result.away.pressure
        assert not result.home.passes_gate
        assert result.triggering_team is Side.AWAY, "weaker side should inherit the alert"

    def test_a_qualifying_home_team_is_ignored_when_away_leads_and_fails(self) -> None:
        result = evaluate(
            window(
                end={"shots_on_target": 1, "dangerous_attacks": 5},
                away_end={"shots_on_target": 8, "dangerous_attacks": 0},
            )
        )
        assert result is not None
        assert result.away.pressure > result.home.pressure
        assert not result.away.passes_gate
        assert result.home.passes_gate, "home would qualify on its own"
        assert result.triggering_team is None, "but 2.2 never considers it"


class TestNegativeDeltas:
    """Unclamped, unlike every other strategy. See `evaluate`."""

    def test_a_downward_revision_produces_negative_pressure(self) -> None:
        result = evaluate(
            window(start={"shots_on_target": 4, "dangerous_attacks": 8}, end={"shots_on_target": 1})
        )
        assert result is not None
        assert result.home.shots_on_target_delta < 0
        assert result.home.pressure < 0

    def test_negative_pressure_cannot_trigger_even_if_the_gate_passes(self) -> None:
        result = evaluate(
            window(
                start={"shots_on_target": 6},
                end={"shots_on_target": 1, "dangerous_attacks": 5},
            )
        )
        assert result is not None
        assert result.home.passes_gate
        assert result.home.pressure < 0
        assert result.triggering_team is None

    def test_implausible_deltas_are_flagged_rather_than_only_logged(self) -> None:
        result = evaluate(window(end={"shots_on_target": IMPLAUSIBLE_DELTA + 5}))
        assert result is not None
        assert result.home.is_implausible

    def test_ordinary_deltas_are_not_flagged(self) -> None:
        result = evaluate(window(end=surge()))
        assert result is not None
        assert not result.home.is_implausible


class TestPossessionFallback:
    """Used only when neither team has any shots on target on record."""

    def test_falls_back_when_no_shots_exist_at_all(self) -> None:
        result = evaluate(
            window(
                start={"possession": 40, "dangerous_attacks": 3},
                end={"possession": 55, "dangerous_attacks": 9},
                away_start={"possession": 60},
                away_end={"possession": 45},
            )
        )
        assert result is not None
        assert result.secondary_signal is SecondarySignal.POSSESSION

    def test_the_fallback_scores_possession_change_at_a_low_weight(self) -> None:
        result = evaluate(
            window(
                start={"possession": 40},
                end={"possession": 55},
                away_start={"possession": 60},
                away_end={"possession": 45},
            )
        )
        assert result is not None
        assert result.home.pressure == pytest.approx(15 * POSSESSION_FALLBACK_WEIGHT)
        assert result.home.shots_on_target_delta == 0

    def test_a_single_shot_on_target_anywhere_disables_the_fallback(self) -> None:
        result = evaluate(
            window(
                start={"possession": 40},
                end={"possession": 55},
                away_end={"shots_on_target": 1},
            )
        )
        assert result is not None
        assert result.secondary_signal is SecondarySignal.DANGEROUS_ATTACKS

    def test_no_shots_and_no_possession_is_no_reading(self) -> None:
        assert evaluate(window(end={"dangerous_attacks": 9})) is None


class TestNoReading:
    def test_a_match_younger_than_the_minimum(self) -> None:
        timeline = timeline_from({1: {}, 2: {}}, current_minute=2)
        assert timeline.current_minute < MINIMUM_MINUTE
        assert evaluate(timeline) is None

    def test_current_minute_never_recorded(self) -> None:
        assert evaluate(timeline_from({10: {}, 11: {}}, current_minute=40)) is None

    def test_window_bounds_are_reported(self) -> None:
        result = evaluate(window(end=surge(), minute=30))
        assert result is not None
        assert result.window_start_minute == 25
        assert result.window_end_minute == 30


class TestSecondarySignalChoice:
    def test_shots_off_target_can_stand_in_for_dangerous_attacks(self) -> None:
        timeline = window(end={"shots_on_target": 2, "shots_off_target": 6, "dangerous_attacks": 0})
        result = evaluate(timeline, secondary_signal=SecondarySignal.SHOTS_OFF_TARGET)

        assert result is not None
        assert result.home.secondary_delta == 6
        assert result.triggering_team is Side.HOME

    def test_the_chosen_signal_is_recorded(self) -> None:
        result = evaluate(window(end=surge()), secondary_signal=SecondarySignal.SHOTS_OFF_TARGET)
        assert result is not None
        assert result.secondary_signal is SecondarySignal.SHOTS_OFF_TARGET
