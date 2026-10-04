"""Persist provider league_id on the match header.

Revision ID: 0008_match_league_id
Revises: 0007_match_team_logos
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_match_league_id"
down_revision: str | None = "0007_match_team_logos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS league_id INTEGER;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            DROP COLUMN IF EXISTS league_id;
        """
    )
