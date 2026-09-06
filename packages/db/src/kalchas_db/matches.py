"""Match + minute timeline persistence (sync, for scanner / API)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

UPSERT_MATCH = text(
    """
    INSERT INTO matches (
        match_id, home_team, away_team, home_team_id, away_team_id,
        league_name, status_short, home_score, away_score, minute, updated_at
    ) VALUES (
        :match_id, :home_team, :away_team, :home_team_id, :away_team_id,
        :league_name, :status_short, :home_score, :away_score, :minute, NOW()
    )
    ON CONFLICT (match_id) DO UPDATE SET
        home_team = EXCLUDED.home_team,
        away_team = EXCLUDED.away_team,
        home_team_id = EXCLUDED.home_team_id,
        away_team_id = EXCLUDED.away_team_id,
        league_name = EXCLUDED.league_name,
        status_short = EXCLUDED.status_short,
        home_score = EXCLUDED.home_score,
        away_score = EXCLUDED.away_score,
        minute = EXCLUDED.minute,
        updated_at = NOW()
    """
)

UPSERT_MINUTE = text(
    """
    INSERT INTO match_minutes (
        match_id, minute, home_stats, away_stats, home_goals, away_goals, recorded_at
    ) VALUES (
        :match_id, :minute, CAST(:home_stats AS jsonb), CAST(:away_stats AS jsonb),
        :home_goals, :away_goals, NOW()
    )
    ON CONFLICT (match_id, minute) DO UPDATE SET
        home_stats = EXCLUDED.home_stats,
        away_stats = EXCLUDED.away_stats,
        home_goals = EXCLUDED.home_goals,
        away_goals = EXCLUDED.away_goals,
        recorded_at = NOW()
    """
)

LIST_LIVE = text(
    """
    SELECT match_id, home_team, away_team, minute, home_score, away_score, league_name
    FROM matches
    WHERE updated_at >= NOW() - make_interval(mins => :stale_after_minutes)
    ORDER BY updated_at DESC
    """
)

LOAD_MINUTES = text(
    """
    SELECT minute, home_stats, away_stats, home_goals, away_goals
    FROM match_minutes
    WHERE match_id = :match_id
    ORDER BY minute
    """
)

DELETE_STALE_MATCHES = text(
    """
    DELETE FROM matches
    WHERE updated_at < NOW() - make_interval(mins => :max_age_minutes)
    """
)

_STAT_KEYS = (
    "attacks",
    "dangerous_attacks",
    "shots_on_target",
    "shots_off_target",
    "corners",
    "fouls",
    "possession",
)


def block_to_side_stats(block: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a MatchTimeline minute block into home_stats / away_stats JSONB."""
    home: dict[str, Any] = {}
    away: dict[str, Any] = {}
    for key in _STAT_KEYS:
        side = block.get(key)
        if not isinstance(side, dict):
            continue
        if "home" in side:
            home[key] = side["home"]
        if "away" in side:
            away[key] = side["away"]
    return home, away


def side_stats_to_block(
    home_stats: dict[str, Any],
    away_stats: dict[str, Any],
    *,
    home_goals: int,
    away_goals: int,
) -> dict[str, Any]:
    """Rebuild a MatchTimeline minute block from stored side JSONB columns."""
    keys = set(home_stats) | set(away_stats)
    block: dict[str, Any] = {
        key: {"home": home_stats.get(key, 0), "away": away_stats.get(key, 0)} for key in keys
    }
    block["goals"] = {"home": home_goals, "away": away_goals}
    return block


def upsert_match_minute_sync(
    dsn: str,
    *,
    match_id: str,
    home_team: str,
    away_team: str,
    home_team_id: int | None,
    away_team_id: int | None,
    league_name: str | None,
    status_short: str | None,
    home_score: int,
    away_score: int,
    minute: int,
    minute_block: dict[str, Any],
) -> None:
    """Upsert the match header and one minute snapshot in a single transaction."""
    home_stats, away_stats = block_to_side_stats(minute_block)
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT_MATCH,
            {
                "match_id": match_id,
                "home_team": home_team,
                "away_team": away_team,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "league_name": league_name or None,
                "status_short": status_short or None,
                "home_score": int(home_score),
                "away_score": int(away_score),
                "minute": int(minute),
            },
        )
        conn.execute(
            UPSERT_MINUTE,
            {
                "match_id": match_id,
                "minute": int(minute),
                "home_stats": json.dumps(home_stats),
                "away_stats": json.dumps(away_stats),
                "home_goals": int(home_score),
                "away_goals": int(away_score),
            },
        )


def list_live_matches_sync(dsn: str, *, stale_after_minutes: int = 15) -> list[dict[str, Any]]:
    """Matches the scanner has touched recently enough to treat as live."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(
            LIST_LIVE, {"stale_after_minutes": int(stale_after_minutes)}
        ).mappings().all()
        return [dict(r) for r in rows]


def load_match_history_sync(dsn: str, match_id: str) -> dict[str, dict[str, Any]]:
    """Raw minute_by_minute dict suitable for ``MatchTimeline.from_raw`` / MinuteStore."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LOAD_MINUTES, {"match_id": match_id}).mappings().all()
    history: dict[str, dict[str, Any]] = {}
    for row in rows:
        home_stats = row["home_stats"]
        away_stats = row["away_stats"]
        if isinstance(home_stats, str):
            home_stats = json.loads(home_stats)
        if isinstance(away_stats, str):
            away_stats = json.loads(away_stats)
        history[str(row["minute"])] = side_stats_to_block(
            dict(home_stats or {}),
            dict(away_stats or {}),
            home_goals=int(row["home_goals"]),
            away_goals=int(row["away_goals"]),
        )
    return history


def delete_stale_matches_sync(dsn: str, *, max_age_minutes: int = 360) -> int:
    """Drop finished/abandoned matches (and cascaded minutes) past the retention window."""
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        result = conn.execute(
            DELETE_STALE_MATCHES, {"max_age_minutes": int(max_age_minutes)}
        )
        return int(result.rowcount or 0)
