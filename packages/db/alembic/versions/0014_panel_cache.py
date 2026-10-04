"""7-day H2H overlay cache.

Revision ID: 0014_panel_cache
Revises: 0013_board_settings
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_panel_cache"
down_revision: str | None = "0013_board_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS panel_cache (
            cache_key  TEXT PRIMARY KEY,
            payload    JSONB NOT NULL,
            cached_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS panel_cache;")
