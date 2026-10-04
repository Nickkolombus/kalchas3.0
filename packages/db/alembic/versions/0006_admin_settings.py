"""Admin-tunable fire thresholds, formula weights, and cooldown columns.

Revision ID: 0006_admin_settings
Revises: 0005_match_country_odds
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_admin_settings"
down_revision: str | None = "0005_match_country_odds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_rules
            ADD COLUMN IF NOT EXISTS cooldown_minutes INTEGER NOT NULL DEFAULT 10,
            ADD COLUMN IF NOT EXISTS cooldown_bypass_delta DOUBLE PRECISION;

        UPDATE strategy_rules SET cooldown_bypass_delta = 0.5 WHERE strategy_slot = 1
            AND cooldown_bypass_delta IS NULL;
        UPDATE strategy_rules SET cooldown_bypass_delta = 10.0 WHERE strategy_slot = 2
            AND cooldown_bypass_delta IS NULL;
        UPDATE strategy_rules SET cooldown_bypass_delta = 4.0 WHERE strategy_slot = 3
            AND cooldown_bypass_delta IS NULL;
        UPDATE strategy_rules SET cooldown_bypass_delta = 1.0 WHERE strategy_slot = 4
            AND cooldown_bypass_delta IS NULL;
        UPDATE strategy_rules SET cooldown_bypass_delta = 1.5 WHERE strategy_slot = 6
            AND cooldown_bypass_delta IS NULL;
        UPDATE strategy_rules SET cooldown_bypass_delta = 5.0 WHERE strategy_slot = 7
            AND cooldown_bypass_delta IS NULL;

        INSERT INTO strategy_thresholds (strategy_slot, threshold)
        VALUES
            (1, 1.0),
            (2, 70.0),
            (3, 6.0),
            (4, 3.0),
            (6, 0.0),
            (7, 60.0)
        ON CONFLICT (strategy_slot) DO NOTHING;

        CREATE TABLE IF NOT EXISTS strategy_weights (
            strategy_key    TEXT NOT NULL,
            coeff_key       TEXT NOT NULL,
            value           DOUBLE PRECISION NOT NULL,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (strategy_key, coeff_key)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS strategy_weights;
        ALTER TABLE strategy_rules
            DROP COLUMN IF EXISTS cooldown_minutes,
            DROP COLUMN IF EXISTS cooldown_bypass_delta;
        """
    )
