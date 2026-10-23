"""Per-strategy late cut-off: don't fire after a given match minute.

Adds ``strategy_rules.max_fire_minute``. NULL (the default for every row) is
off, so nothing changes until an admin sets a minute. The scanner's cooldown
step blocks any alert whose match minute is past it; stoppage time counts as
the minute the feed reports (90+4 is 94).

Revision ID: 0024_max_fire_minute
Revises: 0023_visitor_sessions
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_max_fire_minute"
down_revision: str | None = "0023_visitor_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_rules ADD COLUMN max_fire_minute INTEGER;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_rules DROP COLUMN IF EXISTS max_fire_minute;
        """
    )
