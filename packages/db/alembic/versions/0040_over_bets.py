"""Over-goals bet per alert: the admin choice for first-half alerts and the graded bets.

Every alert is also read as an Over bet at the live price when it fired
(see ``kalchas_core.over_bet``). ``over_bet_settings`` holds which bet a
first-half alert shows (full-time Over +1.5 or half-time Over +0.5);
``alert_over_bets`` holds each alert's bets graded at full time, written once.

Revision ID: 0040_over_bets
Revises: 0039_match_history
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0040_over_bets"
down_revision: str | None = "0039_match_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS over_bet_settings (
            id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            first_half_mode TEXT NOT NULL DEFAULT 'ft_o15',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT over_bet_first_half_mode
                CHECK (first_half_mode IN ('ft_o15', 'ht_o05'))
        );

        INSERT INTO over_bet_settings (id)
        VALUES (1)
        ON CONFLICT (id) DO NOTHING;

        CREATE TABLE IF NOT EXISTS alert_over_bets (
            alert_id    BIGINT PRIMARY KEY REFERENCES alerts(id) ON DELETE CASCADE,
            primary_variant TEXT NOT NULL,
            bets        JSONB NOT NULL DEFAULT '{}',
            ht_goals    INTEGER,
            ft_goals    INTEGER,
            graded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS alert_over_bets;
        DROP TABLE IF EXISTS over_bet_settings;
        """
    )
