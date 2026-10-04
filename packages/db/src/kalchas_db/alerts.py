"""Alert outbox SQL helpers (asyncpg)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import asyncpg
from sqlalchemy import text

from kalchas_db.sync import sync_engine

INSERT_PENDING = """
INSERT INTO alerts (
    match_id, strategy_slot, strategy_key, team, value, minute, score,
    home_team, away_team, payload, delivery_status
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, 'pending'
)
RETURNING id
"""

CLAIM_BATCH = """
UPDATE alerts
SET delivery_status = 'reserved', reserved_at = NOW()
WHERE id IN (
    SELECT id FROM alerts
    WHERE delivery_status = 'pending'
    ORDER BY created_at
    LIMIT $1
    FOR UPDATE SKIP LOCKED
)
RETURNING id, match_id, strategy_slot, strategy_key, team, value, minute,
          score, home_team, away_team, payload
"""

MARK_SENT = """
UPDATE alerts
SET delivery_status = 'sent', delivered_at = NOW(), error = NULL
WHERE id = $1
"""

MARK_FAILED = """
UPDATE alerts
SET delivery_status = 'failed', error = $2
WHERE id = $1
"""

LIST_RECENT = text(
    """
    SELECT id, match_id, strategy_slot, strategy_key, team, value, minute,
           score, home_team, away_team, payload, delivery_status, created_at
    FROM alerts
    ORDER BY created_at DESC
    LIMIT :limit
    """
)

LIST_OPEN_FOR_MATCH = text(
    """
    SELECT a.id, a.match_id, a.strategy_slot, a.strategy_key, a.team, a.value,
           a.minute, a.score, a.home_team, a.away_team, a.payload, a.created_at
    FROM alerts a
    LEFT JOIN alert_outcomes o ON o.alert_id = a.id
    WHERE a.match_id = :match_id AND o.alert_id IS NULL
    ORDER BY a.created_at
    """
)

UPSERT_OUTCOME = text(
    """
    INSERT INTO alert_outcomes (alert_id, state, decision, detail, evaluated_at)
    VALUES (:alert_id, :state, :decision, CAST(:detail AS jsonb), NOW())
    ON CONFLICT (alert_id) DO NOTHING
    """
)


async def insert_pending(conn: asyncpg.Connection, alert: dict[str, Any]) -> int:
    row = await conn.fetchrow(
        INSERT_PENDING,
        alert.get("match_id"),
        int(alert["strategy_slot"]),
        alert.get("strategy") or alert.get("strategy_key"),
        alert.get("team"),
        float(alert["value"]),
        int(alert["minute"]),
        alert.get("score"),
        alert.get("home"),
        alert.get("away"),
        json.dumps(alert),
    )
    if row is None:
        raise RuntimeError("INSERT INTO alerts returned no row")
    return int(row["id"])


async def claim_pending(conn: asyncpg.Connection, limit: int = 20) -> list[asyncpg.Record]:
    async with conn.transaction():
        return await conn.fetch(CLAIM_BATCH, limit)


async def mark_sent(conn: asyncpg.Connection, alert_id: int) -> None:
    await conn.execute(MARK_SENT, alert_id)


async def mark_failed(conn: asyncpg.Connection, alert_id: int, error: str) -> None:
    await conn.execute(MARK_FAILED, alert_id, error[:2000])


def list_recent_alerts_sync(dsn: str, limit: int = 20) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_RECENT, {"limit": int(limit)}).mappings().all()
    return [dict(row) for row in rows]


def list_open_alerts_for_match_sync(dsn: str, match_id: str) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_OPEN_FOR_MATCH, {"match_id": match_id}).mappings().all()
    return [dict(row) for row in rows]


def insert_alert_outcome_sync(
    dsn: str,
    *,
    alert_id: int,
    state: str,
    decision: str,
    detail: dict[str, Any],
) -> None:
    """Write-once settle row. Later rule edits do not overwrite history."""
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT_OUTCOME,
            {
                "alert_id": int(alert_id),
                "state": state,
                "decision": decision,
                "detail": json.dumps(detail),
            },
        )


def list_alert_results_sync(
    dsn: str,
    *,
    since: datetime,
    until: datetime,
    strategies: list[str] | None = None,
    state: str | None = None,
    team: str | None = None,
    league: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter alert history. `state` is Confirmed / Expired / Monitoring."""
    from sqlalchemy import bindparam

    where = ["a.created_at >= :since", "a.created_at < :until"]
    params: dict[str, Any] = {
        "since": since,
        "until": until,
        "limit": int(limit),
        "offset": int(offset),
    }
    if strategies:
        where.append("a.strategy_key IN :strategies")
        params["strategies"] = list(strategies)
    if state == "Monitoring":
        where.append("o.state IS NULL")
    elif state:
        where.append("o.state = :state")
        params["state"] = state
    if team:
        where.append("a.team = :team")
        params["team"] = team
    if league:
        where.append("COALESCE(a.payload->>'league', '') ILIKE :league")
        params["league"] = f"%{league.strip()}%"

    clause = " AND ".join(where)
    list_sql = text(
        f"""
        SELECT a.id, a.match_id, a.strategy_slot, a.strategy_key, a.team, a.value,
               a.minute, a.score, a.home_team, a.away_team, a.created_at,
               a.payload, o.state, o.decision, o.detail, o.evaluated_at,
               (m.match_id IS NOT NULL) AS live
        FROM alerts a
        LEFT JOIN alert_outcomes o ON o.alert_id = a.id
        LEFT JOIN matches m ON m.match_id = a.match_id
        WHERE {clause}
        ORDER BY a.created_at DESC
        LIMIT :limit OFFSET :offset
        """  # noqa: S608
    )
    summary_sql = text(
        f"""
        SELECT
            count(*)::int AS total,
            count(*) FILTER (WHERE o.state = 'Confirmed')::int AS confirmed,
            count(*) FILTER (WHERE o.state = 'Expired')::int AS expired,
            count(*) FILTER (WHERE o.state IS NULL)::int AS monitoring
        FROM alerts a
        LEFT JOIN alert_outcomes o ON o.alert_id = a.id
        WHERE {clause}
        """  # noqa: S608
    )
    if strategies:
        list_sql = list_sql.bindparams(bindparam("strategies", expanding=True))
        summary_sql = summary_sql.bindparams(bindparam("strategies", expanding=True))

    summary_params = {k: v for k, v in params.items() if k not in {"limit", "offset"}}
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(list_sql, params).mappings().all()
        summary = dict(conn.execute(summary_sql, summary_params).mappings().one())
    return [dict(row) for row in rows], {
        "total": int(summary.get("total") or 0),
        "confirmed": int(summary.get("confirmed") or 0),
        "expired": int(summary.get("expired") or 0),
        "monitoring": int(summary.get("monitoring") or 0),
    }
