"""Live visitor presence: who's on the board right now, and from where.

Revision ID: 0020_live_visitors
Revises: 0019_telegram_free_channel
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020_live_visitors"
down_revision: str | None = "0019_telegram_free_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE live_visitors (
            visitor_id   TEXT PRIMARY KEY,
            country      TEXT,
            last_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX idx_live_visitors_last_seen ON live_visitors (last_seen);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS live_visitors;
        """
    )
