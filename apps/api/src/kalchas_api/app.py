"""Kalchas API — FastAPI app."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from kalchas_core import __version__ as core_version
from kalchas_core.alert_outcomes import DEFAULT_RULES, evaluator_from_rule_rows, match_is_terminal
from kalchas_core.events import count_cards_by_side
from kalchas_core.match import MatchTimeline
from kalchas_core.odds import kickoff_home_away
from kalchas_core.runner import board_snapshot, home_away_odds, live_home_away_odds
from kalchas_core.strategies.omega import DEFAULT_ANGLE_SCALE, alert_theta_degrees
from kalchas_core.weights import WeightSet, strategy_names
from kalchas_football import apifootball_badge_url, https_asset_url
from pydantic import BaseModel, Field

from kalchas_api.admin import router as admin_router
from kalchas_api.signals import (
    goals_from_events,
    public_alert_signal,
)
from kalchas_api.tips import admin_router as tips_admin_router
from kalchas_api.tips import public_router as tips_public_router

logger = logging.getLogger("kalchas.api")

app = FastAPI(
    title="Kalchas API",
    version="3.0.0",
    description="Strategy analytics API. OpenAPI is the contract for the web client.",
)


class HealthResponse(BaseModel):
    status: str
    core_version: str
    strategies: list[str]


class ScannerStatusResponse(BaseModel):
    """Public feed health.

    Provider/billing text is deliberately absent: it reaches end users on the
    dashboard. The raw scanner error stays in the scanner logs.
    """

    state: str
    mode: str
    connected: bool
    messages_received: int = 0
    reconnects: int = 0
    last_message_at: str | None = None
    last_http_poll_at: str | None = None
    updated_at: str | None = None


class WeightsSummary(BaseModel):
    strategies: dict[str, dict[str, float]]


class StrategyRuleOut(BaseModel):
    strategy_slot: int
    strategy_name: str
    success_window_minutes: int
    expiration_buffer_minutes: int
    infinite_ttl: bool
    team_specific: bool
    enabled: bool
    source: str = "defaults"


class StrategyRulesResponse(BaseModel):
    rules: list[StrategyRuleOut]


class TeamSpecificPatch(BaseModel):
    team_specific: bool = Field(..., description="True = only trigger team goals count")


class SideValue(BaseModel):
    home: float | int = 0
    away: float | int = 0


class TeamStrategyCell(BaseModel):
    value: float
    triggered: bool = False


class StrategyBlock(BaseModel):
    teams: dict[str, TeamStrategyCell]
    threshold: float = 0
    match: int | None = None


class MatchEventOut(BaseModel):
    event_type: str
    minute: int
    side: str
    team: str | None = None
    player_name: str | None = None
    detail: str | None = None


class LastGoalOut(BaseModel):
    minute: int
    side: str
    team: str | None = None


class OddsLineOut(BaseModel):
    home: float | None = None
    draw: float | None = None
    away: float | None = None


class OddsOut(BaseModel):
    home: float | None = None
    draw: float | None = None
    away: float | None = None
    kickoff: OddsLineOut | None = None
    live: OddsLineOut | None = None


class LineupPlayerOut(BaseModel):
    player: str
    number: str = ""
    position: str = ""


class TeamLineupOut(BaseModel):
    starting: list[LineupPlayerOut] = Field(default_factory=list)
    substitutes: list[LineupPlayerOut] = Field(default_factory=list)
    coach: str | None = None


class SubstitutionOut(BaseModel):
    minute: int
    side: str
    player_out: str = ""
    player_in: str = ""


class TimelinePointOut(BaseModel):
    minute: int
    dangerous_attacks: SideValue
    attacks: SideValue
    shots_on_target: SideValue
    possession: SideValue
    rule_of_three: SideValue
    omega: SideValue
    kscore: float = 0


class MatchPanelResponse(BaseModel):
    match_id: str
    home_team: str
    away_team: str
    minute: int
    score: str
    league: str | None = None
    status_short: str | None = None
    minute_display: str | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None
    home_team_logo: str | None = None
    away_team_logo: str | None = None
    stat_lines: dict[str, SideValue] = Field(default_factory=dict)
    strategy_status: dict[str, StrategyBlock] = Field(default_factory=dict)
    events: list[MatchEventOut] = Field(default_factory=list)
    substitutions: list[SubstitutionOut] = Field(default_factory=list)
    timeline: list[TimelinePointOut] = Field(default_factory=list)
    lineup: dict[str, TeamLineupOut] = Field(default_factory=dict)


class H2HCountOut(BaseModel):
    count: int = 0
    pct: int = 0
    team: str | None = None


class H2HSummaryOut(BaseModel):
    home_wins: int = 0
    draws: int = 0
    away_wins: int = 0
    sample: int = 0


class H2HFixtureOut(BaseModel):
    match_id: str = ""
    home_team: str = ""
    away_team: str = ""
    home_score: int = 0
    away_score: int = 0
    match_date: str = ""
    league_name: str = ""
    home_team_id: int = 0
    away_team_id: int = 0


class H2HTimingOut(BaseModel):
    sample: int = 0
    late_goals: H2HCountOut = Field(default_factory=H2HCountOut)
    final_15: H2HCountOut = Field(default_factory=H2HCountOut)
    stoppage_time_goals: H2HCountOut = Field(default_factory=H2HCountOut)
    early_goals_15: H2HCountOut = Field(default_factory=H2HCountOut)
    fast_start_10: H2HCountOut = Field(default_factory=H2HCountOut)
    first_half_goals: H2HCountOut = Field(default_factory=H2HCountOut)
    btts_first_half: H2HCountOut = Field(default_factory=H2HCountOut)
    first_goal_before_30: H2HCountOut = Field(default_factory=H2HCountOut)


class H2HPatternsOut(BaseModel):
    sample: int = 0
    over_2_5: H2HCountOut = Field(default_factory=H2HCountOut)
    under_2_5: H2HCountOut = Field(default_factory=H2HCountOut)
    btts: H2HCountOut = Field(default_factory=H2HCountOut)
    home_cs: H2HCountOut = Field(default_factory=H2HCountOut)
    away_cs: H2HCountOut = Field(default_factory=H2HCountOut)
    avg_goals: float | None = None
    home_goals: int = 0
    away_goals: int = 0
    timing: H2HTimingOut | None = None


class H2HDataOut(BaseModel):
    home_team: str
    away_team: str
    insufficient: bool = True
    reason: str | None = None
    summary: H2HSummaryOut = Field(default_factory=H2HSummaryOut)
    fixtures: list[H2HFixtureOut] = Field(default_factory=list)
    patterns: H2HPatternsOut = Field(default_factory=H2HPatternsOut)


class H2HResponse(BaseModel):
    source: str
    data: H2HDataOut


class LiveMatchRow(BaseModel):
    match_id: str
    home_team: str
    away_team: str
    minute: int
    score: str
    league: str | None = None
    league_id: int | None = None
    status_short: str | None = None
    minute_display: str | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None
    home_team_logo: str | None = None
    away_team_logo: str | None = None
    hot_score: int = 0
    stat_lines: dict[str, SideValue] = Field(default_factory=dict)
    strategy_status: dict[str, StrategyBlock] = Field(default_factory=dict)
    active_strategies: list[str] = Field(default_factory=list)
    goal_events: list[MatchEventOut] = Field(default_factory=list)
    card_events: list[MatchEventOut] = Field(default_factory=list)
    last_goal: LastGoalOut | None = None
    country_name: str | None = None
    country_logo: str | None = None
    odds: OddsOut | None = None


class RecentAlertOut(BaseModel):
    id: int
    match_id: str
    strategy: str
    team: str | None = None
    value: float
    minute: int
    score: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    state: str
    kind: str = "monitoring"
    scoring_side: str | None = None
    goal_minute: int | None = None
    opponent_side: str | None = None
    created_at: str
    current_score: str | None = None
    current_minute: int | None = None
    current_status: str | None = None
    kickoff_home: float | None = None
    kickoff_away: float | None = None


def _team_logo(persisted: Any, team_id: int | None, team_name: str) -> str | None:
    """Live-row ``team_home_badge`` / ``team_away_badge`` first. Slug URL is last resort."""
    return https_asset_url(persisted) or apifootball_badge_url(team_id, team_name)


class SweetSpotOut(BaseModel):
    ht1_start: int = 28
    ht1_end: int = 44
    ht2_start: int = 72
    ht2_end: int = 88
    include_injury_time: bool = False


class LiveResponse(BaseModel):
    matches: list[LiveMatchRow]
    source: str
    recent_alerts: list[RecentAlertOut] = Field(default_factory=list)
    sweet_spot: SweetSpotOut = Field(default_factory=SweetSpotOut)


_LIVE_CACHE_TTL = 2.0
_live_cache_lock = threading.Lock()
_live_cache: tuple[float, LiveResponse] | None = None


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        core_version=core_version,
        strategies=list(strategy_names()),
    )


def _odds_line_out(block: Any) -> OddsLineOut | None:
    if not isinstance(block, dict):
        return None
    home = block.get("home")
    draw = block.get("draw")
    away = block.get("away")
    if home is None and draw is None and away is None:
        return None
    return OddsLineOut(
        home=float(home) if home is not None else None,
        draw=float(draw) if draw is not None else None,
        away=float(away) if away is not None else None,
    )


def _odds_out(raw: Any) -> OddsOut | None:
    data = _parse_jsonb(raw)
    if not data:
        return None
    kickoff = _odds_line_out(data.get("kickoff"))
    if kickoff is None:
        kickoff = _odds_line_out(
            {"home": data.get("home"), "draw": data.get("draw"), "away": data.get("away")}
        )
    live = _odds_line_out(data.get("live"))
    if kickoff is None and live is None:
        return None
    return OddsOut(
        home=kickoff.home if kickoff else None,
        draw=kickoff.draw if kickoff else None,
        away=kickoff.away if kickoff else None,
        kickoff=kickoff,
        live=live,
    )


def _alert_kickoff_odds(
    row: dict[str, Any], live_match: LiveMatchRow | None
) -> tuple[float | None, float | None]:
    payload = _parse_jsonb(row.get("payload"))
    odds_raw = payload.get("odds") if payload else None
    ko_home, ko_away = kickoff_home_away(odds_raw)
    if ko_home is not None or ko_away is not None:
        return ko_home, ko_away
    if live_match is None or live_match.odds is None:
        return None, None
    return kickoff_home_away(live_match.odds.model_dump())


def _public_feed_state(*, connected: bool, has_error: bool) -> str:
    """Collapse scanner internals into a state the dashboard can phrase safely."""
    if connected:
        return "live"
    return "paused" if has_error else "idle"


@app.get("/api/scanner-status", response_model=ScannerStatusResponse)
def scanner_status() -> ScannerStatusResponse:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        return ScannerStatusResponse(state="unconfigured", mode="unconfigured", connected=False)
    from kalchas_db.scanner_status import get_scanner_status_sync

    try:
        row = get_scanner_status_sync(dsn)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"scanner status unavailable: {exc}") from exc
    if row is None:
        return ScannerStatusResponse(state="starting", mode="starting", connected=False)
    connected = bool(row["connected"])
    return ScannerStatusResponse(
        state=_public_feed_state(connected=connected, has_error=bool(row.get("last_error"))),
        mode=str(row["mode"]),
        connected=connected,
        messages_received=int(row["messages_received"]),
        reconnects=int(row["reconnects"]),
        last_message_at=(
            row["last_message_at"].isoformat() if row.get("last_message_at") else None
        ),
        last_http_poll_at=(
            row["last_http_poll_at"].isoformat() if row.get("last_http_poll_at") else None
        ),
        updated_at=row["updated_at"].isoformat() if row.get("updated_at") else None,
    )


@app.get("/api/weights/defaults", response_model=WeightsSummary)
def default_weights() -> WeightsSummary:
    w = WeightSet.defaults()
    payload: dict[str, dict[str, float]] = {}
    for name in strategy_names():
        payload[name] = {row["key"]: float(row["current"]) for row in w.describe(name)}
    return WeightsSummary(strategies=payload)


def _parse_jsonb(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return dict(json.loads(value))
    if isinstance(value, dict):
        return dict(value)
    return {}


def _optional_league_id(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed else None


def _stat_lines_from_sides(
    home_stats: dict[str, Any], away_stats: dict[str, Any]
) -> dict[str, SideValue]:
    keys = (
        "shots_on_target",
        "shots_off_target",
        "attacks",
        "dangerous_attacks",
        "corners",
        "possession",
    )
    out: dict[str, SideValue] = {}
    for key in keys:
        out[key] = SideValue(
            home=home_stats.get(key, 0) or 0,
            away=away_stats.get(key, 0) or 0,
        )
    return out


def _strategy_blocks(raw: dict[str, Any]) -> dict[str, StrategyBlock]:
    out: dict[str, StrategyBlock] = {}
    for key, block in raw.items():
        teams_in = block.get("teams") or {}
        teams: dict[str, TeamStrategyCell] = {}
        for side in ("home", "away"):
            cell = teams_in.get(side) or {}
            teams[side] = TeamStrategyCell(
                value=float(cell.get("value", 0) or 0),
                triggered=bool(cell.get("triggered")),
            )
        out[key] = StrategyBlock(
            teams=teams,
            threshold=float(block.get("threshold", 0) or 0),
            match=block.get("match"),
        )
    return out


def _enrich_live_row(
    dsn: str,
    row: dict[str, Any],
    *,
    history: dict[str, dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> LiveMatchRow:
    from kalchas_db.matches import load_match_events_sync, load_match_history_sync

    match_id = str(row["match_id"])
    home_score = int(row["home_score"])
    away_score = int(row["away_score"])
    minute = int(row["minute"])
    home_stats = _parse_jsonb(row.get("home_stats"))
    away_stats = _parse_jsonb(row.get("away_stats"))
    stat_lines = _stat_lines_from_sides(home_stats, away_stats)

    strategy_status: dict[str, StrategyBlock] = {}
    active: list[str] = []
    hot = 0
    if events is None:
        events = load_match_events_sync(dsn, match_id)
    yellow, red = count_cards_by_side(events)
    if history is None:
        history = load_match_history_sync(dsn, match_id)
    if history:
        from kalchas_api.runtime import load_board_tuning

        tuning = load_board_tuning()
        timeline = MatchTimeline.from_raw(history, minute)
        odds_data = _parse_jsonb(row.get("odds"))
        home_odds, away_odds = home_away_odds(odds_data)
        live_home, live_away = live_home_away_odds(odds_data)
        board = board_snapshot(
            timeline,
            home_goals=home_score,
            away_goals=away_score,
            weights=tuning.weights,
            thresholds=tuning.thresholds,
            league_id=_optional_league_id(row.get("league_id")),
            league_name=str(row["league_name"]) if row.get("league_name") else None,
            country_name=str(row["country_name"]) if row.get("country_name") else None,
            home_odds=home_odds,
            away_odds=away_odds,
            live_home_odds=live_home,
            live_away_odds=live_away,
            yellow_cards=yellow,
            red_cards=red,
            conditions=tuning.conditions,
        )
        strategy_status = _strategy_blocks(board["strategy_status"])
        active = list(board.get("active_strategies") or [])
        hot = int(board.get("hot_score") or 0)
        if board.get("stat_lines"):
            stat_lines = {
                k: SideValue(home=v["home"], away=v["away"]) for k, v in board["stat_lines"].items()
            }
    events = [
        MatchEventOut(
            event_type=str(event["event_type"]),
            minute=int(event["minute"]),
            side=str(event["side"]),
            team=str(event["team"]) if event.get("team") else None,
            player_name=str(event["player_name"]) if event.get("player_name") else None,
            detail=str(event["detail"]) if event.get("detail") else None,
        )
        for event in events
    ]
    goals = [event for event in events if event.event_type == "goal"]
    cards = [event for event in events if event.event_type == "card"]
    stat_lines["yellow_cards"] = SideValue(home=yellow["home"], away=yellow["away"])
    stat_lines["red_cards"] = SideValue(home=red["home"], away=red["away"])
    last_goal = max(goals, key=lambda event: event.minute) if goals else None

    home_id = int(row["home_team_id"]) if row.get("home_team_id") is not None else None
    away_id = int(row["away_team_id"]) if row.get("away_team_id") is not None else None
    home_team = str(row["home_team"])
    away_team = str(row["away_team"])

    return LiveMatchRow(
        match_id=match_id,
        home_team=home_team,
        away_team=away_team,
        minute=minute,
        score=f"{home_score}-{away_score}",
        league=str(row["league_name"]) if row.get("league_name") else None,
        league_id=_optional_league_id(row.get("league_id")),
        status_short=str(row["status_short"]) if row.get("status_short") else None,
        minute_display=str(row["minute_display"]) if row.get("minute_display") else None,
        home_team_id=home_id,
        away_team_id=away_id,
        home_team_logo=_team_logo(row.get("home_team_logo"), home_id, home_team),
        away_team_logo=_team_logo(row.get("away_team_logo"), away_id, away_team),
        hot_score=hot,
        stat_lines=stat_lines,
        strategy_status=strategy_status,
        active_strategies=active,
        goal_events=goals,
        card_events=cards,
        last_goal=(
            LastGoalOut(minute=last_goal.minute, side=last_goal.side, team=last_goal.team)
            if last_goal
            else None
        ),
        country_name=str(row["country_name"]) if row.get("country_name") else None,
        country_logo=str(row["country_logo"]) if row.get("country_logo") else None,
        odds=_odds_out(row.get("odds")),
    )


def _recent_alert_display_value(strategy_key: str, stored: float, weights: WeightSet) -> float:
    """Omega alerts are stored as linear ω; the board and strip show θ°."""
    if strategy_key != "omega":
        return stored
    try:
        k_scale = float(weights.get("omega", "k_scale"))
    except (TypeError, ValueError):
        k_scale = DEFAULT_ANGLE_SCALE
    return round(alert_theta_degrees(stored, k_scale))


@app.get("/api/live", response_model=LiveResponse)
def live() -> LiveResponse:
    """Live board rows from scanner persistence + recomputed strategy cells."""
    global _live_cache
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        now = time.monotonic()
        cached = _live_cache
        if cached is not None and now - cached[0] < _LIVE_CACHE_TTL:
            return cached[1]
        with _live_cache_lock:
            cached = _live_cache
            if cached is not None and time.monotonic() - cached[0] < _LIVE_CACHE_TTL:
                return cached[1]
            payload = _build_live_response()
            _live_cache = (time.monotonic(), payload)
            return payload
    return _build_live_response()


def _build_live_response() -> LiveResponse:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        return LiveResponse(matches=[], source="empty", recent_alerts=[], sweet_spot=SweetSpotOut())
    from kalchas_db.alerts import list_recent_alerts_sync
    from kalchas_db.matches import (
        get_matches_sync,
        list_live_matches_sync,
        load_match_events_for_ids_sync,
        load_match_histories_sync,
    )
    from kalchas_db.rules import list_strategy_rules

    try:
        rows = [
            row
            for row in list_live_matches_sync(dsn)
            if not match_is_terminal(str(row.get("status_short") or "") or None)
        ]
        live_ids = [str(row["match_id"]) for row in rows]
        alert_rows = list_recent_alerts_sync(dsn)
        alert_ids = [str(row["match_id"]) for row in alert_rows]
        event_ids = list(dict.fromkeys(live_ids + alert_ids))
        histories = load_match_histories_sync(dsn, live_ids)
        events_by_id = load_match_events_for_ids_sync(dsn, event_ids)
        matches = [
            _enrich_live_row(
                dsn,
                row,
                history=histories.get(str(row["match_id"]), {}),
                events=events_by_id.get(str(row["match_id"]), []),
            )
            for row in rows
        ]
        try:
            evaluator = evaluator_from_rule_rows(list_strategy_rules(dsn))
        except Exception:  # noqa: BLE001 — rules table must not take down the board
            evaluator = evaluator_from_rule_rows(None)
        live_by_id = {m.match_id: m for m in matches}
        offboard: dict[str, dict[str, Any]] = {}
        missing_ids = [
            match_id for match_id in dict.fromkeys(alert_ids) if match_id not in live_by_id
        ]
        headers = get_matches_sync(dsn, missing_ids)
        for match_id in missing_ids:
            header = headers.get(match_id)
            if header is None:
                offboard[match_id] = {}
                continue
            offboard[match_id] = {
                "minute": int(header["minute"]),
                "score": f"{int(header['home_score'])}-{int(header['away_score'])}",
                "status_short": str(header["status_short"]) if header.get("status_short") else None,
                "goals": goals_from_events(events_by_id.get(match_id, [])),
            }
        try:
            from kalchas_api.runtime import load_board_tuning

            tuning = load_board_tuning()
            weights = tuning.weights
        except Exception:  # noqa: BLE001 — missing k_scale must not take down the board
            weights = WeightSet.defaults()
        recent_alerts = []
        for row in alert_rows:
            match_id = str(row["match_id"])
            live_match = live_by_id.get(match_id)
            if live_match is not None:
                current_minute = live_match.minute
                current_score = live_match.score
                status_short = live_match.status_short
                goals = goals_from_events(list(live_match.goal_events))
            else:
                ctx = offboard.get(match_id) or {}
                current_minute = ctx.get("minute")
                current_score = ctx.get("score")
                status_short = ctx.get("status_short")
                goals = list(ctx.get("goals") or [])
            try:
                signal = public_alert_signal(
                    row,
                    current_minute=current_minute,
                    current_score=current_score,
                    status_short=status_short,
                    goals=goals,
                    evaluator=evaluator,
                )
            except Exception:
                logger.exception("public signal failed for alert %s", row.get("id"))
                continue
            kickoff_home, kickoff_away = _alert_kickoff_odds(row, live_match)
            recent_alerts.append(
                RecentAlertOut(
                    id=int(row["id"]),
                    match_id=match_id,
                    strategy=str(row["strategy_key"]),
                    team=str(row["team"]) if row.get("team") else None,
                    value=_recent_alert_display_value(
                        str(row["strategy_key"]), float(row["value"]), weights
                    ),
                    minute=int(row["minute"]),
                    score=str(row["score"]) if row.get("score") else None,
                    home_team=str(row["home_team"]) if row.get("home_team") else None,
                    away_team=str(row["away_team"]) if row.get("away_team") else None,
                    state=signal.state,
                    kind=signal.kind,
                    scoring_side=signal.scoring_side,
                    goal_minute=signal.goal_minute,
                    opponent_side=signal.opponent_side,
                    created_at=(
                        row["created_at"].isoformat()
                        if hasattr(row["created_at"], "isoformat")
                        else str(row["created_at"])
                    ),
                    current_score=str(current_score) if current_score else None,
                    current_minute=int(current_minute) if current_minute is not None else None,
                    current_status=str(status_short) if status_short else None,
                    kickoff_home=kickoff_home,
                    kickoff_away=kickoff_away,
                )
            )
    except Exception as exc:
        logger.exception("live feed unavailable")
        raise HTTPException(status_code=503, detail=f"live feed unavailable: {exc}") from exc
    sweet_spot = SweetSpotOut()
    try:
        from kalchas_db.settings import get_board_settings

        sweet_spot = SweetSpotOut.model_validate(get_board_settings(dsn))
    except Exception:  # noqa: BLE001 — missing board_settings must not take down live
        sweet_spot = SweetSpotOut()
    return LiveResponse(
        matches=matches,
        source="postgres",
        recent_alerts=recent_alerts,
        sweet_spot=sweet_spot,
    )


def _side_value(raw: Any) -> SideValue:
    if not isinstance(raw, dict):
        return SideValue()
    return SideValue(home=raw.get("home", 0) or 0, away=raw.get("away", 0) or 0)


def _lineup_side(raw: Any) -> TeamLineupOut:
    data = raw if isinstance(raw, dict) else {}
    return TeamLineupOut(
        starting=[
            LineupPlayerOut(
                player=str(item.get("player") or ""),
                number=str(item.get("number") or ""),
                position=str(item.get("position") or ""),
            )
            for item in (data.get("starting") or [])
            if isinstance(item, dict)
        ],
        substitutes=[
            LineupPlayerOut(
                player=str(item.get("player") or ""),
                number=str(item.get("number") or ""),
                position=str(item.get("position") or ""),
            )
            for item in (data.get("substitutes") or [])
            if isinstance(item, dict)
        ],
        coach=str(data["coach"]) if data.get("coach") else None,
    )


def _panel_to_response(raw: dict[str, Any]) -> MatchPanelResponse:
    events = [
        MatchEventOut(
            event_type=str(event["event_type"]),
            minute=int(event["minute"]),
            side=str(event["side"]),
            team=str(event["team"]) if event.get("team") else None,
            player_name=str(event["player_name"]) if event.get("player_name") else None,
            detail=str(event["detail"]) if event.get("detail") else None,
        )
        for event in raw.get("events") or []
    ]
    yellow, red = count_cards_by_side(raw.get("events") or [])
    stat_lines = {key: _side_value(value) for key, value in (raw.get("stat_lines") or {}).items()}
    stat_lines["yellow_cards"] = SideValue(home=yellow["home"], away=yellow["away"])
    stat_lines["red_cards"] = SideValue(home=red["home"], away=red["away"])
    home_id = raw.get("home_team_id")
    away_id = raw.get("away_team_id")
    home_team = str(raw["home_team"])
    away_team = str(raw["away_team"])
    timeline = [
        TimelinePointOut(
            minute=int(point["minute"]),
            dangerous_attacks=_side_value(point.get("dangerous_attacks")),
            attacks=_side_value(point.get("attacks")),
            shots_on_target=_side_value(point.get("shots_on_target")),
            possession=_side_value(point.get("possession")),
            rule_of_three=_side_value(point.get("rule_of_three")),
            omega=_side_value(point.get("omega")),
            kscore=float(point.get("kscore") or 0),
        )
        for point in raw.get("timeline") or []
    ]
    lineup_raw = raw.get("lineup") or {}
    return MatchPanelResponse(
        match_id=str(raw["match_id"]),
        home_team=home_team,
        away_team=away_team,
        minute=int(raw["minute"]),
        score=str(raw["score"]),
        league=str(raw["league"]) if raw.get("league") else None,
        status_short=str(raw["status_short"]) if raw.get("status_short") else None,
        minute_display=str(raw["minute_display"]) if raw.get("minute_display") else None,
        home_team_id=int(home_id) if home_id is not None else None,
        away_team_id=int(away_id) if away_id is not None else None,
        home_team_logo=_team_logo(
            raw.get("home_team_logo"),
            int(home_id) if home_id is not None else None,
            home_team,
        ),
        away_team_logo=_team_logo(
            raw.get("away_team_logo"),
            int(away_id) if away_id is not None else None,
            away_team,
        ),
        stat_lines=stat_lines,
        strategy_status=_strategy_blocks(raw.get("strategy_status") or {}),
        events=events,
        substitutions=[
            SubstitutionOut(
                minute=int(item["minute"]),
                side=str(item["side"]),
                player_out=str(item.get("player_out") or ""),
                player_in=str(item.get("player_in") or ""),
            )
            for item in raw.get("substitutions") or []
        ],
        timeline=timeline,
        lineup={
            "home": _lineup_side(lineup_raw.get("home")),
            "away": _lineup_side(lineup_raw.get("away")),
        },
    )


@app.get("/api/match/{match_id}/panel", response_model=MatchPanelResponse)
def match_panel(match_id: str) -> MatchPanelResponse:
    """Overlay payload from persisted live/WS rows — no extra provider HTTP."""
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="live feed unavailable")
    from kalchas_api.panel import build_match_panel

    try:
        raw = build_match_panel(dsn, match_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"match panel unavailable: {exc}") from exc
    if raw is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return _panel_to_response(raw)


@app.get("/api/match/{match_id}/h2h", response_model=H2HResponse)
def match_h2h(match_id: str) -> H2HResponse:
    """Head-to-head overlay. Cached 7 days. One get_H2H call on a miss."""
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="live feed unavailable")
    from kalchas_db.matches import get_match_sync
    from kalchas_db.panel_cache import load_panel_cache, pair_cache_key, save_panel_cache

    from kalchas_api.h2h import DEFAULT_LAST, build_h2h_payload, empty_h2h_payload

    header = get_match_sync(dsn, match_id)
    if header is None:
        raise HTTPException(status_code=404, detail="Match not found")
    home_team = str(header.get("home_team") or "")
    away_team = str(header.get("away_team") or "")
    try:
        home_id = int(header.get("home_team_id") or 0)
        away_id = int(header.get("away_team_id") or 0)
    except (TypeError, ValueError):
        home_id = away_id = 0
    if home_id <= 0 or away_id <= 0 or home_id == away_id:
        return H2HResponse(
            source="empty",
            data=H2HDataOut.model_validate(
                empty_h2h_payload(
                    home_team=home_team, away_team=away_team, reason="missing_team_ids"
                )
            ),
        )

    cache_key = pair_cache_key("h2h", home_id, away_id)
    try:
        cached = load_panel_cache(dsn, cache_key)
    except Exception:  # noqa: BLE001 — missing table still serves a live fetch
        cached = None
    if cached:
        cached["home_team"] = home_team or cached.get("home_team") or ""
        cached["away_team"] = away_team or cached.get("away_team") or ""
        return H2HResponse(source="cache", data=H2HDataOut.model_validate(cached))

    from kalchas_football import FootballAPIClient, RateLimitBudgetExceeded

    try:
        client = FootballAPIClient()
        try:
            fixtures = client.get_head_to_head(home_id, away_id, last=DEFAULT_LAST)
        finally:
            client.close()
    except RateLimitBudgetExceeded:
        raise HTTPException(status_code=503, detail="H2H rate limit") from None
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"H2H unavailable: {exc}") from exc

    payload = build_h2h_payload(
        fixtures,
        home_team_id=home_id,
        away_team_id=away_id,
        home_team=home_team,
        away_team=away_team,
    )
    if payload["summary"]["sample"] >= 5:
        try:
            save_panel_cache(dsn, cache_key, payload)
        except Exception:  # noqa: BLE001,S110 — cache write must not hide a good payload
            pass
    return H2HResponse(source="api", data=H2HDataOut.model_validate(payload))


def _default_rule_outs() -> list[StrategyRuleOut]:
    return [
        StrategyRuleOut(
            strategy_slot=r.strategy_slot,
            strategy_name=r.strategy_name,
            success_window_minutes=r.success_window_minutes,
            expiration_buffer_minutes=r.expiration_buffer_minutes,
            infinite_ttl=r.infinite_ttl,
            team_specific=r.team_specific,
            enabled=r.enabled,
            source="defaults",
        )
        for r in DEFAULT_RULES
    ]


@app.get("/api/strategy-rules", response_model=StrategyRulesResponse)
def strategy_rules() -> StrategyRulesResponse:
    """Confirmation rules. Uses Postgres when DATABASE_URL is set, else defaults."""
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        return StrategyRulesResponse(rules=_default_rule_outs())
    from kalchas_db.rules import list_strategy_rules

    rows = list_strategy_rules(dsn)
    return StrategyRulesResponse(
        rules=[
            StrategyRuleOut(
                strategy_slot=int(r["strategy_slot"]),
                strategy_name=str(r["strategy_name"]),
                success_window_minutes=int(r["success_window_minutes"]),
                expiration_buffer_minutes=int(r["expiration_buffer_minutes"]),
                infinite_ttl=bool(r["infinite_ttl"]),
                team_specific=bool(r["team_specific"]),
                enabled=bool(r["enabled"]),
                source="database",
            )
            for r in rows
        ]
    )


@app.patch("/api/strategy-rules/{slot}", response_model=StrategyRuleOut)
def patch_team_specific(slot: int, body: TeamSpecificPatch, request: Request) -> StrategyRuleOut:
    """Toggle team_specific for a slot. Requires ADMIN_PASSWORD session."""
    from kalchas_api.admin_auth import require_admin
    from kalchas_api.runtime import clear_board_tuning_cache

    require_admin(request)
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required to change settings")
    from kalchas_db.rules import set_team_specific

    row = set_team_specific(dsn, slot, body.team_specific)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No strategy_rules row for slot {slot}")
    clear_board_tuning_cache()
    return StrategyRuleOut(
        strategy_slot=int(row["strategy_slot"]),
        strategy_name=str(row["strategy_name"]),
        success_window_minutes=int(row["success_window_minutes"]),
        expiration_buffer_minutes=int(row["expiration_buffer_minutes"]),
        infinite_ttl=bool(row["infinite_ttl"]),
        team_specific=bool(row["team_specific"]),
        enabled=bool(row["enabled"]),
        source="database",
    )


def _web_dist() -> Path:
    return Path(os.environ.get("WEB_DIST", "/app/apps/web/dist"))


def _mount_web_ui() -> None:
    """Serve the Vite build from the same origin as /api (production)."""
    dist = _web_dist()
    index = dist / "index.html"
    if not index.is_file():
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="web-assets")

    @app.get("/", include_in_schema=False)
    def spa_index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        reserved = {"api", "health", "docs", "redoc", "openapi.json", "assets", "tips.csv"}
        head = full_path.split("/", 1)[0]
        if head in reserved or full_path in reserved:
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (dist / full_path).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            return FileResponse(index)
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


app.include_router(admin_router)
app.include_router(tips_admin_router)
app.include_router(tips_public_router)
_mount_web_ui()
