"""Browser push: goal notifications for matches a visitor pinned.

Revision ID: 0036_push_subscriptions
Revises: 0035_alert_templates
Create Date: 2026-11-05

``push_subscriptions`` holds one row per browser that turned goal alerts on,
with the match ids it has pinned. ``push_goal_marks`` is the last score the
sender saw per match, so a goal is pushed once even across bot restarts.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036_push_subscriptions"
down_revision: str | None = "0035_alert_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id BIGSERIAL PRIMARY KEY,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            match_ids TEXT[] NOT NULL DEFAULT '{}',
            user_agent TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_sent_at TIMESTAMPTZ,
            fail_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS push_subscriptions_match_ids_idx
            ON push_subscriptions USING GIN (match_ids);

        CREATE TABLE IF NOT EXISTS push_goal_marks (
            match_id TEXT PRIMARY KEY,
            home_score INTEGER NOT NULL,
            away_score INTEGER NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS push_goal_marks")
    op.execute("DROP TABLE IF EXISTS push_subscriptions")
