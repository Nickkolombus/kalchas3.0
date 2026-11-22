"""Per-strategy "once per half": at most one alert per team in each half.

Adds ``strategy_rules.once_per_half``. FALSE (the default for every row) keeps
the cooldown and its bypass as they were; the admin turns it on per strategy.

Motivation: on 2026-11-22 K-Index fired 146 alerts on 58 teams, because a
5-point rise skipped its 10' cooldown and K moves that much easily. One match
fired eight times. As Over bets the repeats lost most of the money; the first
alert per match was close to break-even.

Revision ID: 0041_once_per_half
Revises: 0040_over_bets
Create Date: 2026-11-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0041_once_per_half"
down_revision: str | None = "0040_over_bets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_rules
            ADD COLUMN IF NOT EXISTS once_per_half BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_rules DROP COLUMN IF EXISTS once_per_half;
        """
    )
