"""Delta 5min (Strategy 4) -- short-horizon pressure spikes.

    Δ5 = ΔSOT × sot_weight + ΔSecondary × da_weight

A deliberately blunt counterpart to the Pressure Index: no square-root
scaling, no game-state or time modifiers, just raw five-minute deltas. It
catches surges that the Pressure Index's ten-minute window smooths away.

A surge only fires if it clears a corroboration gate, so a single flurry of
dangerous attacks -- the noisiest signal the feed carries -- cannot trigger an
alert on its own.

Ported from Kalchas 2.2, where this strategy was split in two: the arithmetic
lived in `utils/delta_calculator.py`, which the background monitor ran to write
a `delta_5min_pressure` key into the match dictionary, and
`strategies/strategy_004_delta_5min/formula.py` read that key back out and
applied the gate. If the monitor had not run first, the strategy silently
evaluated to nothing. Both halves are here, and it computes what it needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from kalchas_core.match import (
    ActivityWindow,
    MatchTimeline,
    Side,
    TeamDeltas,
    WindowClamp,
    resolve_window,
)
from kalchas_core.weights import WeightSet

STRATEGY_KEY = "delta_5min"

WINDOW_MINUTES = 5
MINIMUM_MINUTE = 5

# 2.2 warned when a five-minute delta exceeded this, on the grounds that no
# team takes ten shots on target in five minutes. It only logged; the value was
# used regardless. Reported on the result here so a caller can act on it.
IMPLAUSIBLE_DELTA = 10


# Weight applied in the possession fallback. Hardcoded in 2.2 and not one of
# the registered coefficients, so it is not admin-tunable here either.
POSSESSION_FALLBACK_WEIGHT = 0.1


class SecondarySignal(StrEnum):
    """Which stat stood in for the second term.

    The feed does not carry dangerous attacks for every competition, so a
    lower-quality substitute is accepted rather than skipping the match.
    """

    DANGEROUS_ATTACKS = "dangerous_attacks"
    SHOTS_OFF_TARGET = "shots_off_target"

    POSSESSION = "possession"
    """Last resort, used only when neither team has any shots on target on
    record. Scored on the change in possession share at a much lower weight,
    with the shots term forced to zero."""


@dataclass(frozen=True, slots=True)
class TeamDelta:
    """One team's five-minute pressure delta."""

    pressure: float
    shots_on_target_delta: int
    secondary_delta: int
    passes_gate: bool

    @property
    def is_implausible(self) -> bool:
        """Whether either delta is large enough to suggest corrupt feed data."""
        return (
            abs(self.shots_on_target_delta) > IMPLAUSIBLE_DELTA
            or abs(self.secondary_delta) > IMPLAUSIBLE_DELTA
        )


@dataclass(frozen=True, slots=True)
class Delta5MinResult:
    """Both teams' deltas, and which of them (if either) triggers."""

    home: TeamDelta
    away: TeamDelta
    secondary_signal: SecondarySignal
    window_start_minute: int
    window_end_minute: int

    def team(self, side: Side) -> TeamDelta:
        return self.home if side is Side.HOME else self.away

    @property
    def triggering_team(self) -> Side | None:
        """The qualifying team with the strongest pressure, or None.

        Fair rule (3.0): any side with ``pressure > 0`` that passes the
        corroboration gate is eligible. Highest pressure wins; ties go home.
        """
        eligible = [
            side
            for side in (Side.HOME, Side.AWAY)
            if self.team(side).pressure > 0 and self.team(side).passes_gate
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda side: (self.team(side).pressure, side is Side.HOME))

    @property
    def trigger_value(self) -> float:
        """The value compared against the alert threshold, or 0 if nothing fires."""
        side = self.triggering_team
        return self.team(side).pressure if side else 0.0


def passes_corroboration(
    shots_on_target_delta: int,
    secondary_delta: int,
    weights: WeightSet,
) -> bool:
    """Whether a spike is corroborated well enough to alert on.

    Requires a floor of secondary activity, plus *either* a shot on target or
    a clearly higher secondary count. Dangerous attacks alone are too noisy to
    trust, but a lot of them is still evidence.
    """
    minimum_secondary = int(weights.get(STRATEGY_KEY, "min_da_delta"))
    minimum_shots = int(weights.get(STRATEGY_KEY, "min_sot_delta"))
    fallback_secondary = int(weights.get(STRATEGY_KEY, "fallback_da_delta"))

    if secondary_delta < minimum_secondary:
        return False
    return shots_on_target_delta >= minimum_shots or secondary_delta >= fallback_secondary


def _secondary_delta(deltas: TeamDeltas, signal: SecondarySignal) -> int:
    if signal is SecondarySignal.DANGEROUS_ATTACKS:
        return deltas.dangerous_attacks
    return deltas.shots_off_target


def _team_delta(
    deltas: TeamDeltas,
    signal: SecondarySignal,
    weights: WeightSet,
) -> TeamDelta:
    shots_delta = deltas.shots_on_target
    secondary = _secondary_delta(deltas, signal)

    pressure = shots_delta * weights.get(STRATEGY_KEY, "sot_weight") + secondary * weights.get(
        STRATEGY_KEY, "da_weight"
    )

    return TeamDelta(
        pressure=pressure,
        shots_on_target_delta=shots_delta,
        secondary_delta=secondary,
        passes_gate=passes_corroboration(shots_delta, secondary, weights),
    )


def _possession_delta(window: ActivityWindow, side: Side) -> int:
    """Change in possession share across the window, truncated to a whole number.

    2.2 stored the raw float and the strategy applied `int()` to it when
    checking the gate, so 4.7 points of possession gained counts as 4.
    """
    return int(window.end.team(side).possession - window.start.team(side).possession)


def _possession_fallback_delta(window: ActivityWindow, side: Side, weights: WeightSet) -> TeamDelta:
    delta = _possession_delta(window, side)
    return TeamDelta(
        pressure=delta * POSSESSION_FALLBACK_WEIGHT,
        shots_on_target_delta=0,
        secondary_delta=delta,
        passes_gate=passes_corroboration(0, delta, weights),
    )


def evaluate(
    timeline: MatchTimeline,
    *,
    weights: WeightSet | None = None,
    secondary_signal: SecondarySignal = SecondarySignal.DANGEROUS_ATTACKS,
) -> Delta5MinResult | None:
    """Five-minute pressure deltas for both teams.

    Returns None when the match is too young, when no window resolves, or when
    there is nothing usable to measure.

    Deltas are deliberately **not** clamped at zero here, unlike every other
    strategy. 2.2 subtracted the raw counters, so a provider revising a count
    downward produced negative pressure, and a team could be excluded by the
    `pressure > 0` test even after clearing the corroboration gate. Clamping
    would make such a team start triggering. Preserved to keep alert
    behaviour identical; `TeamDelta.is_implausible` surfaces the corrupt-data
    case that 2.2 only wrote to a log.
    """
    if timeline.current_minute < MINIMUM_MINUTE:
        return None

    window = resolve_window(timeline, WINDOW_MINUTES, clamp=WindowClamp.SHORT_AFTER_BREAK)
    if window is None:
        return None

    w = weights or WeightSet.defaults()

    # The strategy needs shots on target to exist at all -- not a delta, just a
    # non-zero count somewhere in the window. Without one it cannot tell a
    # quiet match from a competition the feed does not cover properly, and
    # falls back to possession.
    has_shots_on_target = any(
        snapshot.team(side).shots_on_target
        for snapshot in (window.start, window.end)
        for side in Side
    )

    if has_shots_on_target:
        home = _team_delta(window.deltas(Side.HOME, clamp=False), secondary_signal, w)
        away = _team_delta(window.deltas(Side.AWAY, clamp=False), secondary_signal, w)
        signal = secondary_signal
    else:
        has_possession = any(
            snapshot.team(side).possession
            for snapshot in (window.start, window.end)
            for side in Side
        )
        if not has_possession:
            return None
        home = _possession_fallback_delta(window, Side.HOME, w)
        away = _possession_fallback_delta(window, Side.AWAY, w)
        signal = SecondarySignal.POSSESSION

    return Delta5MinResult(
        home=home,
        away=away,
        secondary_signal=signal,
        window_start_minute=window.start_minute,
        window_end_minute=window.end_minute,
    )
