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
SET delivery_status = 'sent',
    delivered_at = NOW(),
    error = NULL,
    telegram_message_id = COALESCE($2, telegram_message_id)
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

CLAIM_OUTCOME_BATCH = """
UPDATE alert_outcomes o
SET telegram_delivery_status = 'reserved'
FROM alerts a
WHERE o.alert_id = a.id
  AND o.alert_id IN (
    SELECT o2.alert_id
    FROM alert_outcomes o2
    INNER JOIN alerts a2 ON a2.id = o2.alert_id
    WHERE o2.telegram_delivery_status = 'pending'
      AND a2.telegram_message_id IS NOT NULL
    ORDER BY o2.evaluated_at
    LIMIT $1
    FOR UPDATE OF o2 SKIP LOCKED
  )
RETURNING o.alert_id, o.state, o.decision, o.detail, o.evaluated_at,
          a.strategy_key, a.team, a.home_team, a.away_team, a.value, a.payload,
          a.telegram_message_id, a.telegram_free_message_id, a.minute, a.score,
          a.discord_message_id, a.discord_free_message_id
"""

SKIP_UNREPLIABLE_OUTCOMES = """
UPDATE alert_outcomes o
SET telegram_delivery_status = 'skipped'
FROM alerts a
WHERE o.alert_id = a.id
  AND o.telegram_delivery_status = 'pending'
  AND (
    a.delivery_status = 'failed'
    OR (a.delivery_status = 'sent' AND a.telegram_message_id IS NULL)
  )
"""

MARK_OUTCOME_SENT = """
UPDATE alert_outcomes
SET telegram_delivery_status = 'sent'
WHERE alert_id = $1
"""

MARK_OUTCOME_FAILED = """
UPDATE alert_outcomes
SET telegram_delivery_status = 'failed'
WHERE alert_id = $1
"""

MARK_FREE_SENT = """
UPDATE alerts
SET telegram_free_message_id = $2,
    telegram_free_sent_at = NOW()
WHERE id = $1
"""

ATTACH_FREE_MESSAGE = """
UPDATE alerts
SET telegram_free_message_id = $2
WHERE id = $1
"""

MARK_DISCORD_SENT = """
UPDATE alerts
SET discord_message_id = $2
WHERE id = $1
"""

MARK_DISCORD_FREE_SENT = """
UPDATE alerts
SET discord_free_message_id = $2
WHERE id = $1
"""

SENT_SAME_MINUTE = """
SELECT id, match_id, strategy_slot, strategy_key, team, value, minute,
       score, home_team, away_team, payload,
       telegram_message_id, telegram_free_message_id,
       discord_message_id, discord_free_message_id
FROM alerts
WHERE match_id = $1
  AND minute = $2
  AND delivery_status = 'sent'
  AND telegram_message_id IS NOT NULL
ORDER BY id
"""

MESSAGE_ALERT_STATES = """
SELECT a.id, o.state
FROM alerts a
LEFT JOIN alert_outcomes o ON o.alert_id = a.id
WHERE a.telegram_message_id = $1
"""

RELEASE_OUTCOME = """
UPDATE alert_outcomes
SET telegram_delivery_status = 'pending'
WHERE alert_id = $1
"""

LAST_FREE_SENT_AT = """
SELECT MAX(telegram_free_sent_at) AS last_at
FROM alerts
WHERE telegram_free_sent_at IS NOT NULL
"""

FREE_GATE_LOCK_KEY = 87420001

LOCK_FREE_GATE = "SELECT pg_try_advisory_lock($1)"
UNLOCK_FREE_GATE = "SELECT pg_advisory_unlock($1)"


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


async def mark_sent(
    conn: asyncpg.Connection,
    alert_id: int,
    telegram_message_id: int | None = None,
) -> None:
    await conn.execute(MARK_SENT, alert_id, telegram_message_id)


async def claim_pending_outcomes(conn: asyncpg.Connection, limit: int = 20) -> list[asyncpg.Record]:
    async with conn.transaction():
        await conn.execute(SKIP_UNREPLIABLE_OUTCOMES)
        return await conn.fetch(CLAIM_OUTCOME_BATCH, limit)


async def mark_outcome_sent(conn: asyncpg.Connection, alert_id: int) -> None:
    await conn.execute(MARK_OUTCOME_SENT, alert_id)


async def mark_outcome_failed(conn: asyncpg.Connection, alert_id: int) -> None:
    await conn.execute(MARK_OUTCOME_FAILED, alert_id)


async def mark_failed(conn: asyncpg.Connection, alert_id: int, error: str) -> None:
    await conn.execute(MARK_FAILED, alert_id, error[:2000])


async def mark_free_sent(
    conn: asyncpg.Connection,
    alert_id: int,
    telegram_free_message_id: int | None,
) -> None:
    await conn.execute(MARK_FREE_SENT, alert_id, telegram_free_message_id)


async def attach_free_message(
    conn: asyncpg.Connection,
    alert_id: int,
    telegram_free_message_id: int,
) -> None:
    """Share an existing free post. Does not move the hourly free clock."""
    await conn.execute(ATTACH_FREE_MESSAGE, alert_id, telegram_free_message_id)


async def mark_discord_sent(
    conn: asyncpg.Connection,
    alert_id: int,
    discord_message_id: int,
) -> None:
    await conn.execute(MARK_DISCORD_SENT, alert_id, discord_message_id)


async def mark_discord_free_sent(
    conn: asyncpg.Connection,
    alert_id: int,
    discord_free_message_id: int,
) -> None:
    """Also used to share an existing Discord free post with a sibling alert."""
    await conn.execute(MARK_DISCORD_FREE_SENT, alert_id, discord_free_message_id)


async def sent_same_minute(
    conn: asyncpg.Connection,
    match_id: str,
    minute: int,
) -> list[asyncpg.Record]:
    return await conn.fetch(SENT_SAME_MINUTE, str(match_id), int(minute))


async def message_alert_states(
    conn: asyncpg.Connection,
    telegram_message_id: int,
) -> list[asyncpg.Record]:
    return await conn.fetch(MESSAGE_ALERT_STATES, int(telegram_message_id))


async def release_outcome(conn: asyncpg.Connection, alert_id: int) -> None:
    await conn.execute(RELEASE_OUTCOME, alert_id)


async def last_free_sent_at(conn: asyncpg.Connection) -> datetime | None:
    row = await conn.fetchrow(LAST_FREE_SENT_AT)
    if row is None:
        return None
    value = row["last_at"]
    return value if isinstance(value, datetime) else None


async def lock_free_gate(conn: asyncpg.Connection) -> bool:
    locked = await conn.fetchval(LOCK_FREE_GATE, FREE_GATE_LOCK_KEY)
    return bool(locked)


async def unlock_free_gate(conn: asyncpg.Connection) -> None:
    await conn.fetchval(UNLOCK_FREE_GATE, FREE_GATE_LOCK_KEY)


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
