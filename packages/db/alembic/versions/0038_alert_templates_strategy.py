"""Alert templates per strategy, and X as its own channel.

Each template now belongs to a strategy: ``default`` (every strategy without its
own text; the rows saved so far) or a strategy key such as ``delta_5min``.
X gets its own templates (alert, goal reply and the no-goal reply X posts).

Revision ID: 0038_alert_templates_strategy
Revises: 0037_parlay_slips
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0038_alert_templates_strategy"
down_revision: str | None = "0037_parlay_slips"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE alert_templates
            ADD COLUMN IF NOT EXISTS strategy TEXT NOT NULL DEFAULT 'default';
        ALTER TABLE alert_templates DROP CONSTRAINT IF EXISTS alert_templates_channel_check;
        ALTER TABLE alert_templates DROP CONSTRAINT IF EXISTS alert_templates_kind_check;
        ALTER TABLE alert_templates ADD CONSTRAINT alert_templates_channel_check
            CHECK (channel IN ('paid', 'free', 'discord', 'x'));
        ALTER TABLE alert_templates ADD CONSTRAINT alert_templates_kind_check
            CHECK (kind IN ('alert', 'goal', 'miss'));
        ALTER TABLE alert_templates DROP CONSTRAINT IF EXISTS alert_templates_pkey;
        ALTER TABLE alert_templates ADD PRIMARY KEY (strategy, channel, kind);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM alert_templates
        WHERE strategy <> 'default' OR channel = 'x' OR kind = 'miss';
        ALTER TABLE alert_templates DROP CONSTRAINT IF EXISTS alert_templates_pkey;
        ALTER TABLE alert_templates DROP COLUMN IF EXISTS strategy;
        ALTER TABLE alert_templates DROP CONSTRAINT IF EXISTS alert_templates_channel_check;
        ALTER TABLE alert_templates DROP CONSTRAINT IF EXISTS alert_templates_kind_check;
        ALTER TABLE alert_templates ADD CONSTRAINT alert_templates_channel_check
            CHECK (channel IN ('paid', 'free', 'discord'));
        ALTER TABLE alert_templates ADD CONSTRAINT alert_templates_kind_check
            CHECK (kind IN ('alert', 'goal'));
        ALTER TABLE alert_templates ADD PRIMARY KEY (channel, kind);
        """
    )
