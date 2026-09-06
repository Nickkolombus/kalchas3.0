"""Alert outbox SQL helpers (asyncpg)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

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
