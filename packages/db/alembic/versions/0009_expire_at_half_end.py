"""Per-strategy option: expire the confirmation window at the current half's end.

Revision ID: 0009_expire_at_half_end
Revises: 0008_match_league_id
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_expire_at_half_end"
down_revision: str | None = "0008_match_league_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_rules
            ADD COLUMN IF NOT EXISTS expire_at_half_end BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_rules
            DROP COLUMN IF EXISTS expire_at_half_end;
        """
    )
