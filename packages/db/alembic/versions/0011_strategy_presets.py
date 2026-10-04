"""Indexes and named formula-weight presets.

Revision ID: 0011_strategy_presets
Revises: 0010_alert_results_indexes
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_strategy_presets"
down_revision: str | None = "0010_alert_results_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_presets (
            strategy_key TEXT NOT NULL,
            name         TEXT NOT NULL,
            payload      JSONB NOT NULL DEFAULT '{}',
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (strategy_key, name)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategy_presets;")
