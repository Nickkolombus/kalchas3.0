"""Widen tips.csv inclusion window past the 30-second pulse.

Revision ID: 0017_tips_window
Revises: 0016_tips_export
Create Date: 2026-10-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_tips_window"
down_revision: str | None = "0016_tips_export"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tips_export_settings
            DROP CONSTRAINT IF EXISTS tips_export_alert_window;
        ALTER TABLE tips_export_settings
            ADD CONSTRAINT tips_export_alert_window
            CHECK (alert_window_seconds >= 1 AND alert_window_seconds <= 3600);
        ALTER TABLE tips_export_settings
            ALTER COLUMN alert_window_seconds SET DEFAULT 1800;
        UPDATE tips_export_settings
            SET alert_window_seconds = 1800, updated_at = NOW()
            WHERE id = 1 AND alert_window_seconds <= 60;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE tips_export_settings
            SET alert_window_seconds = 30, updated_at = NOW()
            WHERE id = 1 AND alert_window_seconds > 60;
        ALTER TABLE tips_export_settings
            DROP CONSTRAINT IF EXISTS tips_export_alert_window;
        ALTER TABLE tips_export_settings
            ALTER COLUMN alert_window_seconds SET DEFAULT 30;
        ALTER TABLE tips_export_settings
            ADD CONSTRAINT tips_export_alert_window
            CHECK (alert_window_seconds >= 1 AND alert_window_seconds <= 60);
        """
    )
