"""History of strategy config saves: one row per change with before/after values.

Thresholds, rules, extra conditions and weight overrides are overwritten in
place, so without this table there is no way to tell which config produced a
given week's alerts.

Revision ID: 0032_strategy_config_history
Revises: 0031_visit_watchlist
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032_strategy_config_history"
down_revision: str | None = "0031_visit_watchlist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_config_history (
            id              BIGSERIAL PRIMARY KEY,
            changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            strategy_slot   SMALLINT,
            strategy_key    TEXT,
            kind            TEXT NOT NULL
                CHECK (kind IN ('threshold', 'rule', 'conditions', 'weights')),
            before          JSONB,
            after           JSONB
        );
        CREATE INDEX IF NOT EXISTS strategy_config_history_changed_at_idx
            ON strategy_config_history (changed_at);
        CREATE INDEX IF NOT EXISTS strategy_config_history_slot_idx
            ON strategy_config_history (strategy_slot, changed_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategy_config_history;")
