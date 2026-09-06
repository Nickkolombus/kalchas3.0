"""Pressure Index (Strategy 2) -- attacking momentum over a rolling window.

    PI = √ΔSOT·sot_points + √ΔSOFFT·sofft_points
       + √ΔCorners·corner_points + √ΔDA·da_points
    PI × game_state × time_multiplier, clamped to 0-100

Counting events over a window and square-rooting them gives diminishing
returns, so a team that takes eight shots in ten minutes reads as busier than
one taking four, but not twice as dangerous.

Alongside the main window, a short burst window catches surges the longer
window smooths away.

Ported from Kalchas 2.2 `utils/pressure_index_service.py`, whose
`PressureIndexService` was instantiated at module import and read its window
length from a JSON file in that constructor -- importing the module touched
the filesystem, and the window could not be varied per call.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kalchas_core.match import (
    ActivityWindow,
    MatchTimeline,
    Side,
    TeamDeltas,
    WindowClamp,
    resolve_window,
)
from kalchas_core.weights import WeightSet

STRATEGY_KEY = "pressure_index"

DEFAULT_WINDOW_MINUTES = 10
DEFAULT_BURST_MINUTES = 3

# When no snapshot falls inside the window, reach back at most this far for the
# nearest one rather than reporting nothing.
FALLBACK_LOOKBACK_MINUTES = 15

# A match is not evaluated before this minute; there is too little history.
MINIMUM_MINUTE = 5

MIN_PRESSURE = 0.0
MAX_PRESSURE = 100.0


@dataclass(frozen=True, slots=True)
class TeamPressure:
    """One team's pressure reading, with the factors behind it."""

    pressure: float
    raw_pressure: float
    burst: float
    deltas: TeamDeltas
    game_state_modifier: float
    time_multiplier: float


@dataclass(frozen=True, slots=True)
class PressureIndexResult:
    """Both teams' pressure over the same window."""

    home: TeamPressure
    away: TeamPressure
    window_start_minute: int
    window_end_minute: int

    def team(self, side: Side) -> TeamPressure:
        return self.home if side is Side.HOME else self.away

    @property
    def window_minutes(self) -> int:
        """Minutes actually covered, which may be less than the span requested."""
        return self.window_end_minute - self.window_start_minute

    @property
    def total(self) -> float:
        """Combined pressure. This is the value the strategy fires on."""
        return self.home.pressure + self.away.pressure

    @property
    def leader(self) -> Side | None:
        """The team applying more pressure, or None if they are level."""
        if self.home.pressure == self.away.pressure:
            return None
        return Side.HOME if self.home.pressure > self.away.pressure else Side.AWAY


def game_state_modifier(team_goals: int, opponent_goals: int) -> float:
    """Pressure while chasing converts more often than pressure while ahead.

    Unlike Strategy 1's equivalent, these are fixed rather than admin-tunable,
    and take no account of the clock. Carried over as-is.
    """
    difference = team_goals - opponent_goals
    if difference == 0:
        return 1.0
    if difference == 1:
        return 0.90
    if difference >= 2:
        return 0.75
    if difference == -1:
        return 1.15
    return 1.10


def time_multiplier(minute: int | None, weights: WeightSet) -> float:
    """Late pressure is worth more, because late goals are more frequent."""
    if not minute or minute <= 0:
        return 1.0
    if minute <= 30:
        return weights.get(STRATEGY_KEY, "time_mult_0_30")
    if minute <= 60:
        return weights.get(STRATEGY_KEY, "time_mult_31_60")
    if minute <= 75:
        return weights.get(STRATEGY_KEY, "time_mult_61_75")
    return weights.get(STRATEGY_KEY, "time_mult_75_plus")


def raw_pressure(deltas: TeamDeltas, weights: WeightSet) -> float:
    """Square-root-scaled event count, clamped to 0-100.

    Square-rooting is what stops a burst of dangerous attacks -- the noisiest
    input the feed provides -- from dominating the score.
    """
    total = (
        math.sqrt(deltas.shots_on_target) * weights.get(STRATEGY_KEY, "sot_points")
        + math.sqrt(max(0, deltas.shots - deltas.shots_on_target))
        * weights.get(STRATEGY_KEY, "sofft_points")
        + math.sqrt(deltas.corners) * weights.get(STRATEGY_KEY, "corner_points")
        + math.sqrt(deltas.dangerous_attacks) * weights.get(STRATEGY_KEY, "da_points")
    )
    return min(MAX_PRESSURE, max(MIN_PRESSURE, total))


def pressure_series(
    timeline: MatchTimeline,
    side: Side,
    *,
    up_to_minute: int,
    window_minutes: int,
    home_goals: int = 0,
    away_goals: int = 0,
    weights: WeightSet | None = None,
) -> list[float]:
    """One team's pressure at every minute from 0 to `up_to_minute`.

    The same reading `evaluate` produces, computed at each minute in turn, so a
    caller can look at how pressure moved rather than only where it is. Omega
    differentiates two of these against each other.

    Minutes the scanner never recorded, and minutes with no resolvable window,
    read as 0.0 rather than being omitted, so the index of the list is always
    the minute. That does conflate "no data" with "no pressure", which is the
    one place this core does so; Omega only ever reads minutes it has already
    established are present.

    Game state is taken from the scoreline as it stood at each minute where
    the feed recorded one, falling back to the score passed in.
    """
    if up_to_minute < 0:
        return []

    w = weights or WeightSet.defaults()
    out = [0.0] * (up_to_minute + 1)

    for minute in range(up_to_minute + 1):
        if timeline.snapshot_at(minute) is None:
            continue

        window = resolve_window(
            timeline,
            window_minutes,
            clamp=WindowClamp.PERIOD_START,
            fallback_lookback=FALLBACK_LOOKBACK_MINUTES,
            require_full_span=False,
            at_minute=minute,
        )
        if window is None:
            continue

        recorded = window.end
        goals = recorded.team(side).goals
        opponent_goals = recorded.team(side.opponent).goals
        default_goals = home_goals if side is Side.HOME else away_goals
        default_opponent = away_goals if side is Side.HOME else home_goals

        out[minute] = _team_pressure(
            window,
            None,
            side,
            goals=goals if goals is not None else default_goals,
            opponent_goals=opponent_goals if opponent_goals is not None else default_opponent,
            minute=minute,
            weights=w,
        ).pressure

    return out


def _team_pressure(
    window: ActivityWindow,
    burst_window: ActivityWindow | None,
    side: Side,
    *,
    goals: int,
    opponent_goals: int,
    minute: int,
    weights: WeightSet,
) -> TeamPressure:
    deltas = window.deltas(side)
    raw = raw_pressure(deltas, weights)

    state = game_state_modifier(goals, opponent_goals)
    time_mult = time_multiplier(minute, weights)

    # Clamped twice, as in 2.2: once inside raw_pressure and again after the
    # modifiers, so a maxed-out raw score multiplied by a chasing team's 1.15
    # still lands at 100 rather than 115.
    pressure = min(MAX_PRESSURE, max(MIN_PRESSURE, raw * state * time_mult))

    burst = raw_pressure(burst_window.deltas(side), weights) if burst_window else 0.0

    return TeamPressure(
        pressure=pressure,
        raw_pressure=raw,
        burst=burst,
        deltas=deltas,
        game_state_modifier=state,
        time_multiplier=time_mult,
    )


def evaluate(
    timeline: MatchTimeline,
    *,
    home_goals: int = 0,
    away_goals: int = 0,
    weights: WeightSet | None = None,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    burst_minutes: int = DEFAULT_BURST_MINUTES,
) -> PressureIndexResult | None:
    """Pressure for both teams over the most recent window.

    Returns None when the match is too young or no window can be resolved.
    2.2 returned `{'home': 0.0, 'away': 0.0, 'total': 0.0}` in that case, which
    is indistinguishable from a genuine reading of no pressure at all.

    The window clamps to the start of the current period, so a ten-minute
    lookback taken shortly after the interval does not count first-half events
    as current pressure.
    """
    if timeline.current_minute < MINIMUM_MINUTE:
        return None

    window = resolve_window(
        timeline,
        window_minutes,
        clamp=WindowClamp.PERIOD_START,
        fallback_lookback=FALLBACK_LOOKBACK_MINUTES,
        require_full_span=False,
    )
    if window is None:
        return None

    burst_window = resolve_window(
        timeline,
        burst_minutes,
        clamp=WindowClamp.PERIOD_START,
        require_full_span=False,
    )
    w = weights or WeightSet.defaults()
    minute = timeline.current_minute

    return PressureIndexResult(
        home=_team_pressure(
            window,
            burst_window,
            Side.HOME,
            goals=home_goals,
            opponent_goals=away_goals,
            minute=minute,
            weights=w,
        ),
        away=_team_pressure(
            window,
            burst_window,
            Side.AWAY,
            goals=away_goals,
            opponent_goals=home_goals,
            minute=minute,
            weights=w,
        ),
        window_start_minute=window.start_minute,
        window_end_minute=window.end_minute,
    )
