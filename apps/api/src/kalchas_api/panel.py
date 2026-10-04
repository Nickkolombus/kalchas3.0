"""Match overlay payload from persisted live/WS fields — no extra provider calls."""

from __future__ import annotations

import json
from typing import Any

from kalchas_core.events import count_cards_by_side
from kalchas_core.match import MatchTimeline
from kalchas_core.runner import board_snapshot, home_away_odds, live_home_away_odds


def _json_obj(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _parse_clock(value: Any) -> int:
    text = str(value or "0").strip().replace("'", "")
    if "+" in text:
        parts = text.split("+")
        try:
            return int(parts[0]) + (int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0)
        except ValueError:
            return 0
    return int(text) if text.isdigit() else 0


def _players(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("lineup_player") or "").strip()
        if not name:
            continue
        out.append(
            {
                "player": name,
                "number": str(item.get("lineup_number") or "").strip(),
                "position": str(item.get("lineup_position") or "").strip(),
            }
        )
    return out


def _team_lineup(raw: Any) -> dict[str, Any]:
    side = raw if isinstance(raw, dict) else {}
    coaches = side.get("coach") or []
    coach_name: str | None = None
    if isinstance(coaches, list) and coaches:
        first = coaches[0]
        if isinstance(first, dict):
            coach_name = str(first.get("lineup_player") or "").strip() or None
    return {
        "starting": _players(side.get("starting_lineups")),
        "substitutes": _players(side.get("substitutes")),
        "coach": coach_name,
    }


def flatten_substitutions(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Provider stores ``out | in`` on each side list."""
    out: list[dict[str, Any]] = []
    for side in ("home", "away"):
        items = raw.get(side) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("substitution") or "")
            parts = [part.strip() for part in text.split("|", 1)]
            out.append(
                {
                    "minute": _parse_clock(item.get("time")),
                    "side": side,
                    "player_out": parts[0] if parts else "",
                    "player_in": parts[1] if len(parts) > 1 else "",
                }
            )
    out.sort(key=lambda event: (int(event["minute"]), str(event["side"])))
    return out


def _side_values(status: dict[str, Any], key: str) -> dict[str, float]:
    teams = (status.get(key) or {}).get("teams") or {}
    return {
        "home": float((teams.get("home") or {}).get("value") or 0),
        "away": float((teams.get("away") or {}).get("value") or 0),
    }


def _snapshot_stat(timeline: MatchTimeline, name: str) -> dict[str, float]:
    snap = timeline.current
    if snap is None:
        return {"home": 0, "away": 0}
    return {
        "home": float(getattr(snap.home, name)),
        "away": float(getattr(snap.away, name)),
    }


def timeline_series(
    history: dict[str, dict[str, Any]],
    *,
    league_id: int | str | None = None,
    league_name: str | None = None,
    country_name: str | None = None,
    home_odds: float | None = None,
    away_odds: float | None = None,
    live_home_odds: float | None = None,
    live_away_odds: float | None = None,
    yellow_cards: Any = (0, 0),
    red_cards: Any = (0, 0),
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    series: list[dict[str, Any]] = []
    latest_board: dict[str, Any] | None = None
    from kalchas_api.runtime import load_board_tuning

    tuning = load_board_tuning()
    for minute in sorted(int(key) for key in history):
        timeline = MatchTimeline.from_raw(history, minute)
        goals = (history.get(str(minute)) or {}).get("goals") or {}
        board = board_snapshot(
            timeline,
            home_goals=int(goals.get("home") or 0),
            away_goals=int(goals.get("away") or 0),
            weights=tuning.weights,
            thresholds=tuning.thresholds,
            league_id=league_id,
            league_name=league_name,
            country_name=country_name,
            home_odds=home_odds,
            away_odds=away_odds,
            live_home_odds=live_home_odds,
            live_away_odds=live_away_odds,
            yellow_cards=yellow_cards,
            red_cards=red_cards,
            conditions=tuning.conditions,
        )
        latest_board = board
        status = board.get("strategy_status") or {}
        kblock = status.get("kscore") or {}
        series.append(
            {
                "minute": minute,
                "dangerous_attacks": _snapshot_stat(timeline, "dangerous_attacks"),
                "attacks": _snapshot_stat(timeline, "attacks"),
                "shots_on_target": _snapshot_stat(timeline, "shots_on_target"),
                "possession": _snapshot_stat(timeline, "possession"),
                "rule_of_three": _side_values(status, "rule_of_three"),
                "omega": _side_values(status, "omega"),
                "kscore": float(kblock.get("match") or 0),
            }
        )
    return series, latest_board


def build_match_panel(dsn: str, match_id: str) -> dict[str, Any] | None:
    """Assemble the overlay from Postgres. Returns None when the match is unknown."""
    from kalchas_db.matches import (
        get_match_sync,
        load_match_events_sync,
        load_match_history_sync,
    )

    row = get_match_sync(dsn, match_id)
    if row is None:
        return None
    history = load_match_history_sync(dsn, match_id)
    events_raw = load_match_events_sync(dsn, match_id)
    yellow, red = count_cards_by_side(events_raw)
    odds_data = _json_obj(row.get("odds"))
    home_odds, away_odds = home_away_odds(odds_data)
    live_home, live_away = live_home_away_odds(odds_data)
    league_raw = row.get("league_id")
    league_id: int | None = None
    if league_raw not in (None, ""):
        try:
            parsed = int(league_raw)
        except (TypeError, ValueError):
            parsed = 0
        league_id = parsed if parsed else None
    series, board = timeline_series(
        history,
        league_id=league_id,
        league_name=str(row["league_name"]) if row.get("league_name") else None,
        country_name=str(row["country_name"]) if row.get("country_name") else None,
        home_odds=home_odds,
        away_odds=away_odds,
        live_home_odds=live_home,
        live_away_odds=live_away,
        yellow_cards=yellow,
        red_cards=red,
    )
    events = [
        {
            "event_type": str(event["event_type"]),
            "minute": int(event["minute"]),
            "side": str(event["side"]),
            "team": str(event["team"]) if event.get("team") else None,
            "player_name": str(event["player_name"]) if event.get("player_name") else None,
            "detail": str(event["detail"]) if event.get("detail") else None,
        }
        for event in events_raw
    ]
    lineup_raw = _json_obj(row.get("lineup"))
    subs_raw = _json_obj(row.get("substitutions"))
    home_id = int(row["home_team_id"]) if row.get("home_team_id") is not None else None
    away_id = int(row["away_team_id"]) if row.get("away_team_id") is not None else None
    return {
        "match_id": str(row["match_id"]),
        "home_team": str(row["home_team"]),
        "away_team": str(row["away_team"]),
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team_logo": str(row["home_team_logo"]) if row.get("home_team_logo") else None,
        "away_team_logo": str(row["away_team_logo"]) if row.get("away_team_logo") else None,
        "minute": int(row["minute"]),
        "minute_display": str(row["minute_display"]) if row.get("minute_display") else None,
        "score": f"{int(row['home_score'])}-{int(row['away_score'])}",
        "league": str(row["league_name"]) if row.get("league_name") else None,
        "status_short": str(row["status_short"]) if row.get("status_short") else None,
        "stat_lines": (board or {}).get("stat_lines") or {},
        "strategy_status": (board or {}).get("strategy_status") or {},
        "events": events,
        "substitutions": flatten_substitutions(subs_raw),
        "timeline": series,
        "lineup": {
            "home": _team_lineup(lineup_raw.get("home")),
            "away": _team_lineup(lineup_raw.get("away")),
        },
    }
