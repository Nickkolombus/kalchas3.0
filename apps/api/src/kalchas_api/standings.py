"""League table ranks for versus / H2H. Cached per league, not per match."""

from __future__ import annotations

from typing import Any

STANDINGS_TTL_HOURS = 6


def standings_cache_key(league_id: int) -> str:
    return f"standings_{int(league_id)}"


def attach_league_ranks(
    payload: dict[str, Any],
    *,
    dsn: str,
    league_id: int | None,
    home_id: int,
    away_id: int,
) -> dict[str, Any]:
    """Add home_rank / away_rank when the league table has those teams."""
    payload["home_rank"] = None
    payload["away_rank"] = None
    if league_id is None or int(league_id) <= 0 or home_id <= 0 or away_id <= 0:
        return payload
    positions = _positions_for_league(dsn, int(league_id))
    if not positions:
        return payload
    payload["home_rank"] = positions.get(int(home_id))
    payload["away_rank"] = positions.get(int(away_id))
    return payload


def _positions_for_league(dsn: str, league_id: int) -> dict[int, int]:
    from kalchas_db.panel_cache import load_panel_cache, save_panel_cache

    key = standings_cache_key(league_id)
    try:
        cached = load_panel_cache(dsn, key, ttl_hours=STANDINGS_TTL_HOURS)
    except Exception:  # noqa: BLE001 — missing table still tries a live fetch
        cached = None
    if isinstance(cached, dict):
        return _positions_from_payload(cached)
    try:
        from kalchas_football import FootballAPIClient

        client = FootballAPIClient()
        try:
            positions = client.get_standings(league_id)
        finally:
            client.close()
    except Exception:  # noqa: BLE001 — ranks are optional; H2H still returns
        return {}
    try:
        save_panel_cache(
            dsn,
            key,
            {"positions": {str(team_id): pos for team_id, pos in positions.items()}},
        )
    except Exception:  # noqa: BLE001,S110 — cache write must not hide ranks
        pass
    return positions


def _positions_from_payload(raw: dict[str, Any]) -> dict[int, int]:
    block = raw.get("positions") if isinstance(raw.get("positions"), dict) else raw
    if not isinstance(block, dict):
        return {}
    out: dict[int, int] = {}
    for key, value in block.items():
        try:
            team_id = int(key)
            position = int(value)
        except (TypeError, ValueError):
            continue
        if team_id > 0 and position > 0:
            out[team_id] = position
    return out
