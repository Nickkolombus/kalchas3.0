"""Whop -> Telegram access bridge: one row per paid membership.

`apps/api` (sync, FastAPI) owns the webhook-driven writes: inviting a new
member and revoking on cancellation. `apps/bot` (async, long-polling) owns
exactly one write: recording which Telegram account used the invite link,
which is the only way to later kick that specific account.
"""

from __future__ import annotations

from typing import Any

import asyncpg
from sqlalchemy import text

from kalchas_db.sync import sync_engine

GET_GRANT = text(
    """
    SELECT id, whop_membership_id, whop_user_id, telegram_user_id,
           telegram_invite_link, status
    FROM whop_telegram_grants
    WHERE whop_membership_id = :membership_id
    """
)

UPSERT_INVITED_GRANT = text(
    """
    INSERT INTO whop_telegram_grants (
        whop_membership_id, whop_user_id, telegram_invite_link, status
    )
    VALUES (:membership_id, :user_id, :invite_link, 'invited')
    ON CONFLICT (whop_membership_id) DO UPDATE SET
        whop_user_id = EXCLUDED.whop_user_id,
        telegram_invite_link = EXCLUDED.telegram_invite_link,
        telegram_user_id = NULL,
        status = 'invited',
        joined_at = NULL,
        revoked_at = NULL
    """
)

MARK_REVOKED = text(
    """
    UPDATE whop_telegram_grants
    SET status = 'revoked', revoked_at = NOW()
    WHERE whop_membership_id = :membership_id AND status != 'revoked'
    """
)


def get_grant(dsn: str, membership_id: str) -> dict[str, Any] | None:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = conn.execute(GET_GRANT, {"membership_id": membership_id}).mappings().first()
    return dict(row) if row else None


def upsert_invited_grant(dsn: str, *, membership_id: str, user_id: str, invite_link: str) -> None:
    """(Re)invite a membership: fresh single-use link, joined/revoked state cleared."""
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT_INVITED_GRANT,
            {"membership_id": membership_id, "user_id": user_id, "invite_link": invite_link},
        )


def mark_revoked(dsn: str, membership_id: str) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(MARK_REVOKED, {"membership_id": membership_id})


MARK_JOINED_BY_INVITE_LINK = """
UPDATE whop_telegram_grants
SET telegram_user_id = $2, status = 'joined', joined_at = NOW()
WHERE telegram_invite_link = $1 AND status = 'invited'
RETURNING id
"""


async def mark_joined_by_invite_link(
    conn: asyncpg.Connection, invite_link: str, telegram_user_id: int
) -> bool:
    """True if a pending grant was matched to this invite link and claimed."""
    row = await conn.fetchrow(MARK_JOINED_BY_INVITE_LINK, invite_link, telegram_user_id)
    return row is not None
