"""Whop -> Telegram access bridge: track each paid membership's invite link
and join state so a cancellation can kick the right Telegram account.

Revision ID: 0026_whop_telegram_grants
Revises: 0025_max_fire_minute_1h
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026_whop_telegram_grants"
down_revision: str | None = "0025_max_fire_minute_1h"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS whop_telegram_grants (
            id BIGSERIAL PRIMARY KEY,
            whop_membership_id TEXT NOT NULL UNIQUE,
            whop_user_id TEXT,
            telegram_user_id BIGINT,
            telegram_invite_link TEXT,
            status TEXT NOT NULL DEFAULT 'invited',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            joined_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS whop_telegram_grants_invite_link_idx
            ON whop_telegram_grants (telegram_invite_link);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS whop_telegram_grants;")
