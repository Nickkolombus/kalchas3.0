"""Daily recaps beside the weekly ones: same table, keyed by kind and start date.

Revision ID: 0033_daily_recaps
Revises: 0032_strategy_config_history
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033_daily_recaps"
down_revision: str | None = "0032_strategy_config_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE weekly_recaps
            ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'week'
                CHECK (kind IN ('week', 'day'));
        ALTER TABLE weekly_recaps DROP CONSTRAINT IF EXISTS weekly_recaps_pkey;
        ALTER TABLE weekly_recaps ADD PRIMARY KEY (kind, week_start);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM weekly_recaps WHERE kind = 'day';
        ALTER TABLE weekly_recaps DROP CONSTRAINT IF EXISTS weekly_recaps_pkey;
        ALTER TABLE weekly_recaps ADD PRIMARY KEY (week_start);
        ALTER TABLE weekly_recaps DROP COLUMN IF EXISTS kind;
        """
    )
