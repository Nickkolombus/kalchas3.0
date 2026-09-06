"""Rolling activity windows over a match timeline.

Strategies 4 and 5 both measure activity across the last few minutes, and both
have to stop the window from reaching back across a half-time break -- counters
carry over but the play does not, so a window spanning the interval reports a
surge that never happened.

Kalchas 2.2 implemented this twice, verbatim, in
`utils/delta_calculator.calculate_delta_5min_pressure` and
`utils/npei_calculator._resolve_five_minute_window`, with a comment in the
first asking the second to be kept in sync by hand. It lives in one place here.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalchas_core.match.snapshot import MatchTimeline, MinuteSnapshot, Side, TeamStats

DEFAULT_WINDOW_MINUTES = 5

# Minute at which each period begins. The ranges above each boundary include
# that period's injury time, which is why the second half starts at 51 rather
# than 46: minutes 46-50 are first-half stoppage.
PERIOD_STARTS: tuple[int, ...] = (51, 97, 111)

# How long after a period starts the window stays clamped, and how far back it
# may reach while clamped.
_CLAMP_DURATION = 5
_CLAMPED_LOOKBACK = 3


@dataclass(frozen=True, slots=True)
class TeamDeltas:
    """Activity by one team across a window: end counters minus start counters.

    Never negative. A provider correcting a counter downward mid-match would
    otherwise register as negative activity.
    """

    attacks: int
    dangerous_attacks: int
    shots: int
    shots_on_target: int
    corners: int

    @classmethod
    def between(cls, start: TeamStats, end: TeamStats) -> TeamDeltas:
        return cls(
            attacks=max(0, end.attacks - start.attacks),
            dangerous_attacks=max(0, end.dangerous_attacks - start.dangerous_attacks),
            shots=max(0, end.total_shots - start.total_shots),
            shots_on_target=max(0, end.shots_on_target - start.shots_on_target),
            corners=max(0, end.corners - start.corners),
        )


@dataclass(frozen=True, slots=True)
class ActivityWindow:
    """Two snapshots bracketing a stretch of play, and the deltas between them."""

    start: MinuteSnapshot
    end: MinuteSnapshot

    @property
    def start_minute(self) -> int:
        return self.start.minute

    @property
    def end_minute(self) -> int:
        return self.end.minute

    @property
    def span(self) -> int:
        """Minutes actually covered, which may be less than the span requested."""
        return self.end.minute - self.start.minute

    def deltas(self, side: Side) -> TeamDeltas:
        return TeamDeltas.between(self.start.team(side), self.end.team(side))


def earliest_allowed_start(current_minute: int, span: int = DEFAULT_WINDOW_MINUTES) -> int:
    """The earliest minute a window ending now may reach back to.

    Normally `current_minute - span`. Just after a period starts, the window is
    clamped so it cannot span the break: for the first five minutes of a new
    period it reaches back at most three minutes, and never past the period
    start itself.
    """
    start = current_minute - span

    for period_start in PERIOD_STARTS:
        if period_start <= current_minute < period_start + _CLAMP_DURATION:
            clamped = max(period_start, current_minute - _CLAMPED_LOOKBACK)
            return max(start, clamped)

    return start


def resolve_window(
    timeline: MatchTimeline,
    span: int = DEFAULT_WINDOW_MINUTES,
) -> ActivityWindow | None:
    """The most recent `span`-minute window of play, or None if unavailable.

    Returns None -- rather than an empty or zeroed window -- when the match is
    too young for a full window, when the current minute was never recorded, or
    when no recorded minute falls inside the allowed range. Those cases mean
    "no reading", which is not the same as a reading of zero.
    """
    current_minute = timeline.current_minute
    if current_minute < span:
        return None

    end = timeline.snapshot_at(current_minute)
    if end is None:
        return None

    lower_bound = earliest_allowed_start(current_minute, span)
    candidates = [m for m in timeline.available_minutes if lower_bound <= m < current_minute]
    if not candidates:
        return None

    start = timeline.snapshot_at(candidates[0])
    if start is None:  # pragma: no cover -- candidates come from the same mapping
        return None

    return ActivityWindow(start=start, end=end)
