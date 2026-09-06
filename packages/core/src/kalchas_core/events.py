"""Goal/card event normalisation and Time-Since-Last-Goal (TSLG).

Ported from ``scanner/match_enricher.py``. Callers supply already-fetched
events; this module never talks to the network or database.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def convert_ssot_events(
    ssot_events: Iterable[dict[str, Any]],
    home_team: str | None = None,
    away_team: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert SSOT ``match_events`` rows into ``(goal_events, card_events)``."""
    goal_events: list[dict[str, Any]] = []
    card_events: list[dict[str, Any]] = []

    for event in ssot_events or []:
        etype = str(event.get("event_type", "")).lower()
        side = str(event.get("side") or "").strip().lower()

        raw_team = str(event.get("team") or event.get("team_name") or "").strip()
        if raw_team and raw_team.lower() not in ("home", "away"):
            team_label = raw_team
        elif side == "home" and home_team:
            team_label = str(home_team)
        elif side == "away" and away_team:
            team_label = str(away_team)
        else:
            team_label = str(event.get("side") or "")

        if etype == "goal":
            goal_events.append(
                {
                    "time": event.get("minute", 0),
                    "minute": event.get("minute", 0),
                    "side": side,
                    "team": team_label,
                    "team_name": team_label,
                    "player": event.get("player_name", ""),
                    "assist": "",
                    "type": "Goal",
                    "detail": event.get("detail", ""),
                    "comments": "",
                }
            )
        elif etype == "card":
            card_events.append(
                {
                    "time": event.get("minute", 0),
                    "minute": event.get("minute", 0),
                    "side": side,
                    "team": team_label,
                    "team_name": team_label,
                    "player": event.get("player_name", ""),
                    "type": "Card",
                    "detail": event.get("detail", ""),
                    "comments": "",
                }
            )

    return goal_events, card_events


def tally_red_cards(
    card_events: Iterable[dict[str, Any]],
    home_team_name: str,
    away_team_name: str,
) -> dict[str, int]:
    """Count red cards per side by exact team-name equality."""
    home_reds = 0
    away_reds = 0
    for card in card_events or []:
        detail = str(card.get("detail", "")).lower()
        if "red" not in detail:
            continue
        team_name = card.get("team", "")
        if team_name == home_team_name:
            home_reds += 1
        elif team_name == away_team_name:
            away_reds += 1
    return {"home": home_reds, "away": away_reds}


def clean_goal_events(
    goal_events: Iterable[dict[str, Any]],
    home_team: str | None = None,
    away_team: str | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    dedup_window_minutes: int = 4,
) -> list[dict[str, Any]]:
    """Dedup same-side goals within a window and cap by current score."""
    home_l = str(home_team or "").strip().lower()
    away_l = str(away_team or "").strip().lower()
    side_seen: dict[str, list[int]] = {"home": [], "away": []}
    cleaned: list[dict[str, Any]] = []

    def _event_minute(event: dict[str, Any]) -> int:
        for key in ("minute", "time"):
            val = event.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
        return 0

    def _infer_side(event: dict[str, Any]) -> str | None:
        side = str(event.get("side") or "").strip().lower()
        if side in ("home", "away"):
            return side
        team_name = str(event.get("team") or event.get("team_name") or "").strip().lower()
        if not team_name or not (home_l or away_l):
            return None
        if home_l and (team_name == home_l or team_name in home_l or home_l in team_name):
            return "home"
        if away_l and (team_name == away_l or team_name in away_l or away_l in team_name):
            return "away"
        return None

    sorted_events = sorted(goal_events or [], key=_event_minute)
    for ev in sorted_events:
        side = _infer_side(ev)
        if side is None:
            continue
        minute = _event_minute(ev)
        if any(abs(minute - m) <= dedup_window_minutes for m in side_seen[side]):
            continue
        side_seen[side].append(minute)
        normalised = dict(ev)
        normalised["side"] = side
        cleaned.append(normalised)

    if home_score is not None:
        home_limit = max(0, int(home_score))
        home_events = [e for e in cleaned if e["side"] == "home"][:home_limit]
    else:
        home_events = [e for e in cleaned if e["side"] == "home"]

    if away_score is not None:
        away_limit = max(0, int(away_score))
        away_events = [e for e in cleaned if e["side"] == "away"][:away_limit]
    else:
        away_events = [e for e in cleaned if e["side"] == "away"]

    return sorted(home_events + away_events, key=_event_minute)


def compute_tslg_status(
    match_data: dict[str, Any],
    minute: int | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
    cooldown_minutes: int = 10,
) -> dict[str, Any]:
    """Time since last goal for each side.

    Evidence chain: cleaned ``goal_events`` → ``score_history`` →
    ``minute_by_minute``. Scoreless sides stay ``None`` (display ``—``).
    """
    if minute is None:
        minute = match_data.get("current_minute", 0)
    try:
        minute = int(minute or 0)
    except (TypeError, ValueError):
        minute = 0

    home_team = (
        home_team or match_data.get("home_team") or match_data.get("match_hometeam_name") or ""
    )
    away_team = (
        away_team or match_data.get("away_team") or match_data.get("match_awayteam_name") or ""
    )
    home_l = str(home_team).strip().lower()
    away_l = str(away_team).strip().lower()

    home_score = match_data.get("home_score")
    away_score = match_data.get("away_score")
    raw_score = match_data.get("score")
    if isinstance(raw_score, dict):
        if home_score is None:
            home_score = raw_score.get("home")
        if away_score is None:
            away_score = raw_score.get("away")
    elif isinstance(raw_score, str):
        try:
            h_part, a_part = raw_score.split("-")
            if home_score is None:
                home_score = int(h_part)
            if away_score is None:
                away_score = int(a_part)
        except (ValueError, IndexError):
            pass
    if home_score is not None:
        try:
            home_score = int(home_score)
        except (TypeError, ValueError):
            home_score = None
    if away_score is not None:
        try:
            away_score = int(away_score)
        except (TypeError, ValueError):
            away_score = None

    raw_goal_events = match_data.get("goal_events") or []
    goal_events = clean_goal_events(
        raw_goal_events,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
    )
    last_home_goal: int | None = None
    last_away_goal: int | None = None

    def _event_minute(event: dict[str, Any]) -> int | None:
        for key in ("time", "minute", "elapsed"):
            val = event.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
        t = event.get("time")
        if isinstance(t, dict):
            for key in ("elapsed", "extra"):
                val = t.get(key)
                if val is not None:
                    try:
                        return int(val)
                    except (TypeError, ValueError):
                        pass
        return None

    def _event_side(event: dict[str, Any]) -> str | None:
        team_name = str(event.get("team") or event.get("team_name") or "").strip().lower()
        if team_name and (home_l or away_l):
            if home_l and (team_name == home_l or team_name in home_l or home_l in team_name):
                return "home"
            if away_l and (team_name == away_l or team_name in away_l or away_l in team_name):
                return "away"
        side = str(event.get("side") or "").strip().lower()
        if side in ("home", "away"):
            return side
        return None

    if goal_events:
        sorted_events = sorted(goal_events, key=lambda ev: _event_minute(ev) or -1)
        for event in reversed(sorted_events):
            event_minute = _event_minute(event)
            if event_minute is None or event_minute > minute:
                continue
            side = _event_side(event)
            if side == "home" and last_home_goal is None:
                last_home_goal = event_minute
            elif side == "away" and last_away_goal is None:
                last_away_goal = event_minute
            if last_home_goal is not None and last_away_goal is not None:
                break

    if last_home_goal is None or last_away_goal is None:
        score_history = match_data.get("score_history")
        if score_history:
            rows: list[tuple[int, int, int]] = []
            for entry in score_history:
                if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                    try:
                        rows.append((int(entry[0]), int(entry[1]), int(entry[2])))
                    except (TypeError, ValueError):
                        pass
                elif isinstance(entry, dict):
                    score_str = entry.get("score")
                    if isinstance(score_str, str):
                        try:
                            h, a = map(int, score_str.split("-"))
                            rows.append((int(entry.get("minute", 0)), h, a))
                        except (TypeError, ValueError):
                            pass
            rows.sort(key=lambda r: r[0])
            if rows:
                prev_home, prev_away = rows[0][1], rows[0][2]
                for hist_min, h, a in rows[1:]:
                    if h > prev_home and (last_home_goal is None or hist_min > last_home_goal):
                        last_home_goal = hist_min
                    if a > prev_away and (last_away_goal is None or hist_min > last_away_goal):
                        last_away_goal = hist_min
                    prev_home, prev_away = h, a

    if last_home_goal is None or last_away_goal is None:
        mbm = match_data.get("minute_by_minute") or {}
        rows = []
        for key, data in mbm.items() if isinstance(mbm, dict) else []:
            try:
                m = int(key)
            except (TypeError, ValueError):
                continue
            if m > minute:
                continue
            if not isinstance(data, dict):
                continue
            s = data.get("score")
            if isinstance(s, dict):
                try:
                    h = int(s.get("home", 0) or 0)
                    a = int(s.get("away", 0) or 0)
                except (TypeError, ValueError):
                    continue
            elif isinstance(s, str):
                try:
                    h, a = map(int, s.split("-"))
                except (TypeError, ValueError):
                    continue
            else:
                continue
            rows.append((m, h, a))
        rows.sort(key=lambda r: r[0])
        if rows:
            prev_h, prev_a = rows[0][1], rows[0][2]
            for m, h, a in rows[1:]:
                if h > prev_h and (last_home_goal is None or m > last_home_goal):
                    last_home_goal = m
                if a > prev_a and (last_away_goal is None or m > last_away_goal):
                    last_away_goal = m
                prev_h, prev_a = h, a

    home_minutes = minute - last_home_goal if last_home_goal is not None else None
    away_minutes = minute - last_away_goal if last_away_goal is not None else None

    cooldown_active = any(
        value is not None and value < cooldown_minutes for value in (home_minutes, away_minutes)
    )

    last_goal_info: dict[str, Any] = {}
    if last_home_goal is not None or last_away_goal is not None:
        if last_home_goal is not None and (
            last_away_goal is None or last_home_goal >= last_away_goal
        ):
            last_goal_info = {"side": "home", "minute": last_home_goal, "team": home_team}
        else:
            last_goal_info = {"side": "away", "minute": last_away_goal, "team": away_team}

    def _fmt(value: int | None) -> str:
        if value is None:
            return "—"
        if value < 0:
            value = 0
        return f"{value}'"

    return {
        "home_minutes": home_minutes,
        "away_minutes": away_minutes,
        "cooldown_minutes": cooldown_minutes,
        "cooldown_active": cooldown_active,
        "display": f"{_fmt(home_minutes)} - {_fmt(away_minutes)}",
        "last_goal": last_goal_info,
    }
