"""Extra Fire conditions: left/right operands and a multiplier.

Revision ID: 0015_strategy_extra_conditions
Revises: 0014_panel_cache
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_strategy_extra_conditions"
down_revision: str | None = "0014_panel_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategy_conditions;")
    op.execute(
        """
        CREATE TABLE strategy_conditions (
            id              BIGSERIAL PRIMARY KEY,
            strategy_slot   INTEGER NOT NULL REFERENCES strategy_rules(strategy_slot),
            enabled         BOOLEAN NOT NULL DEFAULT TRUE,
            left_scope      TEXT NOT NULL,
            left_metric     TEXT NOT NULL,
            operator        TEXT NOT NULL,
            right_kind      TEXT NOT NULL DEFAULT 'value',
            right_scope     TEXT,
            right_metric    TEXT,
            right_value     DOUBLE PRECISION NOT NULL DEFAULT 0,
            multiplier      DOUBLE PRECISION NOT NULL DEFAULT 1,
            sort_order      INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS strategy_conditions_slot_idx
            ON strategy_conditions (strategy_slot, sort_order, id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategy_conditions;")
    op.execute(
        """
        CREATE TABLE strategy_conditions (
            id              BIGSERIAL PRIMARY KEY,
            strategy_slot   INTEGER NOT NULL REFERENCES strategy_rules(strategy_slot),
            metric_key      TEXT NOT NULL,
            scope           TEXT NOT NULL,
            operator        TEXT NOT NULL,
            threshold       DOUBLE PRECISION NOT NULL,
            enabled         BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE (strategy_slot, metric_key, scope, operator)
        );
        """
    )
