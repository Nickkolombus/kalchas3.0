"""Persist provider team badge URLs on the match header.

Revision ID: 0007_match_team_logos
Revises: 0006_admin_settings
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_match_team_logos"
down_revision: str | None = "0006_admin_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS home_team_logo TEXT,
            ADD COLUMN IF NOT EXISTS away_team_logo TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            DROP COLUMN IF EXISTS home_team_logo,
            DROP COLUMN IF EXISTS away_team_logo;
        """
    )
