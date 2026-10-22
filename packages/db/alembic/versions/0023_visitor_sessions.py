"""Visitor log: one row per visit, kept 30 days, for the admin Visitors tab.

``live_visitors`` only answers "who is here now" -- one row per visitor,
deleted ten minutes after their last ping -- so it can't hold first seen,
duration or history. This table keeps one row per visit (a run of activity
with no gap longer than 30 minutes):

* ``visitor_id`` is the same client-generated id the board poll already
  sends; NULL for a page load that never ran the JS heartbeat (crawlers,
  link previews, no-JS clients).
* ``ip_masked`` is the caller's address with the host part dropped
  (IPv4 /24, IPv6 /48) -- enough to spot a data-centre range or group
  page loads, not enough to identify a household.
* ``referrer`` is the referring host only, never the full URL.

Bot/human is decided at read time from these columns, so the rules can
change without rewriting stored rows.

Revision ID: 0023_visitor_sessions
Revises: 0022_form_bar_pace
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023_visitor_sessions"
down_revision: str | None = "0022_form_bar_pace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE visitor_sessions (
            id              BIGSERIAL PRIMARY KEY,
            visitor_id      TEXT,
            ip_masked       TEXT,
            country         TEXT,
            user_agent      TEXT,
            referrer        TEXT,
            landing_path    TEXT,
            first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            page_loads      INTEGER NOT NULL DEFAULT 0,
            heartbeats      INTEGER NOT NULL DEFAULT 0,
            matches_viewed  TEXT[] NOT NULL DEFAULT '{}',
            telegram_free   BOOLEAN NOT NULL DEFAULT FALSE,
            telegram_paid   BOOLEAN NOT NULL DEFAULT FALSE
        );

        CREATE INDEX idx_visitor_sessions_visitor
            ON visitor_sessions (visitor_id, last_seen DESC);
        CREATE INDEX idx_visitor_sessions_anon
            ON visitor_sessions (ip_masked, last_seen DESC) WHERE visitor_id IS NULL;
        CREATE INDEX idx_visitor_sessions_last_seen ON visitor_sessions (last_seen);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS visitor_sessions;
        """
    )
