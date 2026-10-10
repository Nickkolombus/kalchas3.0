"""BFbot /tips.csv settings, first-seen log, and poll history.

Revision ID: 0016_tips_export
Revises: 0015_strategy_extra_conditions
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016_tips_export"
down_revision: str | None = "0015_strategy_extra_conditions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tips_export_settings (
            id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            alert_window_seconds INTEGER NOT NULL DEFAULT 30,
            last_polled_at TIMESTAMPTZ,
            last_row_count INTEGER NOT NULL DEFAULT 0,
            poll_count INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT tips_export_alert_window
                CHECK (alert_window_seconds >= 1 AND alert_window_seconds <= 60)
        );

        INSERT INTO tips_export_settings (id)
        VALUES (1)
        ON CONFLICT (id) DO NOTHING;

        CREATE TABLE IF NOT EXISTS tips_export_log (
            id BIGSERIAL PRIMARY KEY,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            match_id TEXT NOT NULL,
            alert_time TEXT NOT NULL,
            api_home TEXT,
            api_away TEXT,
            event_name TEXT NOT NULL,
            market_type TEXT,
            selection_name TEXT,
            correlation_method TEXT,
            fuzzy_applied BOOLEAN,
            strategies TEXT,
            CONSTRAINT tips_export_log_unique_alert UNIQUE (match_id, alert_time)
        );

        CREATE INDEX IF NOT EXISTS tips_export_log_recorded_at_idx
            ON tips_export_log (recorded_at DESC);

        CREATE TABLE IF NOT EXISTS tips_export_polls (
            id BIGSERIAL PRIMARY KEY,
            polled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            row_count INTEGER NOT NULL DEFAULT 0,
            user_agent TEXT
        );

        CREATE INDEX IF NOT EXISTS tips_export_polls_polled_at_idx
            ON tips_export_polls (polled_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tips_export_polls;")
    op.execute("DROP TABLE IF EXISTS tips_export_log;")
    op.execute("DROP TABLE IF EXISTS tips_export_settings;")
