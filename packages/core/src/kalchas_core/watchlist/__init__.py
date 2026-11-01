"""Pre-match watchlist: team profiles, ranked patterns and page payloads."""

from kalchas_core.watchlist.patterns import (
    PATTERN_ROWS,
    Pattern,
    match_patterns,
    pattern_table,
    watch_level,
    watch_score,
)
from kalchas_core.watchlist.profile import (
    PROFILE_WINDOW,
    TIMING_LABELS,
    LeagueNorms,
    PlayedGame,
    TeamProfile,
    build_team_profile,
    is_played,
    league_norms,
    team_games,
    timing_bucket,
)
from kalchas_core.watchlist.research import (
    build_match_research,
    league_label,
    list_row,
    shortlist,
    table_slice,
    timing_note,
)

__all__ = [
    "PATTERN_ROWS",
    "PROFILE_WINDOW",
    "TIMING_LABELS",
    "LeagueNorms",
    "Pattern",
    "PlayedGame",
    "TeamProfile",
    "build_match_research",
    "build_team_profile",
    "is_played",
    "league_label",
    "league_norms",
    "list_row",
    "match_patterns",
    "pattern_table",
    "shortlist",
    "table_slice",
    "team_games",
    "timing_bucket",
    "timing_note",
    "watch_level",
    "watch_score",
]
