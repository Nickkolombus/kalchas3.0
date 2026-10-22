"""Team form metrics from finished fixtures (Strategy 9 pure core).

Enrichment only — never triggers alerts. Callers fetch fixtures; this module
turns them into form numbers and English insight strings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Final

DEFAULT_FORM_WINDOW: Final = 5
DEFAULT_MIN_STREAK: Final = 3
DEFAULT_HIGH_SCORING: Final = 2.0
DEFAULT_CONCEDE_FLAG: Final = 2.0
DEFAULT_GD_INSIGHT: Final = 6
DEFAULT_FORM_POINTS_GAP: Final = 6
DEFAULT_SCORING_GAP: Final = 1.0
DEFAULT_POSITION_GAP: Final = 5
MIN_FIXTURES_FOR_FORM: Final = 3

PLAYED_STATUS_CODES: Final = frozenset({"FT", "AET", "PEN"})
"""Finished *and actually played*. Postponed / cancelled / abandoned /
awarded rows count as finished elsewhere, but carry no real score, so they
would read as 0-0 here."""


@dataclass(frozen=True, slots=True)
class FinishedFixture:
    """One finished match, already filtered by the caller."""

    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int
    match_date: str = ""
    match_id: str = ""


@dataclass(frozen=True, slots=True)
class VenueRecord:
    games: int = 0
    wins: int = 0
    goals: int = 0


@dataclass(frozen=True, slots=True)
class Streak:
    type: str | None = None  # "W" | "D" | "L"
    count: int = 0


@dataclass(frozen=True, slots=True)
class TeamForm:
    games_played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0
    goals_per_game: float = 0.0
    goals_against_per_game: float = 0.0
    form_string: str = "No recent data"
    results_last5: tuple[str, ...] = ()
    current_streak: Streak = field(default_factory=Streak)
    home_record: VenueRecord = field(default_factory=VenueRecord)
    away_record: VenueRecord = field(default_factory=VenueRecord)
    scored_by_game: tuple[int, ...] = ()
    """Goals this team scored in each game of the window, newest first."""
    conceded_by_game: tuple[int, ...] = ()
    """Goals this team conceded in each game of the window, newest first."""

    @property
    def form_points(self) -> int:
        return self.wins * 3 + self.draws

    @property
    def median_scored(self) -> float:
        return float(median(self.scored_by_game)) if self.scored_by_game else 0.0

    @property
    def median_conceded(self) -> float:
        return float(median(self.conceded_by_game)) if self.conceded_by_game else 0.0


EMPTY_FORM = TeamForm()


def played_fixtures(rows: Sequence[dict[str, Any]]) -> list[FinishedFixture]:
    """Canonical team-fixture rows (``kalchas_football.parse_team_fixtures``)
    down to the ones actually played, order kept.

    Keyed on the normalised ``status_short`` (``FT``/``AET``/``PEN``), not the
    provider's ``match_status`` text (``"Finished"``, ``"After Pen."``, ...).
    Rows missing either score are dropped rather than read as 0.
    """
    out: list[FinishedFixture] = []
    for row in rows:
        if str(row.get("status_short") or "") not in PLAYED_STATUS_CODES:
            continue
        home_score, away_score = row.get("home_score"), row.get("away_score")
        if home_score is None or away_score is None:
            continue
        out.append(
            FinishedFixture(
                home_team_id=int(row.get("home_team_id") or 0),
                away_team_id=int(row.get("away_team_id") or 0),
                home_score=int(home_score),
                away_score=int(away_score),
                match_date=str(row.get("match_date") or ""),
                match_id=str(row.get("match_id") or ""),
            )
        )
    return out


def form_cache_key(team_id: int) -> str:
    """``panel_cache`` key for a team's Form Bar form. ``v3``: Form Bar needs
    each game's scored/conceded for medians; v2 rows only held totals, and v1
    rows were written by a status filter that dropped every fixture. A new key
    skips both instead of serving them out their TTL."""
    return f"team_form_v3_{team_id}"


def form_cache_payload(form: TeamForm) -> dict[str, list[int]]:
    """What the scanner and API store in ``panel_cache`` for Form Bar."""
    return {"scored": list(form.scored_by_game), "conceded": list(form.conceded_by_game)}


def form_from_cache_payload(payload: Any) -> TeamForm | None:
    """Inverse of `form_cache_payload`. `None` for anything unreadable, so the
    caller refetches instead of trusting it."""
    if not isinstance(payload, dict):
        return None
    scored, conceded = payload.get("scored"), payload.get("conceded")
    if not isinstance(scored, list) or not isinstance(conceded, list):
        return None
    if len(scored) != len(conceded):
        return None
    try:
        scored_t = tuple(int(g) for g in scored)
        conceded_t = tuple(int(g) for g in conceded)
    except (TypeError, ValueError):
        return None
    games = len(scored_t)
    if games == 0:
        return EMPTY_FORM
    goals_for, goals_against = sum(scored_t), sum(conceded_t)
    return TeamForm(
        games_played=games,
        goals_for=goals_for,
        goals_against=goals_against,
        goal_difference=goals_for - goals_against,
        goals_per_game=round(goals_for / games, 1),
        goals_against_per_game=round(goals_against / games, 1),
        scored_by_game=scored_t,
        conceded_by_game=conceded_t,
    )


def calculate_team_form(
    fixtures: Sequence[FinishedFixture | dict[str, Any]],
    team_id: int,
    window: int = DEFAULT_FORM_WINDOW,
) -> TeamForm:
    """Form over the most recent `window` fixtures (already newest-first).

    Accepts either typed `FinishedFixture` rows or the 2.2 dict shape with
    `match_hometeam_id` / `match_hometeam_score` keys.
    """
    if not fixtures:
        return EMPTY_FORM

    recent = fixtures[:window]
    wins = draws = losses = 0
    goals_for = goals_against = 0
    current_streak = Streak()
    streak_open = True
    home_wins = away_wins = 0
    home_goals = away_goals = 0
    home_games = away_games = 0
    results: list[str] = []
    scored_by_game: list[int] = []
    conceded_by_game: list[int] = []

    for i, match in enumerate(recent):
        try:
            home_id, _away_id, home_score, away_score = _unpack(match)
            is_home = home_id == team_id
            if is_home:
                team_score, opp_score = home_score, away_score
                home_games += 1
                home_goals += team_score
            else:
                team_score, opp_score = away_score, home_score
                away_games += 1
                away_goals += team_score

            goals_for += team_score
            goals_against += opp_score
            scored_by_game.append(team_score)
            conceded_by_game.append(opp_score)

            if team_score > opp_score:
                wins += 1
                if is_home:
                    home_wins += 1
                else:
                    away_wins += 1
                result = "W"
            elif team_score == opp_score:
                draws += 1
                result = "D"
            else:
                losses += 1
                result = "L"

            if len(results) < window:
                results.append(result)

            # Current streak = unbroken run from the most recent match only.
            if i == 0:
                current_streak = Streak(type=result, count=1)
            elif streak_open and current_streak.type == result:
                current_streak = Streak(type=result, count=current_streak.count + 1)
            else:
                streak_open = False
        except (ValueError, TypeError, KeyError, AttributeError):
            continue

    games_played = wins + draws + losses
    if games_played == 0:
        return EMPTY_FORM

    return TeamForm(
        games_played=games_played,
        wins=wins,
        draws=draws,
        losses=losses,
        goals_for=goals_for,
        goals_against=goals_against,
        goal_difference=goals_for - goals_against,
        goals_per_game=round(goals_for / games_played, 1),
        goals_against_per_game=round(goals_against / games_played, 1),
        form_string=f"{wins}W-{draws}D-{losses}L",
        results_last5=tuple(results),
        current_streak=current_streak,
        home_record=VenueRecord(home_games, home_wins, home_goals),
        away_record=VenueRecord(away_games, away_wins, away_goals),
        scored_by_game=tuple(scored_by_game),
        conceded_by_game=tuple(conceded_by_game),
    )


def _unpack(match: FinishedFixture | dict) -> tuple[int, int, int, int]:
    if isinstance(match, FinishedFixture):
        return (
            match.home_team_id,
            match.away_team_id,
            match.home_score,
            match.away_score,
        )
    return (
        int(match.get("match_hometeam_id", match.get("home_team_id", 0)) or 0),
        int(match.get("match_awayteam_id", match.get("away_team_id", 0)) or 0),
        int(match.get("match_hometeam_score", match.get("home_score", 0)) or 0),
        int(match.get("match_awayteam_score", match.get("away_score", 0)) or 0),
    )
