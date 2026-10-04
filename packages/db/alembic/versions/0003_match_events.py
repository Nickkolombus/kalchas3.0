"""Persist normalized match goals and cards.

Revision ID: 0003_match_events
Revises: 0002_scanner_status
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_match_events"
down_revision: str | None = "0002_scanner_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE match_events (
            match_id    TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            event_key   TEXT NOT NULL,
            event_type  TEXT NOT NULL CHECK (event_type IN ('goal', 'card')),
            minute      INTEGER NOT NULL,
            side        TEXT NOT NULL CHECK (side IN ('home', 'away')),
            team        TEXT,
            player_name TEXT,
            detail      TEXT,
            payload     JSONB NOT NULL DEFAULT '{}',
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (match_id, event_key)
        );
        CREATE INDEX idx_match_events_timeline ON match_events (match_id, minute, event_type);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS match_events")
