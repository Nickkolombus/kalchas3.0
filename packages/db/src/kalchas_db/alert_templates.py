"""Admin-edited alert message templates (migration 0035).

The bot reads the switched-on ones every cycle; a missing table or row means
built-in text. Admin reads and writes through the sync helpers.
"""

from __future__ import annotations

from typing import Any

import asyncpg
from sqlalchemy import bindparam, text

from kalchas_db.sync import sync_engine

CHANNELS = ("paid", "free", "discord")
KINDS = ("alert", "goal")

LIST_TEMPLATES = text(
    """
    SELECT channel, kind, body, enabled, updated_at,
           fallback_count, last_fallback_at, last_fallback_reason
    FROM alert_templates
    ORDER BY channel, kind
    """
)

UPSERT_TEMPLATE = text(
    """
    INSERT INTO alert_templates (channel, kind, body, enabled, updated_at)
    VALUES (:channel, :kind, :body, :enabled, NOW())
    ON CONFLICT (channel, kind) DO UPDATE SET
        body = EXCLUDED.body,
        enabled = EXCLUDED.enabled,
        updated_at = NOW(),
        fallback_count = 0,
        last_fallback_at = NULL,
        last_fallback_reason = NULL
    """
)

DELETE_TEMPLATE = text("DELETE FROM alert_templates WHERE channel = :channel AND kind = :kind")

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
SELECT channel, kind, body
FROM alert_templates
WHERE enabled
"""

RECORD_FALLBACK = """
UPDATE alert_templates
SET fallback_count = fallback_count + 1,
    last_fallback_at = NOW(),
    last_fallback_reason = $3
WHERE channel = $1 AND kind = $2
"""


def list_templates(dsn: str) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_TEMPLATES).mappings().all()
    return [dict(row) for row in rows]


def save_template(dsn: str, *, channel: str, kind: str, body: str, enabled: bool) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT_TEMPLATE,
            {"channel": channel, "kind": kind, "body": body, "enabled": enabled},
        )


def delete_template(dsn: str, *, channel: str, kind: str) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(DELETE_TEMPLATE, {"channel": channel, "kind": kind})


def recent_alerts(dsn: str, *, limit: int = 60) -> list[dict[str, Any]]:
    """Recently sent alerts, newest first, for the preview picker."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(RECENT_ALERTS, {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def recent_goals(dsn: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Recently confirmed alerts (a goal came), newest first."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(RECENT_GOALS, {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def alerts_by_ids(dsn: str, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(ALERTS_BY_IDS, {"ids": ids}).mappings().all()
    return [dict(row) for row in rows]


async def fetch_active_templates(conn: asyncpg.Connection) -> dict[tuple[str, str], str]:
    """Switched-on templates keyed by (channel, kind). Missing table == none."""
    try:
        rows = await conn.fetch(FETCH_ACTIVE)
    except Exception:  # noqa: BLE001 — table may be missing before migration 0035
        return {}
    out: dict[tuple[str, str], str] = {}
    for row in rows:
        body = str(row["body"] or "")
        if body.strip():
            out[(str(row["channel"]), str(row["kind"]))] = body
    return out


async def record_fallback(conn: asyncpg.Connection, channel: str, kind: str, reason: str) -> None:
    await conn.execute(RECORD_FALLBACK, channel, kind, reason[:500])
