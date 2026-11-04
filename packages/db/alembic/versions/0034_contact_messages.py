"""Contact form messages from the site, kept even if the email or Telegram ping fails.

Revision ID: 0034_contact_messages
Revises: 0033_daily_recaps
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034_contact_messages"
down_revision: str | None = "0033_daily_recaps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_messages (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            ip_hash TEXT,
            ip_masked TEXT,
            country TEXT,
            user_agent TEXT,
            emailed BOOLEAN NOT NULL DEFAULT FALSE,
            telegram_sent BOOLEAN NOT NULL DEFAULT FALSE
        );
        CREATE INDEX IF NOT EXISTS contact_messages_created_idx
            ON contact_messages (created_at DESC);
        CREATE INDEX IF NOT EXISTS contact_messages_ip_idx
            ON contact_messages (ip_hash, created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contact_messages")
