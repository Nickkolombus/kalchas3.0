"""Visitor log: what each visit did with the watchlist.

Revision ID: 0031_visit_watchlist
Revises: 0030_watchlist_archive
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031_visit_watchlist"
down_revision: str | None = "0030_watchlist_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE visitor_sessions
            ADD COLUMN IF NOT EXISTS watchlist TEXT[] NOT NULL DEFAULT '{}';
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE visitor_sessions DROP COLUMN IF EXISTS watchlist;")
