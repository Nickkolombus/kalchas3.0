"""Match state: the typed timeline every strategy reads from."""

from kalchas_core.match.snapshot import (
    MatchTimeline,
    MinuteSnapshot,
    Side,
    TeamStats,
)
from kalchas_core.match.window import (
    DEFAULT_WINDOW_MINUTES,
    FIRST_PERIOD_START,
    PERIOD_STARTS,
    ActivityWindow,
    TeamDeltas,
    WindowClamp,
    earliest_allowed_start,
    period_start_for,
    resolve_window,
)

__all__ = [
    "DEFAULT_WINDOW_MINUTES",
    "FIRST_PERIOD_START",
    "PERIOD_STARTS",
    "ActivityWindow",
    "MatchTimeline",
    "MinuteSnapshot",
    "Side",
    "TeamDeltas",
    "TeamStats",
    "WindowClamp",
    "earliest_allowed_start",
    "period_start_for",
    "resolve_window",
]
