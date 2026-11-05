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
import threading
import time
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
    lead_key: str = ""
    lead_side: Literal["home", "away", ""] | None = None
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


class Pick(BaseModel):
    """A strong watch, as the live board shows it."""

    match_id: str
    day: str
    kickoff: str
    home: TeamRef
    away: TeamRef
    lead_key: str = ""
    lead_side: Literal["home", "away", ""] | None = None
    tag: str = ""
    headline: str
    reason: str
    result: RowResult | None = None
    outcome: Outcome | None = None
    outcome_note: str = ""


class LivePicks(BaseModel):
    today: str
    next: Pick | None = None
    picks: list[Pick] = []


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
    side: Literal["home", "away", ""] = ""
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
    cards: int | None = None
    red_card: bool | None = None
    corners: int | None = None
    goals: list[Goal] = []


class ShotLine(BaseModel):
    stat: Literal["shots", "on_target"]
    at_least: int
    hits: int


class ShooterOut(BaseModel):
    name: str
    apps: int
    minutes: int
    shots: list[int]
    per_90: float
    on_target_per_90: float
    lines: list[ShotLine]


class TeamShots(BaseModel):
    games: int
    source: Literal["competition", "all"]
    players: list[ShooterOut]


class ShotsPair(BaseModel):
    home: TeamShots | None = None
    away: TeamShots | None = None


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
    shots: ShotsPair | None = None
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


def _pick(row: dict, day: str) -> Pick:
    tags = row.get("tags") or []
    return Pick.model_validate(
        {**row, "day": day, "tag": (tags[0].get("label") if tags else "") or ""}
    )


@router.get("/picks", response_model=LivePicks)
def watchlist_picks() -> LivePicks:
    """For the live board: every strong watch of yesterday and today (late
    games cross midnight), and the next one of today still to kick off."""
    from kalchas_db.watchlist import load_watchlist_day

    now = datetime.now(UTC)
    today = board_today(now)
    picks: list[Pick] = []
    upcoming: list[Pick] = []
    try:
        dsn = _dsn()
        for day in (today - timedelta(days=1), today):
            doc = load_watchlist_day(dsn, day.isoformat()) or {}
            for row in doc.get("matches") or []:
                if row.get("watch") != "strong":
                    continue
                pick = _pick(row, day.isoformat())
                picks.append(pick)
                try:
                    starts = datetime.fromisoformat(pick.kickoff)
                except ValueError:
                    continue
                if day == today and starts > now:
                    upcoming.append(pick)
    except HTTPException:
        raise
    except Exception as exc:
        raise _unavailable(exc) from exc
    upcoming.sort(key=lambda p: (p.kickoff, p.match_id))
    return LivePicks(today=today.isoformat(), next=upcoming[0] if upcoming else None, picks=picks)


class LiveScore(BaseModel):
    home: int
    away: int
    minute: int = 0
    display: str = ""
    status: str = ""
    finished: bool = False


ENDED = frozenset({"FT", "AET", "PEN"})
CALLED_OFF = frozenset({"PST", "CANC", "AWD"})
LIVE_TTL_SEC = 15.0
_live_scores: dict[str, tuple[float, dict[str, LiveScore]]] = {}
_live_lock = threading.Lock()


def _live_for(dsn: str, date_str: str) -> dict[str, LiveScore]:
    """Live score for each match on that day's list that is under way or just
    finished and not yet settled, from the rows the live scanner keeps."""
    from kalchas_db.matches import get_matches_sync
    from kalchas_db.watchlist import load_watchlist_day

    doc = load_watchlist_day(dsn, date_str) or {}
    now = datetime.now(UTC)
    ids = []
    for row in doc.get("matches") or []:
        if row.get("result"):
            continue
        try:
            started = datetime.fromisoformat(str(row.get("kickoff"))) <= now
        except ValueError:
            started = False
        if started:
            ids.append(str(row["match_id"]))
    out: dict[str, LiveScore] = {}
    for match_id, row in get_matches_sync(dsn, ids).items():
        status = str(row.get("status_short") or "").upper()
        if status in CALLED_OFF or row.get("home_score") is None:
            continue
        out[match_id] = LiveScore(
            home=int(row["home_score"]),
            away=int(row["away_score"]),
            minute=int(row.get("minute") or 0),
            display=str(row.get("minute_display") or ""),
            status=status,
            finished=status in ENDED,
        )
    return out


@router.get("/live/{day}", response_model=dict[str, LiveScore])
def watchlist_live(day: str) -> dict[str, LiveScore]:
    """Scores of the day's listed matches while they're played, until each is
    settled. Shared for 15 seconds, so many open pages cost one lookup."""
    date_str = resolve_day(day)
    now = time.monotonic()
    hit = _live_scores.get(date_str)
    if hit and now - hit[0] < LIVE_TTL_SEC:
        return hit[1]
    with _live_lock:
        hit = _live_scores.get(date_str)
        if hit and time.monotonic() - hit[0] < LIVE_TTL_SEC:
            return hit[1]
        try:
            scores = _live_for(_dsn(), date_str)
        except HTTPException:
            raise
        except Exception as exc:
            raise _unavailable(exc) from exc
        _live_scores[date_str] = (time.monotonic(), scores)
        return scores


class ParlayLeg(BaseModel):
    match_id: str
    kickoff: str
    league: str
    country: str
    home: TeamRef
    away: TeamRef
    watch: Watch
    market: str
    label: str
    price: float
    hit: int
    n: int
    brief: str
    score: float
    result: RowResult | None = None
    outcome: Outcome | None = None
    outcome_note: str = ""


class Unpriced(BaseModel):
    match_id: str
    home: str
    away: str
    tags: list[str]


class ParlayOrder(BaseModel):
    safer: list[str] = []
    balanced: list[str] = []
    bolder: list[str] = []


class ParlayDay(BaseModel):
    status: Literal["ready", "preparing", "none"]
    day: str
    today: str
    first_day: str | None = None
    legs: list[ParlayLeg] = []
    order: ParlayOrder = ParlayOrder()
    unpriced: list[Unpriced] = []


PARLAY_TTL_SEC = 60.0
_parlays: dict[str, tuple[float, dict]] = {}
_parlay_lock = threading.Lock()


def _parlay_for(dsn: str, date_str: str) -> dict:
    """The day's legs, built from every match page of that day. Kept for a
    minute: a day has a few hundred pages and the slider never re-asks."""
    from kalchas_core.watchlist.parlay import build
    from kalchas_db.watchlist import load_watchlist_matches_on

    hit = _parlays.get(date_str)
    if hit and time.monotonic() - hit[0] < PARLAY_TTL_SEC:
        return hit[1]
    with _parlay_lock:
        hit = _parlays.get(date_str)
        if hit and time.monotonic() - hit[0] < PARLAY_TTL_SEC:
            return hit[1]
        pages = load_watchlist_matches_on(dsn, date_str)
        built = build(pages) if pages else {}
        _parlays[date_str] = (time.monotonic(), built)
        return built


@router.get("/parlay/{day}", response_model=ParlayDay)
def watchlist_parlay(day: str) -> ParlayDay:
    """Every leg the day's parlay can use, with the order each style takes them."""
    from kalchas_db.watchlist import first_watchlist_day

    date_str = resolve_day(day)
    today = board_today().isoformat()
    try:
        dsn = _dsn()
        built = _parlay_for(dsn, date_str)
        first = first_watchlist_day(dsn)
    except HTTPException:
        raise
    except Exception as exc:
        raise _unavailable(exc) from exc
    if not built:
        return ParlayDay(
            status="none" if date_str < today else "preparing",
            day=date_str,
            today=today,
            first_day=first,
        )
    return ParlayDay.model_validate(
        {**built, "status": "ready", "day": date_str, "today": today, "first_day": first}
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
