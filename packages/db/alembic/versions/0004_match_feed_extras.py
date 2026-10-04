"""Persist lineup and substitutions from live get_events / WebSocket rows.

Revision ID: 0004_match_feed_extras
Revises: 0003_match_events
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_match_feed_extras"
down_revision: str | None = "0003_match_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS lineup JSONB NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS substitutions JSONB NOT NULL DEFAULT '{}';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            DROP COLUMN IF EXISTS lineup,
            DROP COLUMN IF EXISTS substitutions;
        """
    )
