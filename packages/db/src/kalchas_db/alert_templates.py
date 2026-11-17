"""Admin-edited alert message templates (migrations 0035, 0038).

Keyed by (strategy, channel, kind); strategy ``default`` covers every strategy
without its own text.

The bot reads the switched-on ones every cycle; a missing table or row means
built-in text. Admin reads and writes through the sync helpers.
"""

from __future__ import annotations

from typing import Any

import asyncpg
from sqlalchemy import bindparam, text

from kalchas_db.sync import sync_engine

CHANNELS = ("paid", "free", "discord", "x")
KINDS = ("alert", "goal", "miss")

LIST_TEMPLATES = text(
    """
    SELECT strategy, channel, kind, body, enabled, updated_at,
           fallback_count, last_fallback_at, last_fallback_reason
    FROM alert_templates
    ORDER BY strategy, channel, kind
    """
)

UPSERT_TEMPLATE = text(
    """
    INSERT INTO alert_templates (strategy, channel, kind, body, enabled, updated_at)
    VALUES (:strategy, :channel, :kind, :body, :enabled, NOW())
    ON CONFLICT (strategy, channel, kind) DO UPDATE SET
        body = EXCLUDED.body,
        enabled = EXCLUDED.enabled,
        updated_at = NOW(),
        fallback_count = 0,
        last_fallback_at = NULL,
        last_fallback_reason = NULL
    """
)

DELETE_TEMPLATE = text(
    "DELETE FROM alert_templates WHERE strategy = :strategy AND channel = :channel AND kind = :kind"
)

_PREVIEW_COLUMNS = """
    a.id, a.match_id, a.strategy_slot, a.strategy_key, a.team, a.value, a.minute,
    a.score, a.home_team, a.away_team, a.payload, a.created_at,
    o.state, o.detail
"""

RECENT_ALERTS = text(
    f"""
    SELECT {_PREVIEW_COLUMNS}
    FROM alerts a
    LEFT JOIN alert_outcomes o ON o.alert_id = a.id
    WHERE a.delivery_status = 'sent'
    ORDER BY a.id DESC
    LIMIT :limit
    """  # noqa: S608
)

RECENT_GOALS = text(
    f"""
    SELECT {_PREVIEW_COLUMNS}
    FROM alerts a
    JOIN alert_outcomes o ON o.alert_id = a.id
    WHERE o.state = 'Confirmed'
    ORDER BY o.evaluated_at DESC
    LIMIT :limit
    """  # noqa: S608
)

RECENT_MISSES = text(
    f"""
    SELECT {_PREVIEW_COLUMNS}
    FROM alerts a
    JOIN alert_outcomes o ON o.alert_id = a.id
    WHERE o.state = 'Expired'
      AND (o.detail->>'kind') IS DISTINCT FROM 'counter_scored'
    ORDER BY o.evaluated_at DESC
    LIMIT :limit
    """  # noqa: S608
)

ALERTS_BY_IDS = text(
    f"""
    SELECT {_PREVIEW_COLUMNS}
    FROM alerts a
    LEFT JOIN alert_outcomes o ON o.alert_id = a.id
    WHERE a.id IN :ids
    ORDER BY a.strategy_slot, a.id
    """  # noqa: S608
).bindparams(bindparam("ids", expanding=True))

FETCH_ACTIVE = """
SELECT strategy, channel, kind, body
FROM alert_templates
WHERE enabled
"""

RECORD_FALLBACK = """
UPDATE alert_templates
SET fallback_count = fallback_count + 1,
    last_fallback_at = NOW(),
    last_fallback_reason = $4
WHERE strategy = $1 AND channel = $2 AND kind = $3
"""


def list_templates(dsn: str) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_TEMPLATES).mappings().all()
    return [dict(row) for row in rows]


def save_template(
    dsn: str, *, strategy: str, channel: str, kind: str, body: str, enabled: bool
) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT_TEMPLATE,
            {
                "strategy": strategy,
                "channel": channel,
                "kind": kind,
                "body": body,
                "enabled": enabled,
            },
        )


def delete_template(dsn: str, *, strategy: str, channel: str, kind: str) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(DELETE_TEMPLATE, {"strategy": strategy, "channel": channel, "kind": kind})


def recent_alerts(dsn: str, *, limit: int = 400) -> list[dict[str, Any]]:
    """Recently sent alerts, newest first, for the preview picker."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(RECENT_ALERTS, {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def recent_goals(dsn: str, *, limit: int = 120) -> list[dict[str, Any]]:
    """Recently confirmed alerts (a goal came), newest first."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(RECENT_GOALS, {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def recent_misses(dsn: str, *, limit: int = 120) -> list[dict[str, Any]]:
    """Recently expired alerts (no goal came; X posts a reply for these), newest first."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(RECENT_MISSES, {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def alerts_by_ids(dsn: str, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(ALERTS_BY_IDS, {"ids": ids}).mappings().all()
    return [dict(row) for row in rows]


async def fetch_active_templates(conn: asyncpg.Connection) -> dict[tuple[str, str, str], str]:
    """Switched-on templates keyed by (strategy, channel, kind). Missing table == none.

    Before migration 0038 there is no strategy column; that read fails too, and
    the bot sends built-in text until the migration runs.
    """
    try:
        rows = await conn.fetch(FETCH_ACTIVE)
    except Exception:  # noqa: BLE001 — table/column may be missing before migrations
        return {}
    out: dict[tuple[str, str, str], str] = {}
    for row in rows:
        body = str(row["body"] or "")
        if body.strip():
            out[(str(row["strategy"]), str(row["channel"]), str(row["kind"]))] = body
    return out


async def record_fallback(
    conn: asyncpg.Connection, strategy: str, channel: str, kind: str, reason: str
) -> None:
    await conn.execute(RECORD_FALLBACK, strategy, channel, kind, reason[:500])
