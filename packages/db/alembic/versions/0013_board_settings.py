"""Board-wide Various settings, starting with sweet-spot windows.

Revision ID: 0013_board_settings
Revises: 0012_match_minute_display
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_board_settings"
down_revision: str | None = "0012_match_minute_display"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS board_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            sweet_spot_ht1_start INTEGER NOT NULL DEFAULT 28,
            sweet_spot_ht1_end INTEGER NOT NULL DEFAULT 44,
            sweet_spot_ht2_start INTEGER NOT NULL DEFAULT 72,
            sweet_spot_ht2_end INTEGER NOT NULL DEFAULT 88,
            sweet_spot_include_injury BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        INSERT INTO board_settings (id)
        VALUES (1)
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS board_settings;")
