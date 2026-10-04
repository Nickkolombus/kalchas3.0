"""Convert apifootball.com statistics/events into core shapes."""

from __future__ import annotations

from typing import Any


_MINUTE_DRIFT = 1


def _event_identity(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(event.get("event_type") or ""),
        str(event.get("side") or "").strip().lower(),
        str(event.get("player_name") or "").strip().lower(),
        str(event.get("detail") or ""),
    )


def collapse_ssot_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one row when the live list repeats the same event a minute later.

    Provider frames often correct 64' → 65' without dropping the old time.
    Identity is type + side + player + detail; minutes within 1 collapse to
    the later clock.
    """
    kept: list[dict[str, Any]] = []
    for event in events:
        ident = _event_identity(event)
        minute = int(event.get("minute") or 0)
        twin: int | None = None
        for index, existing in enumerate(kept):
            if _event_identity(existing) != ident:
                continue
            if abs(int(existing.get("minute") or 0) - minute) > _MINUTE_DRIFT:
                continue
            twin = index
            break
        if twin is None:
            kept.append(dict(event))
            continue
        if minute >= int(kept[twin].get("minute") or 0):
            kept[twin] = dict(event)
    return kept


def _parse_minute(time_str: Any) -> int:
    text = str(time_str or "0").strip()
    if "+" in text:
        parts = text.split("+")
        try:
            return int(parts[0]) + (int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0)
        except ValueError:
            return 0
    return int(text) if text.isdigit() else 0


def api_statistics_to_list(response: object) -> object:
    """Pass through home_team/away_team dicts; leave lists for RapidAPI-era fixtures."""
    if isinstance(response, dict) and "home_team" in response and "away_team" in response:
        return response
    if isinstance(response, list):
        return response
    return {"home_team": {}, "away_team": {}}


def possession_from_stats(stats: object) -> tuple[int, int]:
    """(home, away) possession from a home_team/away_team dict; 50/50 when absent."""
    if not isinstance(stats, dict):
        return 50, 50
    home = (stats.get("home_team") or {}).get("ball_possession")
    away = (stats.get("away_team") or {}).get("ball_possession")
    if not home and not away:
        return 50, 50
    home_i = int(home or 0)
    away_i = int(away or 0)
    if home_i and not away_i:
        away_i = max(0, 100 - home_i)
    elif away_i and not home_i:
        home_i = max(0, 100 - away_i)
    return home_i, away_i


def api_events_to_ssot(
    events: object,
    home_id: int,
    away_id: int,
    *,
    home_team: str = "",
    away_team: str = "",
) -> list[dict]:
    """Map apifootball goalscorer/cards (or a full match row) into SSOT rows.

    Accepts:
    - a match row dict with ``goalscorer`` / ``cards``
    - a list of pre-shaped SSOT events (pass-through)
    """
    if isinstance(events, list):
        # Already SSOT-like or empty.
        if not events:
            return []
        if isinstance(events[0], dict) and "event_type" in events[0]:
            return collapse_ssot_events(list(events))
        return []

    if not isinstance(events, dict):
        return []

    match_data = events
    home_name = home_team or str(match_data.get("match_hometeam_name") or "")
    away_name = away_team or str(match_data.get("match_awayteam_name") or "")
    home_team_id = int(home_id or match_data.get("match_hometeam_id") or 0)
    away_team_id = int(away_id or match_data.get("match_awayteam_id") or 0)

    out: list[dict] = []
    for goal in match_data.get("goalscorer") or []:
        if not isinstance(goal, dict):
            continue
        home_scorer = goal.get("home_scorer") or ""
        away_scorer = goal.get("away_scorer") or ""
        info_side = str(goal.get("info") or "").strip().lower()
        if home_scorer:
            side = "home"
            player = home_scorer
        elif away_scorer:
            side = "away"
            player = away_scorer
        elif info_side in ("home", "away"):
            side = info_side
            player = ""
        else:
            continue
        out.append(
            {
                "event_type": "goal",
                "minute": _parse_minute(goal.get("time")),
                "side": side,
                "player_name": player,
                "detail": "Normal Goal",
                "team": home_name if side == "home" else away_name,
                "team_id": home_team_id if side == "home" else away_team_id,
            }
        )

    for card in match_data.get("cards") or []:
        if not isinstance(card, dict):
            continue
        if card.get("home_fault"):
            side = "home"
            player = card.get("home_fault")
        elif card.get("away_fault"):
            side = "away"
            player = card.get("away_fault")
        else:
            continue
        card_type = str(card.get("card") or "").lower()
        if "yellowred" in card_type or "2nd" in card_type or "second yellow" in card_type:
            detail = "Second Yellow"
        elif "red" in card_type:
            detail = "Red Card"
        else:
            detail = "Yellow Card"
        out.append(
            {
                "event_type": "card",
                "minute": _parse_minute(card.get("time")),
                "side": side,
                "player_name": player or "",
                "detail": detail,
                "team": home_name if side == "home" else away_name,
                "team_id": home_team_id if side == "home" else away_team_id,
            }
        )
    return collapse_ssot_events(out)
