"""Pre-match watchlist: day lists, a month calendar and each match's page.

Read-only. The scanner builds every day into the watchlist archive and adds
the results after full time; this router never calls the provider, so a busy
page costs nothing on the budget.

The stored pages also carry our live-alert hit rate per league. That stays
internal: the models below leave it out, so it is never served publicly.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

Watch = Literal["strong", "look", "quiet"]
Outcome = Literal["landed", "missed"]


class TeamRef(BaseModel):
    name: str
    badge: str | None = None
    position: int | None = None


class Odds1x2(BaseModel):
    home: float | None = None
    draw: float | None = None
    away: float | None = None


class Tag(BaseModel):
    label: str
    outcome: Outcome | None = None


class RowResult(BaseModel):
    status: Literal["finished", "off"]
    label: str
    home: int | None = None
    away: int | None = None
    pens: list[int] | None = None


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
    tags: list[Tag]
    result: RowResult | None = None
    outcome: Outcome | None = None
    outcome_note: str = ""


class LeagueGroup(BaseModel):
    key: str
    name: str
    country: str
    logo: str | None = None
    match_ids: list[str]


class Tally(BaseModel):
    landed: int = 0
    settled: int = 0


class DaySummary(BaseModel):
    matches: int = 0
    strong: int = 0
    look: int = 0
    finished: int = 0
    called_off: int = 0
    top: Tally = Tally()
    strong_tally: Tally = Tally()
    look_tally: Tally = Tally()


class WatchlistDay(BaseModel):
    status: Literal["ready", "preparing", "none"]
    day: str
    today: str
    first_day: str | None = None
    built_at: str | None = None
    partial: bool = False
    matches: list[WatchRow] = []
    leagues: list[LeagueGroup] = []
    shortlist: list[str] = []
    summary: DaySummary | None = None


class MonthDay(BaseModel):
    day: str
    summary: DaySummary


class WatchlistMonth(BaseModel):
    month: str
    today: str
    first_day: str | None = None
    days: list[MonthDay]


class PatternOut(BaseModel):
    key: str
    tag: str
    title: str
    detail: str
    brief: str
    score: float
    outcome: Outcome | None = None
    outcome_note: str = ""


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


class Goal(BaseModel):
    time: str
    half: str
    side: str


class MatchResult(BaseModel):
    status: Literal["finished", "off"]
    label: str
    home: int | None = None
    away: int | None = None
    home_90: int | None = None
    away_90: int | None = None
    ht: list[int] | None = None
    pens: list[int] | None = None
    timed: bool = False
    goals: list[Goal] = []


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
    result: MatchResult | None = None


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


def board_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(board_zone()).date()


def resolve_day(day: str, now: datetime | None = None) -> str:
    """``today``, ``tomorrow`` or a past ``YYYY-MM-DD`` (nothing after tomorrow)."""
    today = board_today(now)
    if day == "today":
        return today.isoformat()
    if day == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    try:
        picked = date.fromisoformat(day) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None
    except ValueError:
        picked = None
    if picked is None or picked > today + timedelta(days=1):
        raise HTTPException(status_code=404, detail="Unknown day")
    return picked.isoformat()


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"watchlist unavailable: {exc}")


@router.get("/day/{day}", response_model=WatchlistDay)
def watchlist_day(day: str) -> WatchlistDay:
    """One day's list. Today and tomorrow say ``preparing`` until built; a
    past day without a list says ``none``."""
    from kalchas_db.watchlist import first_watchlist_day, load_watchlist_day

    date_str = resolve_day(day)
    today = board_today().isoformat()
    try:
        dsn = _dsn()
        doc = load_watchlist_day(dsn, date_str)
        first = first_watchlist_day(dsn)
    except HTTPException:
        raise
    except Exception as exc:
        raise _unavailable(exc) from exc
    if not doc:
        return WatchlistDay(
            status="none" if date_str < today else "preparing",
            day=date_str,
            today=today,
            first_day=first,
        )
    return WatchlistDay.model_validate(
        {**doc, "status": "ready", "day": date_str, "today": today, "first_day": first}
    )


@router.get("/month/{month}", response_model=WatchlistMonth)
def watchlist_month(month: str) -> WatchlistMonth:
    """Every listed day of a month (``YYYY-MM``) with its tally, for the calendar."""
    from kalchas_db.watchlist import first_watchlist_day, load_watchlist_month

    found = re.fullmatch(r"(\d{4})-(\d{2})", month)
    if not found or not 1 <= int(found.group(2)) <= 12:
        raise HTTPException(status_code=404, detail="Unknown month")
    start = date(int(found.group(1)), int(found.group(2)), 1)
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1)
    try:
        dsn = _dsn()
        days = load_watchlist_month(dsn, start, end)
        first = first_watchlist_day(dsn)
    except HTTPException:
        raise
    except Exception as exc:
        raise _unavailable(exc) from exc
    return WatchlistMonth.model_validate(
        {"month": month, "today": board_today().isoformat(), "first_day": first, "days": days}
    )


@router.get("/match/{match_id}", response_model=MatchResearch)
def watchlist_match(match_id: str) -> MatchResearch:
    from kalchas_db.watchlist import load_watchlist_match

    if not match_id.isdigit():
        raise HTTPException(status_code=404, detail="Match not found")
    try:
        doc = load_watchlist_match(_dsn(), match_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _unavailable(exc) from exc
    if not doc:
        raise HTTPException(status_code=404, detail="Match not found")
    return MatchResearch.model_validate(doc)
