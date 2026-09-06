"""Omega (Strategy 6) -- pressure acceleration on a rising baseline.

Every other strategy measures how much pressure a team is applying. Omega
measures whether that pressure is *building*, which is a different question and
answers it with a second derivative.

Two pressure series are tracked per team: a fast one over a short window and a
slow one over a long window. Each is differentiated over a few minutes:

    accel    = d(fast)/dt - d(slow)/dt
    baseline = d(slow)/dt
    level    = slow(now)

`accel` is positive when short-term pressure is pulling away from the longer
trend -- the team is not merely applying pressure but increasing it. Requiring
`baseline` to be positive as well is what separates a genuine surge from a
brief spike inside a fading passage of play, and `level` sets a floor so a
surge from nothing does not qualify.

Theta and alpha are the same two quantities expressed as angles, via
`arctan(x / k)`. They exist because a slope in pressure-per-minute is hard to
reason about, whereas "the curve has tilted 20 degrees" is not. They are
display transforms and thresholds are stored either way -- see `OmegaSettings`.

Ported from `strategies/strategy_006_omega/formula.py`, which was the
best-organised strategy in 2.2: settings in one frozen dataclass, the firing
gate in one testable function, and display concerns kept honestly separate.
The arithmetic is unchanged. Removed: an admin-settings loader that read
thresholds from a database on every evaluation, the HTML message building, and
a writeback that stashed values on the match dictionary for other strategies.

Two things about the signal are worth knowing, both preserved and both pinned
by tests:

* The two series are not on a common scale. The slow window spans twice as
  long, so it counts more events and sits systematically higher, and during a
  sustained build-up its slope tends to exceed the fast window's. That makes
  `accel` come out *negative* while pressure is plainly rising. Normalising
  each series to a per-minute rate before differencing would change what
  Omega detects, so it is left alone here.
* When all of a team's activity falls inside the fast window, both series are
  identical and `accel` is exactly zero, which `classify` labels
  `COLLAPSING`. See that function.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from kalchas_core.match import MatchTimeline, Side
from kalchas_core.strategies.pressure_index import pressure_series
from kalchas_core.weights import WeightSet

STRATEGY_KEY = "omega"

DEFAULT_FAST_WINDOW: Final = 5
DEFAULT_SLOW_WINDOW: Final = 10
DEFAULT_DERIVATIVE_WINDOW: Final = 3
DEFAULT_ANGLE_SCALE: Final = 15.0

DEFAULT_MIN_ACCELERATION: Final = 5.46
"""Roughly 20 degrees at the default angle scale."""

DEFAULT_MIN_BASELINE_SLOPE: Final = 0.0
DEFAULT_MIN_LEVEL: Final = 0.0

DEFAULT_THETA_THRESHOLD: Final = 20.0
DEFAULT_ALPHA_FLOOR: Final = 0.0

FLAT_BAND_DEGREES: Final = 5.0

# Bounds the settings loader applied, kept so a caller constructing settings
# from stored values lands in the same place 2.2 did.
FAST_WINDOW_BOUNDS: Final = (2, 30)
SLOW_WINDOW_BOUNDS: Final = (0, 45)
DERIVATIVE_WINDOW_BOUNDS: Final = (1, 10)
ANGLE_SCALE_BOUNDS: Final = (0.1, 50.0)
MIN_ACCELERATION_BOUNDS: Final = (0.0, 50.0)
MIN_BASELINE_BOUNDS: Final = (-20.0, 20.0)
MIN_LEVEL_BOUNDS: Final = (0.0, 100.0)

_ACCELERATION_PRECISION: Final = 3
_LEVEL_PRECISION: Final = 1
_ANGLE_PRECISION: Final = 2


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], value))


def degrees_to_slope(degrees: float, scale: float) -> float:
    """Convert an angle threshold into a pressure-per-minute slope."""
    return scale * math.tan(math.radians(degrees))


def slope_to_degrees(slope: float, scale: float) -> float:
    """Express a pressure-per-minute slope as an angle."""
    return math.degrees(math.atan(slope / max(scale, 1e-9)))


class OmegaState(StrEnum):
    """Which quadrant of the acceleration/baseline plane a team sits in.

    Diagnostic only. The firing decision uses the thresholds, not this label.
    """

    FLAT = "flat"
    CONFIRMED_SURGE = "confirmed_surge"
    """Rising and accelerating: the case Omega exists to find."""

    SPIKE_ONLY = "spike_only"
    """Accelerating against a falling trend -- a blip, not a surge."""

    SOFTENING = "softening"
    """Still rising, but the rise is slowing."""

    COLLAPSING = "collapsing"


def classify(theta: float, alpha: float, flat_band: float = FLAT_BAND_DEGREES) -> OmegaState:
    """Label the quadrant. Diagnostic only; firing uses the thresholds.

    An acceleration of exactly zero falls through every branch to
    `COLLAPSING`, even with a steeply rising baseline. That is 2.2's behaviour
    and it is preserved, but it is not rare: a burst confined to the fast
    window makes both series identical, so their slopes cancel exactly and a
    team visibly building pressure gets labelled as collapsing on the
    dashboard. Fixing it is a one-line change to this function whenever the
    display is revisited.
    """
    if abs(theta) < flat_band and abs(alpha) < flat_band:
        return OmegaState.FLAT
    if theta > 0 and alpha > 0:
        return OmegaState.CONFIRMED_SURGE
    if theta > 0:
        return OmegaState.SPIKE_ONLY
    if theta < 0 and alpha > 0:
        return OmegaState.SOFTENING
    return OmegaState.COLLAPSING


@dataclass(frozen=True, slots=True)
class OmegaSettings:
    """Firing thresholds and window sizes.

    The linear thresholds are authoritative. `from_stored` accepts the angle
    form as a fallback, because 2.2 stored thresholds in degrees before it
    stored slopes and both shapes still exist in saved settings.
    """

    min_acceleration: float = DEFAULT_MIN_ACCELERATION
    min_baseline_slope: float = DEFAULT_MIN_BASELINE_SLOPE
    min_level: float = DEFAULT_MIN_LEVEL
    angle_scale: float = DEFAULT_ANGLE_SCALE
    fast_window: int = DEFAULT_FAST_WINDOW
    slow_window: int = DEFAULT_SLOW_WINDOW
    derivative_window: int = DEFAULT_DERIVATIVE_WINDOW

    @property
    def theta_threshold(self) -> float:
        return slope_to_degrees(self.min_acceleration, self.angle_scale)

    @property
    def alpha_floor(self) -> float:
        return slope_to_degrees(self.min_baseline_slope, self.angle_scale)

    @property
    def minimum_minute(self) -> int:
        """Before this, the slow series has no room to be differentiated."""
        return self.slow_window + self.derivative_window

    @classmethod
    def from_stored(
        cls,
        *,
        min_acceleration: float | None = None,
        min_baseline_slope: float | None = None,
        min_level: float | None = None,
        angle_scale: float | None = None,
        fast_window: int | None = None,
        slow_window: int | None = None,
        derivative_window: int | None = None,
        theta_threshold: float | None = None,
        alpha_floor: float | None = None,
    ) -> OmegaSettings:
        """Build settings from saved admin values, bounded as 2.2 bounded them.

        Order matters: windows and the angle scale are bounded first, because
        an angle threshold is converted to a slope using the *bounded* scale.
        """
        fast = int(_clamp(fast_window or DEFAULT_FAST_WINDOW, FAST_WINDOW_BOUNDS))

        # The slow window must exceed the fast one, or the difference of their
        # derivatives is meaningless.
        slow = int(max(fast + 1, min(SLOW_WINDOW_BOUNDS[1], slow_window or DEFAULT_SLOW_WINDOW)))
        derivative = int(
            _clamp(derivative_window or DEFAULT_DERIVATIVE_WINDOW, DERIVATIVE_WINDOW_BOUNDS)
        )
        scale = _clamp(angle_scale or DEFAULT_ANGLE_SCALE, ANGLE_SCALE_BOUNDS)

        if min_acceleration is None:
            min_acceleration = degrees_to_slope(
                theta_threshold if theta_threshold is not None else DEFAULT_THETA_THRESHOLD,
                scale,
            )
        if min_baseline_slope is None:
            min_baseline_slope = degrees_to_slope(
                alpha_floor if alpha_floor is not None else DEFAULT_ALPHA_FLOOR,
                scale,
            )

        return cls(
            min_acceleration=_clamp(min_acceleration, MIN_ACCELERATION_BOUNDS),
            min_baseline_slope=_clamp(min_baseline_slope, MIN_BASELINE_BOUNDS),
            min_level=_clamp(
                min_level if min_level is not None else DEFAULT_MIN_LEVEL, MIN_LEVEL_BOUNDS
            ),
            angle_scale=scale,
            fast_window=fast,
            slow_window=slow,
            derivative_window=derivative,
        )


@dataclass(frozen=True, slots=True)
class TeamOmega:
    """One team's acceleration reading.

    Values are rounded, and deliberately so: 2.2 rounded before testing the
    thresholds, so rounding can decide whether an alert fires. Preserved.
    """

    acceleration: float
    baseline_slope: float
    level: float
    theta: float
    alpha: float
    fast_slope: float
    slow_slope: float
    fast_level: float
    state: OmegaState

    def meets(self, settings: OmegaSettings) -> bool:
        """Accelerating, on a rising trend, from a high enough base.

        All three are required. Acceleration alone is a spike; acceleration on
        a rising baseline is a surge.
        """
        return (
            self.acceleration > settings.min_acceleration
            and self.baseline_slope > settings.min_baseline_slope
            and self.level >= settings.min_level
        )


@dataclass(frozen=True, slots=True)
class OmegaResult:
    """Both teams' readings at the minute actually evaluated."""

    home: TeamOmega | None
    away: TeamOmega | None
    minute: int
    settings: OmegaSettings

    def team(self, side: Side) -> TeamOmega | None:
        return self.home if side is Side.HOME else self.away

    @property
    def triggering_team(self) -> Side | None:
        """The qualifying team with the strongest acceleration.

        Ties go to the home team, which is compared first.
        """
        best: Side | None = None
        best_acceleration = -math.inf

        for side in (Side.HOME, Side.AWAY):
            reading = self.team(side)
            if reading is None or not reading.meets(self.settings):
                continue
            if reading.acceleration > best_acceleration:
                best, best_acceleration = side, reading.acceleration

        return best

    @property
    def trigger_value(self) -> float:
        side = self.triggering_team
        reading = self.team(side) if side else None
        return reading.acceleration if reading else 0.0


def _evaluate_side(
    timeline: MatchTimeline,
    side: Side,
    minute: int,
    settings: OmegaSettings,
    home_goals: int,
    away_goals: int,
    weights: WeightSet,
) -> TeamOmega | None:
    if minute < max(settings.minimum_minute, 2):
        return None

    def series(window_minutes: int) -> list[float]:
        return pressure_series(
            timeline,
            side,
            up_to_minute=minute,
            window_minutes=window_minutes,
            home_goals=home_goals,
            away_goals=away_goals,
            weights=weights,
        )

    fast = series(settings.fast_window)
    slow = series(settings.slow_window)
    if len(fast) <= minute or len(slow) <= minute:
        return None

    step = settings.derivative_window
    fast_slope = (fast[minute] - fast[minute - step]) / step
    slow_slope = (slow[minute] - slow[minute - step]) / step
    acceleration = fast_slope - slow_slope

    theta = slope_to_degrees(acceleration, settings.angle_scale)
    alpha = slope_to_degrees(slow_slope, settings.angle_scale)

    return TeamOmega(
        acceleration=round(acceleration, _ACCELERATION_PRECISION),
        baseline_slope=round(slow_slope, _ACCELERATION_PRECISION),
        level=round(slow[minute], _LEVEL_PRECISION),
        theta=round(theta, _ANGLE_PRECISION),
        alpha=round(alpha, _ANGLE_PRECISION),
        fast_slope=round(fast_slope, _ACCELERATION_PRECISION),
        slow_slope=round(slow_slope, _ACCELERATION_PRECISION),
        fast_level=round(fast[minute], _LEVEL_PRECISION),
        state=classify(theta, alpha, weights.get(STRATEGY_KEY, "flat_band")),
    )


def evaluate(
    timeline: MatchTimeline,
    *,
    home_goals: int = 0,
    away_goals: int = 0,
    settings: OmegaSettings | None = None,
    weights: WeightSet | None = None,
) -> OmegaResult | None:
    """Acceleration readings for both teams.

    Evaluated at the most recent minute the scanner actually recorded, not
    necessarily the live minute. Differentiating a series needs the endpoint to
    exist, so falling back to the last recorded minute keeps a reading during a
    polling gap instead of dropping it. 2.2 called this a "data clamp" and
    showed the gap in the alert text.

    Returns None when the match is too young for the slow window to be
    differentiated, or when neither team yields a reading.
    """
    active = settings or OmegaSettings()
    w = weights or WeightSet.defaults()

    recorded = [m for m in timeline.available_minutes if 0 <= m <= timeline.current_minute]
    if not recorded:
        return None

    minute = max(recorded)
    if minute < active.minimum_minute:
        return None

    home = _evaluate_side(timeline, Side.HOME, minute, active, home_goals, away_goals, w)
    away = _evaluate_side(timeline, Side.AWAY, minute, active, home_goals, away_goals, w)
    if home is None and away is None:
        return None

    return OmegaResult(home=home, away=away, minute=minute, settings=active)
