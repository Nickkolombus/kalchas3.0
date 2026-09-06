"""Rolling activity windows over a match timeline.

Strategies 4 and 5 both measure activity across the last few minutes, and both
have to stop the window from reaching back across a half-time break -- counters
carry over but the play does not, so a window spanning the interval reports a
surge that never happened.

Kalchas 2.2 implemented this three times. Two were verbatim copies --
`utils/delta_calculator.calculate_delta_5min_pressure` and
`utils/npei_calculator._resolve_five_minute_window`, with a comment in the
first asking the second to be kept in sync by hand. The third, in
`utils/pressure_index_service.calculate_from_json_data`, used a genuinely
different rule.

Both rules are kept, as `WindowClamp`, because they do not agree: at minute 55
the shortened-lookback rule starts at 52 and the period-start rule at 51. They
are now named and tested rather than incidental.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from kalchas_core.match.snapshot import MatchTimeline, MinuteSnapshot, Side, TeamStats

DEFAULT_WINDOW_MINUTES = 5

# Minute at which each period begins. The range above each boundary includes
# that period's injury time, which is why the second half starts at 51 rather
# than 46: minutes 46-50 are first-half stoppage.
PERIOD_STARTS: tuple[int, ...] = (51, 97, 111)
FIRST_PERIOD_START = 1

# How long after a period starts the SHORT_AFTER_BREAK rule stays engaged, and
# how far back a window may reach while it is.
_CLAMP_DURATION = 5
_CLAMPED_LOOKBACK = 3


class WindowClamp(StrEnum):
    """How a window is stopped from reaching back across a break in play."""

    SHORT_AFTER_BREAK = "short_after_break"
    """Clamp only just after a period starts, to a shortened lookback.

    Used by NPEI and Delta 5min. Outside the first few minutes of a period it
    imposes nothing, which is safe for a five-minute window but would let a
    longer one span the interval.
    """

    PERIOD_START = "period_start"
    """Never reach back before the current period began.

    Used by Pressure Index, whose ten-minute window would otherwise cross
    half-time for the first ten minutes of each period.
    """


def period_start_for(minute: int) -> int:
    """The minute at which the period containing `minute` began."""
    for period_start in reversed(PERIOD_STARTS):
        if minute >= period_start:
            return period_start
    return FIRST_PERIOD_START


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


def earliest_allowed_start(
    current_minute: int,
    span: int = DEFAULT_WINDOW_MINUTES,
    clamp: WindowClamp = WindowClamp.SHORT_AFTER_BREAK,
) -> int:
    """The earliest minute a window ending now may reach back to.

    Normally `current_minute - span`, raised by whichever `clamp` applies so
    the window cannot span a break in play.
    """
    start = current_minute - span

    if clamp is WindowClamp.PERIOD_START:
        return max(start, period_start_for(current_minute))

    for period_start in PERIOD_STARTS:
        if period_start <= current_minute < period_start + _CLAMP_DURATION:
            return max(start, max(period_start, current_minute - _CLAMPED_LOOKBACK))

    return start


def resolve_window(
    timeline: MatchTimeline,
    span: int = DEFAULT_WINDOW_MINUTES,
    *,
    clamp: WindowClamp = WindowClamp.SHORT_AFTER_BREAK,
    fallback_lookback: int | None = None,
    require_full_span: bool = True,
) -> ActivityWindow | None:
    """The most recent `span`-minute window of play, or None if unavailable.

    Returns None -- rather than an empty or zeroed window -- when the current
    minute was never recorded, or when no recorded minute falls inside the
    allowed range. That means "no reading", which is not the same as a reading
    of zero.

    `require_full_span` also rejects a match younger than `span`. NPEI wants
    that; Pressure Index does not, because its ten-minute window would then
    report nothing for the first ten minutes of every match, so it accepts a
    partial window and applies its own minimum instead.

    `fallback_lookback` softens the range check: when nothing falls inside the
    window, accept the nearest recorded minute no more than that many minutes
    back. Pressure Index uses it so a gap in polling degrades the reading
    instead of dropping it. Without it, a gap yields None.
    """
    current_minute = timeline.current_minute
    if require_full_span and current_minute < span:
        return None

    end = timeline.snapshot_at(current_minute)
    if end is None:
        return None

    earlier = [m for m in timeline.available_minutes if m < current_minute]
    if not earlier:
        return None

    lower_bound = earliest_allowed_start(current_minute, span, clamp)
    candidates = [m for m in earlier if m >= lower_bound]

    if candidates:
        start_minute = candidates[0]
    elif fallback_lookback is not None:
        # Nothing inside the window. Reach for the nearest recorded minute,
        # but no further back than the fallback allows -- a very old snapshot
        # would report the whole match as one surge.
        target = max(earlier[-1], current_minute - fallback_lookback)
        start_minute = min(earlier, key=lambda m: abs(m - target))
    else:
        return None

    start = timeline.snapshot_at(start_minute)
    if start is None:  # pragma: no cover -- start_minute came from this mapping
        return None

    return ActivityWindow(start=start, end=end)
