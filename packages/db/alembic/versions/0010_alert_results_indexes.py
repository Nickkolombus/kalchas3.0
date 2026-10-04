"""Indexes for admin Results filters on alerts / alert_outcomes.

Revision ID: 0010_alert_results_indexes
Revises: 0009_expire_at_half_end
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_alert_results_indexes"
down_revision: str | None = "0009_expire_at_half_end"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_alerts_strategy_created
            ON alerts (strategy_key, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_alert_outcomes_state ON alert_outcomes (state);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_alert_outcomes_state;
        DROP INDEX IF EXISTS idx_alerts_strategy_created;
        DROP INDEX IF EXISTS idx_alerts_created_at;
        """
    )
