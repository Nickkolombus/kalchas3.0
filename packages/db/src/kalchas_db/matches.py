"""Match + minute timeline persistence (sync, for scanner / API)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import bindparam, text

from kalchas_db.sync import sync_engine

UPSERT_MATCH = text(
    """
    INSERT INTO matches (
        match_id, home_team, away_team, home_team_id, away_team_id,
        league_name, league_id, status_short, home_score, away_score, minute,
        minute_display,
        country_name, country_logo, home_team_logo, away_team_logo,
        odds, lineup, substitutions, updated_at
    ) VALUES (
        :match_id, :home_team, :away_team, :home_team_id, :away_team_id,
        :league_name, :league_id, :status_short, :home_score, :away_score, :minute,
        :minute_display,
        :country_name, :country_logo, :home_team_logo, :away_team_logo,
        CAST(:odds AS jsonb),
        CAST(:lineup AS jsonb), CAST(:substitutions AS jsonb), NOW()
    )
    ON CONFLICT (match_id) DO UPDATE SET
        home_team = EXCLUDED.home_team,
        away_team = EXCLUDED.away_team,
        home_team_id = EXCLUDED.home_team_id,
        away_team_id = EXCLUDED.away_team_id,
        league_name = EXCLUDED.league_name,
        league_id = COALESCE(EXCLUDED.league_id, matches.league_id),
        status_short = EXCLUDED.status_short,
        home_score = EXCLUDED.home_score,
        away_score = EXCLUDED.away_score,
        minute = EXCLUDED.minute,
        minute_display = EXCLUDED.minute_display,
        country_name = COALESCE(NULLIF(EXCLUDED.country_name, ''), matches.country_name),
        country_logo = COALESCE(NULLIF(EXCLUDED.country_logo, ''), matches.country_logo),
        home_team_logo = COALESCE(NULLIF(EXCLUDED.home_team_logo, ''), matches.home_team_logo),
        away_team_logo = COALESCE(NULLIF(EXCLUDED.away_team_logo, ''), matches.away_team_logo),
        odds = CASE
            WHEN EXCLUDED.odds = '{}'::jsonb THEN matches.odds
            ELSE jsonb_strip_nulls(
                jsonb_build_object(
                    'home', COALESCE(matches.odds->'home', EXCLUDED.odds->'home'),
                    'draw', COALESCE(matches.odds->'draw', EXCLUDED.odds->'draw'),
                    'away', COALESCE(matches.odds->'away', EXCLUDED.odds->'away'),
                    'kickoff', COALESCE(matches.odds->'kickoff', EXCLUDED.odds->'kickoff'),
                    'live', CASE
                        WHEN EXCLUDED.odds ? 'live' THEN EXCLUDED.odds->'live'
                        ELSE matches.odds->'live'
                    END
                )
            )
        END,
        lineup = CASE
            WHEN EXCLUDED.lineup = '{}'::jsonb THEN matches.lineup
            ELSE EXCLUDED.lineup
        END,
        substitutions = CASE
            WHEN EXCLUDED.substitutions = '{}'::jsonb THEN matches.substitutions
            ELSE EXCLUDED.substitutions
        END,
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
    SELECT
        m.match_id, m.home_team, m.away_team, m.minute, m.minute_display,
        m.home_score, m.away_score, m.league_name, m.league_id, m.status_short,
        m.home_team_id, m.away_team_id, m.country_name, m.country_logo,
        m.home_team_logo, m.away_team_logo, m.odds,
        mm.home_stats, mm.away_stats
    FROM matches m
    LEFT JOIN LATERAL (
        SELECT home_stats, away_stats
        FROM match_minutes
        WHERE match_id = m.match_id
        ORDER BY minute DESC
        LIMIT 1
    ) mm ON TRUE
    WHERE m.updated_at >= NOW() - make_interval(mins => :stale_after_minutes)
    ORDER BY m.updated_at DESC
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

UPSERT_EVENT = text(
    """
    INSERT INTO match_events (
        match_id, event_key, event_type, minute, side, team,
        player_name, detail, payload, recorded_at
    ) VALUES (
        :match_id, :event_key, :event_type, :minute, :side, :team,
        :player_name, :detail, CAST(:payload AS jsonb), NOW()
    )
    ON CONFLICT (match_id, event_key) DO UPDATE SET
        team = EXCLUDED.team,
        player_name = EXCLUDED.player_name,
        detail = EXCLUDED.detail,
        payload = EXCLUDED.payload,
        recorded_at = NOW()
    """
)

DELETE_STALE_EVENTS = text(
    """
    DELETE FROM match_events
    WHERE match_id = :match_id
      AND event_key NOT IN :keep_keys
    """
).bindparams(bindparam("keep_keys", expanding=True))

LOAD_EVENTS = text(
    """
    SELECT event_type, minute, side, team, player_name, detail, payload
    FROM match_events
    WHERE match_id = :match_id
    ORDER BY minute, event_type, event_key
    """
)

LOAD_MINUTES_MANY = text(
    """
    SELECT match_id, minute, home_stats, away_stats, home_goals, away_goals
    FROM match_minutes
    WHERE match_id IN :ids
    ORDER BY match_id, minute
    """
).bindparams(bindparam("ids", expanding=True))

LOAD_EVENTS_MANY = text(
    """
    SELECT match_id, event_type, minute, side, team, player_name, detail, payload
    FROM match_events
    WHERE match_id IN :ids
    ORDER BY match_id, minute, event_type, event_key
    """
).bindparams(bindparam("ids", expanding=True))

GET_MATCH = text(
    """
    SELECT
        match_id, home_team, away_team, home_team_id, away_team_id,
        league_name, league_id, status_short, home_score, away_score, minute,
        minute_display, country_name,
        lineup, substitutions, home_team_logo, away_team_logo, odds, updated_at
    FROM matches
    WHERE match_id = :match_id
    """
)

GET_MATCHES = text(
    """
    SELECT
        match_id, home_team, away_team, home_team_id, away_team_id,
        league_name, league_id, status_short, home_score, away_score, minute,
        minute_display, country_name,
        lineup, substitutions, home_team_logo, away_team_logo, odds, updated_at
    FROM matches
    WHERE match_id IN :ids
    """
).bindparams(bindparam("ids", expanding=True))

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
    league_id: int | None = None,
    status_short: str | None,
    home_score: int,
    away_score: int,
    minute: int,
    minute_block: dict[str, Any],
    lineup: dict[str, Any] | None = None,
    substitutions: dict[str, Any] | None = None,
    country_name: str | None = None,
    country_logo: str | None = None,
    home_team_logo: str | None = None,
    away_team_logo: str | None = None,
    odds: dict[str, Any] | None = None,
    minute_display: str | None = None,
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
                "league_id": int(league_id) if league_id else None,
                "status_short": status_short or None,
                "home_score": int(home_score),
                "away_score": int(away_score),
                "minute": int(minute),
                "minute_display": (minute_display or "").strip() or None,
                "country_name": country_name or None,
                "country_logo": country_logo or None,
                "home_team_logo": home_team_logo or None,
                "away_team_logo": away_team_logo or None,
                "odds": json.dumps(odds or {}),
                "lineup": json.dumps(lineup or {}),
                "substitutions": json.dumps(substitutions or {}),
            },
        )
        if home_stats or away_stats:
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
        rows = (
            conn.execute(LIST_LIVE, {"stale_after_minutes": int(stale_after_minutes)})
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]


def _minute_block(row: Any) -> dict[str, Any]:
    home_stats = row["home_stats"]
    away_stats = row["away_stats"]
    if isinstance(home_stats, str):
        home_stats = json.loads(home_stats)
    if isinstance(away_stats, str):
        away_stats = json.loads(away_stats)
    return side_stats_to_block(
        dict(home_stats or {}),
        dict(away_stats or {}),
        home_goals=int(row["home_goals"]),
        away_goals=int(row["away_goals"]),
    )


def _unique_ids(match_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(str(match_id) for match_id in match_ids if match_id))


def load_match_history_sync(dsn: str, match_id: str) -> dict[str, dict[str, Any]]:
    """Raw minute_by_minute dict suitable for ``MatchTimeline.from_raw`` / MinuteStore."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LOAD_MINUTES, {"match_id": match_id}).mappings().all()
    return {str(row["minute"]): _minute_block(row) for row in rows}


def load_match_histories_sync(
    dsn: str, match_ids: list[str]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Minute histories for many matches in one round trip."""
    ids = _unique_ids(match_ids)
    if not ids:
        return {}
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LOAD_MINUTES_MANY, {"ids": ids}).mappings().all()
    out: dict[str, dict[str, dict[str, Any]]] = {match_id: {} for match_id in ids}
    for row in rows:
        out[str(row["match_id"])][str(row["minute"])] = _minute_block(row)
    return out


def event_persist_key(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    minute = int(event.get("minute") or 0)
    side = str(event.get("side") or "")
    player = str(event.get("player_name") or "")
    detail = str(event.get("detail") or "")
    return f"{event_type}:{minute}:{side}:{player}:{detail}"


def upsert_match_events_sync(dsn: str, match_id: str, events: list[dict[str, Any]]) -> None:
    """Replace stored events with the current live-row list.

    Keys include minute, so a 64' → 65' clock correction would otherwise
    leave both rows. Incoming keys are upserted; any previous key for this
    match that is not in the live list is deleted.
    """
    if not events:
        return
    rows = []
    keep_keys: list[str] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        minute = int(event.get("minute") or 0)
        side = str(event.get("side") or "")
        player = str(event.get("player_name") or "")
        detail = str(event.get("detail") or "")
        key = event_persist_key(event)
        keep_keys.append(key)
        rows.append(
            {
                "match_id": match_id,
                "event_key": key,
                "event_type": event_type,
                "minute": minute,
                "side": side,
                "team": event.get("team"),
                "player_name": player or None,
                "detail": detail or None,
                "payload": json.dumps(event),
            }
        )
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(UPSERT_EVENT, rows)
        conn.execute(
            DELETE_STALE_EVENTS,
            {"match_id": match_id, "keep_keys": keep_keys},
        )


def load_match_events_sync(dsn: str, match_id: str) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LOAD_EVENTS, {"match_id": match_id}).mappings().all()
    return [dict(row) for row in rows]


def load_match_events_for_ids_sync(
    dsn: str, match_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Events for many matches in one round trip."""
    ids = _unique_ids(match_ids)
    if not ids:
        return {}
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LOAD_EVENTS_MANY, {"ids": ids}).mappings().all()
    out: dict[str, list[dict[str, Any]]] = {match_id: [] for match_id in ids}
    for row in rows:
        payload = dict(row)
        match_id = str(payload.pop("match_id"))
        out.setdefault(match_id, []).append(payload)
    return out


def get_match_sync(dsn: str, match_id: str) -> dict[str, Any] | None:
    """One match header including persisted lineup / substitutions JSON."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = conn.execute(GET_MATCH, {"match_id": match_id}).mappings().first()
    return dict(row) if row is not None else None


def get_matches_sync(dsn: str, match_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Match headers for many ids in one round trip."""
    ids = _unique_ids(match_ids)
    if not ids:
        return {}
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(GET_MATCHES, {"ids": ids}).mappings().all()
    return {str(row["match_id"]): dict(row) for row in rows}


def delete_stale_matches_sync(dsn: str, *, max_age_minutes: int = 360) -> int:
    """Drop finished/abandoned matches (and cascaded minutes) past the retention window."""
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        result = conn.execute(DELETE_STALE_MATCHES, {"max_age_minutes": int(max_age_minutes)})
        return int(result.rowcount or 0)
