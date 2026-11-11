"""Posted parlay slips: what went out, where, and how it settled.

Revision ID: 0037_parlay_slips
Revises: 0036_push_subscriptions
Create Date: 2026-11-08

One row per slip the admin posts. ``legs`` is the slip exactly as previewed
(match, market, label, price), so the result is judged against what was
posted, not against a list that moved since. ``post_log`` holds each channel's
message id (the reply needs it), ``outcomes`` each leg's verdict, and
``reply_log`` the result replies.

Status moves forward only:
approved -> posting -> posted | failed
posted -> needs_decision (a leg was called off or can't be judged) -> posted
posted -> awaiting_reply (autopost off) -> reply_approved | reply_skipped
posted -> reply_approved (autopost on) -> replying -> replied | reply_failed
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0037_parlay_slips"
down_revision: str | None = "0036_push_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS parlay_slips (
            id BIGSERIAL PRIMARY KEY,
            day DATE NOT NULL,
            slot TEXT NOT NULL,
            style TEXT NOT NULL,
            legs JSONB NOT NULL,
            caption TEXT NOT NULL DEFAULT '',
            x_text TEXT NOT NULL DEFAULT '',
            channels JSONB NOT NULL DEFAULT '{}'::jsonb,
            autopost BOOLEAN NOT NULL DEFAULT TRUE,
            status TEXT NOT NULL DEFAULT 'approved',
            post_log JSONB NOT NULL DEFAULT '{}'::jsonb,
            outcomes JSONB NOT NULL DEFAULT '{}'::jsonb,
            result TEXT,
            asked_at TIMESTAMPTZ,
            reply_log JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            posted_at TIMESTAMPTZ,
            settled_at TIMESTAMPTZ,
            replied_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS parlay_slips_status_idx ON parlay_slips (status);
        CREATE INDEX IF NOT EXISTS parlay_slips_created_idx ON parlay_slips (created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS parlay_slips")
