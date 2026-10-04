"""Persist scanner WebSocket and fallback health.

Revision ID: 0002_scanner_status
Revises: 0001_baseline
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_scanner_status"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE scanner_status (
            singleton          BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            mode               TEXT NOT NULL DEFAULT 'starting',
            connected          BOOLEAN NOT NULL DEFAULT FALSE,
            messages_received  BIGINT NOT NULL DEFAULT 0,
            reconnects         INTEGER NOT NULL DEFAULT 0,
            last_message_at    TIMESTAMPTZ,
            last_http_poll_at  TIMESTAMPTZ,
            last_error         TEXT,
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scanner_status")
