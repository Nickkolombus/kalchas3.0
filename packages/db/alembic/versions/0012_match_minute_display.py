"""Keep provider stoppage clock text (45+2, 90+) on the match header.

Revision ID: 0012_match_minute_display
Revises: 0011_strategy_presets
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_match_minute_display"
down_revision: str | None = "0011_strategy_presets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS minute_display TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            DROP COLUMN IF EXISTS minute_display;
        """
    )
