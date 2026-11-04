"""Admin-edited text for alert messages, one per channel (paid, free, Discord) and kind.

A missing or switched-off row means the bot sends its built-in text. The bot
counts how often a saved template could not be used, so admin can show it.

Revision ID: 0035_alert_templates
Revises: 0034_contact_messages
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035_alert_templates"
down_revision: str | None = "0034_contact_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_templates (
            channel TEXT NOT NULL CHECK (channel IN ('paid', 'free', 'discord')),
            kind TEXT NOT NULL CHECK (kind IN ('alert', 'goal')),
            body TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fallback_count INTEGER NOT NULL DEFAULT 0,
            last_fallback_at TIMESTAMPTZ,
            last_fallback_reason TEXT,
            PRIMARY KEY (channel, kind)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alert_templates")
