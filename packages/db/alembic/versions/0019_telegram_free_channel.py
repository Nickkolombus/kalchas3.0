"""Store the free-channel Telegram message id for outcome replies.

Revision ID: 0019_telegram_free_channel
Revises: 0018_telegram_outcome_replies
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019_telegram_free_channel"
down_revision: str | None = "0018_telegram_outcome_replies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE alerts
            ADD COLUMN IF NOT EXISTS telegram_free_message_id BIGINT;
        """
    )
    op.execute(
        """
        ALTER TABLE alerts
            ADD COLUMN IF NOT EXISTS telegram_free_sent_at TIMESTAMPTZ;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE alerts
            DROP COLUMN IF EXISTS telegram_free_sent_at;
        """
    )
    op.execute(
        """
        ALTER TABLE alerts
            DROP COLUMN IF EXISTS telegram_free_message_id;
        """
    )
