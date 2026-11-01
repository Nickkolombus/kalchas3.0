"""Twitter: store the alert tweet id so outcomes can reply under it.

Revision ID: 0028_twitter_tweet_id
Revises: 0027_discord_bot
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028_twitter_tweet_id"
down_revision: str | None = "0027_discord_bot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE alerts
            ADD COLUMN IF NOT EXISTS twitter_tweet_id TEXT;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS twitter_tweet_id;")
