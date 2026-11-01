"""Weekly recap drafts: drafted by the bot, edited and approved in admin, then posted.

Revision ID: 0029_weekly_recaps
Revises: 0028_twitter_tweet_id
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029_weekly_recaps"
down_revision: str | None = "0028_twitter_tweet_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_recaps (
            week_start  DATE PRIMARY KEY,
            status      TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'approved', 'posting', 'posted', 'skipped', 'failed')),
            data        JSONB NOT NULL,
            texts       JSONB NOT NULL,
            channels    JSONB NOT NULL
                DEFAULT '{"x": true, "telegram_free": true, "telegram_paid": true, "discord": true}',
            post_log    JSONB NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notified_at TIMESTAMPTZ,
            approved_at TIMESTAMPTZ,
            posted_at   TIMESTAMPTZ
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS weekly_recaps;")
