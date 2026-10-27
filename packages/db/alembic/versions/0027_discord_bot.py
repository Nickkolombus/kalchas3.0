"""Discord bot: store message ids on alerts and admin-editable channel settings.

Revision ID: 0027_discord_bot
Revises: 0026_whop_telegram_grants
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027_discord_bot"
down_revision: str | None = "0026_whop_telegram_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE alerts
            ADD COLUMN IF NOT EXISTS discord_message_id BIGINT;
        """
    )
    op.execute(
        """
        ALTER TABLE alerts
            ADD COLUMN IF NOT EXISTS discord_free_message_id BIGINT;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS discord_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            free_channel_id TEXT,
            paid_channel_id TEXT,
            free_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            paid_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        INSERT INTO discord_settings (id)
        VALUES (1)
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS discord_settings;")
    op.execute(
        """
        ALTER TABLE alerts
            DROP COLUMN IF EXISTS discord_message_id,
            DROP COLUMN IF EXISTS discord_free_message_id;
        """
    )
