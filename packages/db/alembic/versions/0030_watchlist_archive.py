"""Watchlist archive: every day's list and match pages, kept with their results.

Revision ID: 0030_watchlist_archive
Revises: 0029_weekly_recaps
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030_watchlist_archive"
down_revision: str | None = "0029_weekly_recaps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_matches (
            match_id    TEXT PRIMARY KEY,
            day         DATE NOT NULL,
            payload     JSONB NOT NULL,
            settled     BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS watchlist_matches_day ON watchlist_matches (day);

        CREATE TABLE IF NOT EXISTS watchlist_days (
            day         DATE PRIMARY KEY,
            payload     JSONB NOT NULL,
            summary     JSONB NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS watchlist_days; DROP TABLE IF EXISTS watchlist_matches;")
