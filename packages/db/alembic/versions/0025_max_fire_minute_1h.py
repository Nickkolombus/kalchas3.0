"""Per-strategy first-half cut-off: don't fire late in the first half.

Adds ``strategy_rules.max_fire_minute_1h``. NULL (the default for every row)
is off, so nothing changes until an admin sets a minute. The scanner blocks
an alert when the match is in the first half (or at half-time) and its minute
is past it. First-half stoppage arrives as the running clock (45+3 is 48), so
the scanner decides "first half" from the match status, not the minute.

Motivation: the 2026-10-25 results export had first-half alerts confirming 1
in 8, most of them Δ10′ firing at 45′ with the half about to end.

Revision ID: 0025_max_fire_minute_1h
Revises: 0024_max_fire_minute
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025_max_fire_minute_1h"
down_revision: str | None = "0024_max_fire_minute"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_rules ADD COLUMN max_fire_minute_1h INTEGER;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_rules DROP COLUMN IF EXISTS max_fire_minute_1h;
        """
    )
