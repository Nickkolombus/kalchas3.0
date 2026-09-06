"""Convert API-Football statistics/events into core shapes."""

from __future__ import annotations

from typing import Any


def api_statistics_to_list(response: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map `/fixtures/statistics` response into the two-element list shape."""
    if not response or len(response) < 2:
        return []

    def side_map(entry: dict[str, Any]) -> dict[str, Any]:
        stats = {s.get("type"): s.get("value") for s in (entry.get("statistics") or [])}

        def num(key: str) -> int:
            v = stats.get(key)
            if v is None or v == "None":
                return 0
            try:
                return int(float(str(v).replace("%", "")))
            except (TypeError, ValueError):
                return 0

        shots = num("Total Shots")
        sot = num("Shots on Goal")
        return {
            "shots_on_goal": sot,
            "shots": shots,
            "corner_kicks": num("Corner Kicks"),
            "attacks": num("Attacks"),
            "dangerous_attacks": num("Dangerous Attacks"),
        }

    # API returns team-keyed rows; order is usually home then away.
    return [side_map(response[0]), side_map(response[1])]


def api_events_to_ssot(events: list[dict[str, Any]], home_id: int, away_id: int) -> list[dict]:
    """Map fixture events into SSOT-like rows for ``convert_ssot_events``."""
    out: list[dict] = []
    for ev in events or []:
        etype = str(ev.get("type") or "").lower()
        if etype not in ("goal", "card"):
            continue
        team = ev.get("team") or {}
        tid = int(team.get("id") or 0)
        side = "home" if tid == home_id else "away" if tid == away_id else ""
        time_block = ev.get("time") or {}
        minute = int(time_block.get("elapsed") or 0)
        out.append(
            {
                "event_type": etype,
                "minute": minute,
                "side": side,
                "player_name": (ev.get("player") or {}).get("name") or "",
                "detail": ev.get("detail") or "",
                "team": team.get("name") or "",
            }
        )
    return out
