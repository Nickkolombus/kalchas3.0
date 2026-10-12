"""Store Telegram message ids and outcome-reply delivery status.

Revision ID: 0018_telegram_outcome_replies
Revises: 0017_tips_window
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_telegram_outcome_replies"
down_revision: str | None = "0017_tips_window"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE alerts
            ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT;
        """
    )
    op.execute(
        """
        ALTER TABLE alert_outcomes
            ADD COLUMN IF NOT EXISTS telegram_delivery_status TEXT;
        """
    )
    op.execute(
        """
        UPDATE alert_outcomes
        SET telegram_delivery_status = 'skipped'
        WHERE telegram_delivery_status IS NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE alert_outcomes
            ALTER COLUMN telegram_delivery_status SET DEFAULT 'pending';
        """
    )
    op.execute(
        """
        ALTER TABLE alert_outcomes
            ALTER COLUMN telegram_delivery_status SET NOT NULL;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE alert_outcomes
                ADD CONSTRAINT alert_outcomes_telegram_delivery_status_chk
                CHECK (telegram_delivery_status IN (
                    'pending', 'reserved', 'sent', 'skipped', 'failed'
                ));
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alert_outcomes_telegram_pending
            ON alert_outcomes (evaluated_at)
            WHERE telegram_delivery_status = 'pending';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alert_outcomes_telegram_pending;")
    op.execute(
        """
        ALTER TABLE alert_outcomes
            DROP CONSTRAINT IF EXISTS alert_outcomes_telegram_delivery_status_chk;
        """
    )
    op.execute(
        """
        ALTER TABLE alert_outcomes
            DROP COLUMN IF EXISTS telegram_delivery_status;
        """
    )
    op.execute(
        """
        ALTER TABLE alerts
            DROP COLUMN IF EXISTS telegram_message_id;
        """
    )
