"""Recompute live board cells with in-progress admin weights (no writes)."""

from __future__ import annotations

import json
from typing import Any

from kalchas_core.alert_outcomes import match_is_terminal
from kalchas_core.events import count_cards_by_side
from kalchas_core.match import MatchTimeline
from kalchas_core.runner import board_snapshot, home_away_odds, live_home_away_odds
from kalchas_core.weights import WeightSet
from kalchas_db.settings import SLOT_BY_KEY


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


def _cell_pair(block: dict[str, Any] | None) -> dict[str, Any]:
    teams = (block or {}).get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    return {
        "home": float(home.get("value") or 0),
        "away": float(away.get("value") or 0),
        "home_triggered": bool(home.get("triggered")),
        "away_triggered": bool(away.get("triggered")),
        "match": (block or {}).get("match"),
    }


def _snapshot_row(
    row: dict[str, Any],
    history: dict[str, Any],
    weights: WeightSet,
    thresholds: dict[int, float],
    strategy_key: str,
    *,
    conditions: dict[int, list] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not history:
        return None
    minute = int(row.get("minute") or 0)
    timeline = MatchTimeline.from_raw(history, minute)
    if not timeline:
        return None
    odds_data = _parse_jsonb(row.get("odds"))
    home_odds, away_odds = home_away_odds(odds_data)
    live_home, live_away = live_home_away_odds(odds_data)
    yellow, red = count_cards_by_side(events)
    board = board_snapshot(
        timeline,
        home_goals=int(row.get("home_score") or 0),
        away_goals=int(row.get("away_score") or 0),
        weights=weights,
        thresholds=thresholds,
        league_id=_optional_league_id(row.get("league_id")),
        league_name=str(row["league_name"]) if row.get("league_name") else None,
        country_name=str(row["country_name"]) if row.get("country_name") else None,
        home_odds=home_odds,
        away_odds=away_odds,
        live_home_odds=live_home,
        live_away_odds=live_away,
        yellow_cards=yellow,
        red_cards=red,
        conditions=conditions,
    )
    status = board.get("strategy_status") or {}
    return {
        "match_id": str(row["match_id"]),
        "home_team": str(row.get("home_team") or ""),
        "away_team": str(row.get("away_team") or ""),
        "minute": minute,
        "score": f"{int(row.get('home_score') or 0)}-{int(row.get('away_score') or 0)}",
        "league": str(row["league_name"]) if row.get("league_name") else None,
        "status_short": str(row["status_short"]) if row.get("status_short") else None,
        "hot": int(board.get("hot_score") or 0),
        "strategy": _cell_pair(status.get(strategy_key)),
        "kscore": _cell_pair(status.get("kscore")),
    }


def preview_live_matches(
    dsn: str,
    *,
    strategy_key: str,
    overlay: dict[str, float],
    match_id: str | None = None,
    limit: int = 8,
    conditions_overlay: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    from kalchas_db.matches import (
        get_match_sync,
        list_live_matches_sync,
        load_match_events_sync,
        load_match_history_sync,
    )

    from kalchas_api.runtime import load_board_tuning

    tuning = load_board_tuning()
    baseline = tuning.weights
    thresholds = tuning.thresholds
    saved_conditions = dict(tuning.conditions)
    preview_weights = baseline.with_overrides({strategy_key: overlay}) if overlay else baseline
    preview_conditions = dict(saved_conditions)
    slot = SLOT_BY_KEY.get(strategy_key)
    if slot is not None and conditions_overlay is not None:
        preview_conditions[slot] = list(conditions_overlay)
    live = [
        row
        for row in list_live_matches_sync(dsn)
        if not match_is_terminal(str(row.get("status_short") or "") or None)
    ]
    ordered: list[dict[str, Any]] = []
    pin = (match_id or "").strip()
    if pin:
        pinned = next((row for row in live if str(row["match_id"]) == pin), None)
        if pinned is None:
            header = get_match_sync(dsn, pin)
            if header is not None:
                pinned = header
        if pinned is not None:
            ordered.append(pinned)
    for row in live:
        if str(row["match_id"]) == pin:
            continue
        ordered.append(row)

    out: list[dict[str, Any]] = []
    for row in ordered:
        match_key = str(row["match_id"])
        history = load_match_history_sync(dsn, match_key)
        events = load_match_events_sync(dsn, match_key)
        preview = _snapshot_row(
            row,
            history,
            preview_weights,
            thresholds,
            strategy_key,
            conditions=preview_conditions,
            events=events,
        )
        if preview is None:
            continue
        saved = _snapshot_row(
            row,
            history,
            baseline,
            thresholds,
            strategy_key,
            conditions=saved_conditions,
            events=events,
        )
        preview["baseline"] = {
            "strategy": (saved or {}).get("strategy"),
            "kscore": (saved or {}).get("kscore"),
            "hot": (saved or {}).get("hot"),
        }
        out.append(preview)
        if len(out) >= limit:
            break
    return out
