"""Country crest URL and cached 1X2 odds on the match header.

Revision ID: 0005_match_country_odds
Revises: 0004_match_feed_extras
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_match_country_odds"
down_revision: str | None = "0004_match_feed_extras"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS country_name TEXT,
            ADD COLUMN IF NOT EXISTS country_logo TEXT,
            ADD COLUMN IF NOT EXISTS odds JSONB NOT NULL DEFAULT '{}';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE matches
            DROP COLUMN IF EXISTS country_name,
            DROP COLUMN IF EXISTS country_logo,
            DROP COLUMN IF EXISTS odds;
        """
    )
