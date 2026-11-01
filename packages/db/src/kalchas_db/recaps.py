"""Weekly recap rows: the bot drafts and posts (asyncpg), the admin edits and approves (sync).

A recap only ever moves forward: draft -> approved -> posting -> posted, or
draft -> skipped. A failed post can be approved again to retry.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import asyncpg
from sqlalchemy import text

from kalchas_db.sync import sync_engine

DEFAULT_CHANNELS: dict[str, bool] = {
    "x": True,
    "telegram_free": True,
    "telegram_paid": True,
    "discord": True,
}

WEEK_SIGNALS = """
SELECT a.id, a.match_id, a.strategy_slot, a.strategy_key, a.team, a.value, a.minute,
       a.score, a.home_team, a.away_team, a.payload, a.created_at,
       o.state, o.detail
FROM alerts a
LEFT JOIN alert_outcomes o ON o.alert_id = a.id
WHERE a.delivery_status = 'sent'
  AND a.created_at >= $1 AND a.created_at < $2
ORDER BY a.created_at
"""

THRESHOLDS = "SELECT strategy_slot, threshold FROM strategy_thresholds"

INSERT_DRAFT = """
INSERT INTO weekly_recaps (week_start, data, texts)
VALUES ($1, $2::jsonb, $3::jsonb)
ON CONFLICT (week_start) DO NOTHING
RETURNING week_start
"""

MARK_NOTIFIED = "UPDATE weekly_recaps SET notified_at = NOW() WHERE week_start = $1"

# A draft made before its week ended (a "this week so far" preview) is
# replaced by the full week; one made after is the admin's and is left alone.
REFRESH_EARLY_DRAFT = """
UPDATE weekly_recaps
SET data = $2::jsonb, texts = $3::jsonb, created_at = NOW(), updated_at = NOW()
WHERE week_start = $1 AND status = 'draft' AND created_at < $4
RETURNING week_start
"""

CLAIM_APPROVED = """
UPDATE weekly_recaps
SET status = 'posting', updated_at = NOW()
WHERE week_start = (
    SELECT week_start FROM weekly_recaps
    WHERE status = 'approved'
    ORDER BY week_start
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING week_start, data, texts, channels, post_log
"""

FINISH_POST = """
UPDATE weekly_recaps
SET status = $2, post_log = $3::jsonb, updated_at = NOW(),
    posted_at = CASE WHEN $2 = 'posted' THEN NOW() ELSE posted_at END
WHERE week_start = $1
"""

SKIP_STALE = """
UPDATE weekly_recaps
SET status = 'skipped', updated_at = NOW()
WHERE status = 'draft' AND week_start <= $1
RETURNING week_start
"""

_COLUMNS = (
    "week_start, status, data, texts, channels, post_log, created_at, updated_at, "
    "notified_at, approved_at, posted_at"
)

GET_RECAP = text(f"SELECT {_COLUMNS} FROM weekly_recaps WHERE week_start = :week")  # noqa: S608
LATEST_RECAP = text(
    f"SELECT {_COLUMNS} FROM weekly_recaps ORDER BY week_start DESC LIMIT 1"  # noqa: S608
)
LIST_RECAPS = text(
    """
    SELECT week_start, status, posted_at
    FROM weekly_recaps
    ORDER BY week_start DESC
    LIMIT :limit
    """
)
UPDATE_TEXTS = text(
    """
    UPDATE weekly_recaps
    SET texts = CAST(:texts AS jsonb), channels = CAST(:channels AS jsonb), updated_at = NOW()
    WHERE week_start = :week AND status IN ('draft', 'failed')
    RETURNING week_start
    """
)
SAVE_DRAFT = text(
    """
    INSERT INTO weekly_recaps (week_start, data, texts)
    VALUES (:week, CAST(:data AS jsonb), CAST(:texts AS jsonb))
    ON CONFLICT (week_start) DO UPDATE
        SET data = EXCLUDED.data, texts = EXCLUDED.texts, updated_at = NOW()
        WHERE weekly_recaps.status = 'draft'
    RETURNING week_start
    """
)
SET_STATUS = text(
    """
    UPDATE weekly_recaps
    SET status = :status, updated_at = NOW(),
        approved_at = CASE WHEN :status = 'approved' THEN NOW() ELSE approved_at END
    WHERE week_start = :week AND status = ANY(:allowed)
    RETURNING week_start
    """
)


# ---------------------------------------------------------------- bot (asyncpg)


async def fetch_week_signals(
    conn: asyncpg.Connection, since: datetime, until: datetime
) -> list[dict[str, Any]]:
    rows = await conn.fetch(WEEK_SIGNALS, since, until)
    return [
        {**dict(row), "payload": _json(row["payload"]), "detail": _json(row["detail"])}
        for row in rows
    ]


async def fetch_threshold_overrides(conn: asyncpg.Connection) -> dict[int, float]:
    rows = await conn.fetch(THRESHOLDS)
    return {int(row["strategy_slot"]): float(row["threshold"]) for row in rows}


async def insert_draft(
    conn: asyncpg.Connection, week_start: date, data: dict[str, Any], texts: dict[str, Any]
) -> bool:
    """False when that week already has a recap (drafted on an earlier tick)."""
    created = await conn.fetchval(INSERT_DRAFT, week_start, json.dumps(data), json.dumps(texts))
    return created is not None


async def refresh_early_draft(
    conn: asyncpg.Connection,
    week_start: date,
    data: dict[str, Any],
    texts: dict[str, Any],
    *,
    week_ended_at: datetime,
) -> bool:
    """True when a preview draft made before `week_ended_at` was replaced."""
    replaced = await conn.fetchval(
        REFRESH_EARLY_DRAFT, week_start, json.dumps(data), json.dumps(texts), week_ended_at
    )
    return replaced is not None


async def mark_notified(conn: asyncpg.Connection, week_start: date) -> None:
    await conn.execute(MARK_NOTIFIED, week_start)


async def claim_approved(conn: asyncpg.Connection) -> dict[str, Any] | None:
    async with conn.transaction():
        row = await conn.fetchrow(CLAIM_APPROVED)
    return _decode(dict(row)) if row else None


async def finish_post(
    conn: asyncpg.Connection, week_start: date, *, status: str, post_log: dict[str, Any]
) -> None:
    await conn.execute(FINISH_POST, week_start, status, json.dumps(post_log))


async def skip_stale_drafts(conn: asyncpg.Connection, through_week: date) -> list[date]:
    rows = await conn.fetch(SKIP_STALE, through_week)
    return [row["week_start"] for row in rows]


# ---------------------------------------------------------------- admin (sync)


def get_recap_sync(dsn: str, week_start: date | None = None) -> dict[str, Any] | None:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        if week_start is None:
            row = conn.execute(LATEST_RECAP).mappings().first()
        else:
            row = conn.execute(GET_RECAP, {"week": week_start}).mappings().first()
    return _decode(dict(row)) if row else None


def list_recaps_sync(dsn: str, limit: int = 8) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_RECAPS, {"limit": int(limit)}).mappings().all()
    return [dict(row) for row in rows]


def update_texts_sync(
    dsn: str, week_start: date, texts: dict[str, Any], channels: dict[str, bool]
) -> bool:
    """False unless the recap is still editable (a draft, or a failed post)."""
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        row = conn.execute(
            UPDATE_TEXTS,
            {
                "week": week_start,
                "texts": json.dumps(texts),
                "channels": json.dumps({**DEFAULT_CHANNELS, **channels}),
            },
        ).first()
    return row is not None


def set_status_sync(dsn: str, week_start: date, status: str, *, allowed: list[str]) -> bool:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        row = conn.execute(
            SET_STATUS, {"week": week_start, "status": status, "allowed": list(allowed)}
        ).first()
    return row is not None


def fetch_week_signals_sync(dsn: str, since: datetime, until: datetime) -> list[dict[str, Any]]:
    """Same rows the bot drafts from, for "draft it now" in admin."""
    eng = sync_engine(dsn)
    sql = text(WEEK_SIGNALS.replace("$1", ":since").replace("$2", ":until"))
    with eng.connect() as conn:
        rows = conn.execute(sql, {"since": since, "until": until}).mappings().all()
    return [
        {**dict(row), "payload": _json(row["payload"]), "detail": _json(row["detail"])}
        for row in rows
    ]


def save_draft_sync(
    dsn: str, week_start: date, data: dict[str, Any], texts: dict[str, Any]
) -> bool:
    """Create the week's draft, or rebuild it while it is still a draft (edits are lost)."""
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        row = conn.execute(
            SAVE_DRAFT,
            {"week": week_start, "data": json.dumps(data), "texts": json.dumps(texts)},
        ).first()
    return row is not None


def _json(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if raw is not None else {}


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("data", "texts", "channels", "post_log"):
        if key in row:
            row[key] = _json(row[key])
    return row
