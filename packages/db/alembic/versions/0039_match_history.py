"""Keep each finished match's minute-by-minute stats after the live tables drop it.

The scanner deletes a match about six hours after its last update, and the
cascade takes its `match_minutes` and `match_events` with it. That left one
day of timelines, too few to backtest a strategy minute by minute (on 19 Nov
only 61 matches were left). The cleanup now copies each match into
`match_history` first: one row per match, with its minutes and events as
JSON arrays, kept for a set number of days.

Revision ID: 0039_match_history
Revises: 0038_alert_templates_strategy
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0039_match_history"
down_revision: str | None = "0038_alert_templates_strategy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS match_history (
            match_id      TEXT PRIMARY KEY,
            home_team     TEXT,
            away_team     TEXT,
            home_team_id  INTEGER,
            away_team_id  INTEGER,
            league_name   TEXT,
            league_id     INTEGER,
            country_name  TEXT,
            status_short  TEXT,
            home_score    INTEGER,
            away_score    INTEGER,
            last_minute   INTEGER,
            kickoff_at    TIMESTAMPTZ,
            last_seen_at  TIMESTAMPTZ,
            odds          JSONB NOT NULL DEFAULT '{}',
            minutes       JSONB NOT NULL DEFAULT '[]',
            events        JSONB NOT NULL DEFAULT '[]',
            archived_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS match_history_archived_at_idx
            ON match_history (archived_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS match_history;")
