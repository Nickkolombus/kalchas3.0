"""Match state: the typed timeline every strategy reads from."""

from kalchas_core.match.snapshot import (
    MatchTimeline,
    MinuteSnapshot,
    Side,
    TeamStats,
)
from kalchas_core.match.window import (
    DEFAULT_WINDOW_MINUTES,
    PERIOD_STARTS,
    ActivityWindow,
    TeamDeltas,
    earliest_allowed_start,
    resolve_window,
)

__all__ = [
    "DEFAULT_WINDOW_MINUTES",
    "PERIOD_STARTS",
    "ActivityWindow",
    "MatchTimeline",
    "MinuteSnapshot",
    "Side",
    "TeamDeltas",
    "TeamStats",
    "earliest_allowed_start",
    "resolve_window",
]
