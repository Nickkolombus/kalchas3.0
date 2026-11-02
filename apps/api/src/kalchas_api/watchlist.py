"""Pre-match watchlist: the day list and each match's research page.

Read-only. The scanner's watchlist job builds both into ``panel_cache``; this
router never calls the provider, so a busy page costs nothing on the budget.

The cached pages also carry our live-alert hit rate per league. That stays
internal: the models below leave it out, so it is never served publicly.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

PAGE_TTL_HOURS = 48
Watch = Literal["strong", "look", "quiet"]


class TeamRef(BaseModel):
    name: str
    badge: str | None = None
    position: int | None = None


class Odds1x2(BaseModel):
    home: float | None = None
    draw: float | None = None
    away: float | None = None


class WatchRow(BaseModel):
    match_id: str
    kickoff: str
    league_key: str
    home: TeamRef
    away: TeamRef
    odds: Odds1x2 | None = None
    watch: Watch
    score: float
    headline: str
    reason: str
    tags: list[str]


class LeagueGroup(BaseModel):
    key: str
    name: str
    country: str
    logo: str | None = None
    match_ids: list[str]


class WatchlistDay(BaseModel):
    status: Literal["ready", "preparing"]
    day: str
    built_at: str | None = None
    partial: bool = False
    matches: list[WatchRow] = []
    leagues: list[LeagueGroup] = []
    shortlist: list[str] = []


class PatternOut(BaseModel):
    key: str
    tag: str
    title: str
    detail: str
    brief: str
    score: float


class Count(BaseModel):
    count: int
    n: int


class PatternRow(BaseModel):
    key: str
    label: str
    home: Count
    away: Count
    league_pct: int
    h2h: Count | None = None
    flagged: bool


class FormGameOut(BaseModel):
    match_date: str
    opponent: str
    venue: Literal["H", "A"]
    goals_for: int
    goals_against: int
    result: Literal["W", "D", "L"]


class TeamFormOut(BaseModel):
    games: int
    source: Literal["competition", "all"]
    wins: int
    draws: int
    losses: int
    scored_per_game: float
    conceded_per_game: float
    clean_sheets: int
    failed_to_score: int
    results: list[FormGameOut]


class FormPair(BaseModel):
    home: TeamFormOut
    away: TeamFormOut


class TimingSide(BaseModel):
    games: int
    of: int
    scored: list[int]
    conceded: list[int]


class Timing(BaseModel):
    labels: list[str]
    home: TimingSide
    away: TimingSide
    note: str


class Meeting(BaseModel):
    match_date: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int


class H2HOut(BaseModel):
    sample: int
    home_wins: int
    draws: int
    away_wins: int
    avg_goals: float | None = None
    btts: int
    over_2_5: int
    meetings: list[Meeting]


class TableRow(BaseModel):
    position: int
    team_id: int
    team: str
    played: int
    goal_difference: int
    points: int


class LeagueOut(BaseModel):
    id: int
    name: str
    country: str
    logo: str | None = None
    round: str


class TeamOut(BaseModel):
    id: int
    name: str
    badge: str | None = None
    position: int | None = None
    points: int | None = None


class MatchOdds(Odds1x2):
    over_2_5: float | None = None
    under_2_5: float | None = None
    btts_yes: float | None = None
    btts_no: float | None = None


class MatchResearch(BaseModel):
    match_id: str
    day: str
    built_at: str
    kickoff: str
    league: LeagueOut
    home: TeamOut
    away: TeamOut
    odds: MatchOdds | None = None
    watch: Watch
    score: float
    points: list[PatternOut]
    patterns: list[PatternOut]
    pattern_table: list[PatternRow]
    form: FormPair
    timing: Timing
    h2h: H2HOut | None = None
    table: list[TableRow]


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="watchlist unavailable")
    return dsn


def board_zone() -> timezone:
    """The scanner's fixture time zone, so "tomorrow" is the same day it built."""
    offset = os.environ.get("FOOTBALL_TIMEZONE", "+03:00")
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", offset.strip())
    if not match:
        return UTC
    sign = 1 if match.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3))))


def resolve_day(day: str, now: datetime | None = None) -> str:
    today = (now or datetime.now(UTC)).astimezone(board_zone()).date()
    if day == "today":
        return today.isoformat()
    if day == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    raise HTTPException(status_code=404, detail="Unknown day")


@router.get("/day/{day}", response_model=WatchlistDay)
def watchlist_day(day: str) -> WatchlistDay:
    """``today`` or ``tomorrow`` in the board's time zone."""
    from kalchas_db.panel_cache import load_panel_cache

    date_str = resolve_day(day)
    try:
        doc = load_panel_cache(_dsn(), f"watchlist_day_{date_str}", ttl_hours=PAGE_TTL_HOURS)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"watchlist unavailable: {exc}") from exc
    if not doc:
        return WatchlistDay(status="preparing", day=date_str)
    return WatchlistDay.model_validate({**doc, "status": "ready"})


@router.get("/match/{match_id}", response_model=MatchResearch)
def watchlist_match(match_id: str) -> MatchResearch:
    from kalchas_db.panel_cache import load_panel_cache

    if not match_id.isdigit():
        raise HTTPException(status_code=404, detail="Match not found")
    try:
        doc = load_panel_cache(_dsn(), f"watchlist_match_{match_id}", ttl_hours=PAGE_TTL_HOURS)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"watchlist unavailable: {exc}") from exc
    if not doc:
        raise HTTPException(status_code=404, detail="Match not found")
    return MatchResearch.model_validate(doc)
