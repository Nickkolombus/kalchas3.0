"""Posted parlay slips: the admin saves them (sync), the bot posts, settles and
replies (asyncpg). See migration 0037 for the status flow."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import asyncpg
from sqlalchemy import text

from kalchas_db.sync import sync_engine

_JSON_COLUMNS = ("legs", "channels", "post_log", "outcomes", "reply_log")
_COLUMNS = (
    "id, day, slot, style, legs, caption, x_text, channels, autopost, status, post_log, "
    "outcomes, result, asked_at, reply_log, created_at, updated_at, posted_at, settled_at, "
    "replied_at"
)

# Slips the settle loop still has to watch.
OPEN = ("posted", "needs_decision")

# ---------------------------------------------------------------- bot (asyncpg)

CLAIM_APPROVED = f"""
UPDATE parlay_slips SET status = 'posting', updated_at = NOW()
WHERE id = (
    SELECT id FROM parlay_slips WHERE status = 'approved'
    ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
)
RETURNING {_COLUMNS}
"""  # noqa: S608

FINISH_POST = """
UPDATE parlay_slips
SET status = $2, post_log = $3::jsonb, updated_at = NOW(),
    posted_at = CASE WHEN $2 = 'posted' THEN NOW() ELSE posted_at END
WHERE id = $1
"""

OPEN_SLIPS = f"""
SELECT {_COLUMNS} FROM parlay_slips
WHERE status = ANY($1::text[])
ORDER BY created_at
"""  # noqa: S608

SAVE_SETTLE = """
UPDATE parlay_slips
SET outcomes = $2::jsonb, status = $3, result = $4, updated_at = NOW(),
    asked_at = CASE WHEN $5 THEN NOW() ELSE asked_at END,
    settled_at = CASE WHEN $4 IS NOT NULL AND settled_at IS NULL THEN NOW() ELSE settled_at END
WHERE id = $1 AND status = ANY($6::text[]) AND updated_at = $7
RETURNING id
"""

CLAIM_REPLY = f"""
UPDATE parlay_slips SET status = 'replying', updated_at = NOW()
WHERE id = (
    SELECT id FROM parlay_slips WHERE status = 'reply_approved'
    ORDER BY settled_at NULLS LAST, id LIMIT 1 FOR UPDATE SKIP LOCKED
)
RETURNING {_COLUMNS}
"""  # noqa: S608

FINISH_REPLY = """
UPDATE parlay_slips
SET status = $2, reply_log = $3::jsonb, updated_at = NOW(),
    replied_at = CASE WHEN $2 = 'replied' THEN NOW() ELSE replied_at END
WHERE id = $1
"""

PAGES = "SELECT match_id, payload FROM watchlist_matches WHERE match_id = ANY($1::text[])"


async def claim_approved(conn: asyncpg.Connection) -> dict[str, Any] | None:
    async with conn.transaction():
        row = await conn.fetchrow(CLAIM_APPROVED)
    return _decode(dict(row)) if row else None


async def finish_post(
    conn: asyncpg.Connection, slip_id: int, *, status: str, post_log: dict[str, Any]
) -> None:
    await conn.execute(FINISH_POST, slip_id, status, json.dumps(post_log))


async def open_slips(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    rows = await conn.fetch(OPEN_SLIPS, list(OPEN))
    return [_decode(dict(row)) for row in rows]


async def save_settle(
    conn: asyncpg.Connection,
    slip_id: int,
    *,
    outcomes: dict[str, Any],
    status: str,
    result: str | None,
    seen_at: datetime,
    asked: bool = False,
) -> bool:
    """False when the slip changed since ``seen_at`` (an admin answer, say):
    the next tick judges it again from what is stored then."""
    done = await conn.fetchval(
        SAVE_SETTLE, slip_id, json.dumps(outcomes), status, result, asked, list(OPEN), seen_at
    )
    return done is not None


async def claim_reply(conn: asyncpg.Connection) -> dict[str, Any] | None:
    async with conn.transaction():
        row = await conn.fetchrow(CLAIM_REPLY)
    return _decode(dict(row)) if row else None


async def finish_reply(
    conn: asyncpg.Connection, slip_id: int, *, status: str, reply_log: dict[str, Any]
) -> None:
    await conn.execute(FINISH_REPLY, slip_id, status, json.dumps(reply_log))


async def fetch_pages(conn: asyncpg.Connection, match_ids: list[str]) -> dict[str, dict[str, Any]]:
    rows = await conn.fetch(PAGES, match_ids)
    return {str(row["match_id"]): _json(row["payload"]) for row in rows}


async def get_slip(conn: asyncpg.Connection, slip_id: int) -> dict[str, Any] | None:
    row = await conn.fetchrow(f"SELECT {_COLUMNS} FROM parlay_slips WHERE id = $1", slip_id)  # noqa: S608
    return _decode(dict(row)) if row else None


async def decide_leg(
    conn: asyncpg.Connection, slip_id: int, match_id: str, outcome: str, *, by: str
) -> dict[str, Any] | None:
    """Record the admin's call on one leg; None if the slip no longer takes one."""
    row = await conn.fetchrow(
        DECIDE.replace(":id", "$1").replace(":entry", "$2").replace(":open", "$3"),
        slip_id,
        json.dumps({match_id: {"outcome": outcome, "by": by}}),
        list(OPEN),
    )
    return _decode(dict(row)) if row else None


async def set_reply(conn: asyncpg.Connection, slip_id: int, action: str) -> bool:
    status, allowed = _REPLY_ACTIONS[action]
    done = await conn.fetchval(
        SET_REPLY.replace(":id", "$1").replace(":status", "$2").replace(":allowed", "$3"),
        slip_id,
        status,
        list(allowed),
    )
    return done is not None


# ---------------------------------------------------------------- admin (sync)

INSERT = text(
    f"""
    INSERT INTO parlay_slips (day, slot, style, legs, caption, x_text, channels, autopost)
    VALUES (:day, :slot, :style, CAST(:legs AS jsonb), :caption, :x_text,
            CAST(:channels AS jsonb), :autopost)
    RETURNING {_COLUMNS}
    """  # noqa: S608
)
LIST = text(f"SELECT {_COLUMNS} FROM parlay_slips ORDER BY created_at DESC LIMIT :limit")  # noqa: S608
ONE = text(f"SELECT {_COLUMNS} FROM parlay_slips WHERE id = :id")  # noqa: S608

# Merge one leg's answer into ``outcomes``; a slip waiting on answers goes back
# to the settle loop, which checks whether anything is still open.
DECIDE = f"""
UPDATE parlay_slips
SET outcomes = outcomes || CAST(:entry AS jsonb),
    status = CASE WHEN status = 'needs_decision' THEN 'posted' ELSE status END,
    updated_at = NOW()
WHERE id = :id AND status = ANY(:open)
RETURNING {_COLUMNS}
"""  # noqa: S608

SET_REPLY = """
UPDATE parlay_slips SET status = :status, updated_at = NOW()
WHERE id = :id AND status = ANY(:allowed)
RETURNING id
"""

RETRY_POST = text(
    """
    UPDATE parlay_slips SET status = 'approved', updated_at = NOW()
    WHERE id = :id AND status = 'failed'
    RETURNING id
    """
)

# post: send the result reply; skip: never reply; retry: try a failed reply again.
_REPLY_ACTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "post": ("reply_approved", ("awaiting_reply", "reply_skipped")),
    "skip": ("reply_skipped", ("awaiting_reply",)),
    "retry": ("reply_approved", ("reply_failed",)),
}


def insert_slip_sync(
    dsn: str,
    *,
    day: date,
    slot: str,
    style: str,
    legs: list[dict[str, Any]],
    caption: str,
    x_text: str,
    channels: dict[str, bool],
    autopost: bool,
) -> dict[str, Any]:
    with sync_engine(dsn).begin() as conn:
        row = (
            conn.execute(
                INSERT,
                {
                    "day": day,
                    "slot": slot,
                    "style": style,
                    "legs": json.dumps(legs),
                    "caption": caption,
                    "x_text": x_text,
                    "channels": json.dumps(channels),
                    "autopost": autopost,
                },
            )
            .mappings()
            .one()
        )
    return _decode(dict(row))


def list_slips_sync(dsn: str, limit: int = 30) -> list[dict[str, Any]]:
    with sync_engine(dsn).connect() as conn:
        rows = conn.execute(LIST, {"limit": int(limit)}).mappings().all()
    return [_decode(dict(row)) for row in rows]


def get_slip_sync(dsn: str, slip_id: int) -> dict[str, Any] | None:
    with sync_engine(dsn).connect() as conn:
        row = conn.execute(ONE, {"id": slip_id}).mappings().first()
    return _decode(dict(row)) if row else None


def decide_leg_sync(
    dsn: str, slip_id: int, match_id: str, outcome: str, *, by: str
) -> dict[str, Any] | None:
    with sync_engine(dsn).begin() as conn:
        row = (
            conn.execute(
                text(DECIDE),
                {
                    "id": slip_id,
                    "entry": json.dumps({match_id: {"outcome": outcome, "by": by}}),
                    "open": list(OPEN),
                },
            )
            .mappings()
            .first()
        )
    return _decode(dict(row)) if row else None


def set_reply_sync(dsn: str, slip_id: int, action: str) -> bool:
    status, allowed = _REPLY_ACTIONS[action]
    with sync_engine(dsn).begin() as conn:
        row = conn.execute(
            text(SET_REPLY), {"id": slip_id, "status": status, "allowed": list(allowed)}
        ).first()
    return row is not None


def retry_post_sync(dsn: str, slip_id: int) -> bool:
    with sync_engine(dsn).begin() as conn:
        row = conn.execute(RETRY_POST, {"id": slip_id}).first()
    return row is not None


def _json(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if raw is not None else {}


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    for key in _JSON_COLUMNS:
        if key in row:
            row[key] = _json(row[key])
    return row
