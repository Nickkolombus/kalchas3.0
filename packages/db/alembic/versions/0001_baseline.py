"""Baseline schema for Kalchas 3.0.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-29

One minute-level store, one alerts outbox, versioned strategy config.
Replaces 2.2's dual CREATE TABLE / migrations/ systems.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE matches (
            match_id        TEXT PRIMARY KEY,
            home_team       TEXT NOT NULL,
            away_team       TEXT NOT NULL,
            home_team_id    INTEGER,
            away_team_id    INTEGER,
            league_name     TEXT,
            status_short    TEXT,
            home_score      INTEGER NOT NULL DEFAULT 0,
            away_score      INTEGER NOT NULL DEFAULT 0,
            minute          INTEGER NOT NULL DEFAULT 0,
            kickoff_at      TIMESTAMPTZ,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE match_minutes (
            match_id        TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            minute          INTEGER NOT NULL,
            home_stats      JSONB NOT NULL DEFAULT '{}',
            away_stats      JSONB NOT NULL DEFAULT '{}',
            home_goals      INTEGER NOT NULL DEFAULT 0,
            away_goals      INTEGER NOT NULL DEFAULT 0,
            recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (match_id, minute)
        );

        CREATE TABLE alerts (
            id              BIGSERIAL PRIMARY KEY,
            match_id        TEXT NOT NULL,
            strategy_slot   INTEGER NOT NULL,
            strategy_key    TEXT NOT NULL,
            team            TEXT,
            value           DOUBLE PRECISION NOT NULL,
            minute          INTEGER NOT NULL,
            score           TEXT,
            home_team       TEXT,
            away_team       TEXT,
            payload         JSONB NOT NULL DEFAULT '{}',
            delivery_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (delivery_status IN ('pending', 'reserved', 'sent', 'failed', 'suppressed')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reserved_at     TIMESTAMPTZ,
            delivered_at    TIMESTAMPTZ,
            error           TEXT
        );
        CREATE INDEX idx_alerts_delivery ON alerts (delivery_status, created_at);
        CREATE INDEX idx_alerts_match ON alerts (match_id, strategy_slot);

        CREATE TABLE alert_outcomes (
            alert_id        BIGINT PRIMARY KEY REFERENCES alerts(id) ON DELETE CASCADE,
            state           TEXT NOT NULL,
            decision        TEXT,
            detail          JSONB NOT NULL DEFAULT '{}',
            evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE cooldowns (
            cooldown_key    TEXT PRIMARY KEY,
            match_id        TEXT NOT NULL,
            strategy_slot   INTEGER NOT NULL,
            team            TEXT,
            last_alert_minute INTEGER NOT NULL,
            last_alert_value  DOUBLE PRECISION NOT NULL,
            last_alert_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE strategy_rules (
            strategy_slot               INTEGER PRIMARY KEY,
            strategy_name               TEXT NOT NULL,
            success_window_minutes      INTEGER NOT NULL DEFAULT 20,
            expiration_buffer_minutes   INTEGER NOT NULL DEFAULT 2,
            infinite_ttl                BOOLEAN NOT NULL DEFAULT FALSE,
            team_specific               BOOLEAN NOT NULL DEFAULT TRUE,
            enabled                     BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        INSERT INTO strategy_rules
            (strategy_slot, strategy_name, success_window_minutes, expiration_buffer_minutes,
             infinite_ttl, team_specific, enabled)
        VALUES
            (1, 'Rule of 3', 999, 0, TRUE, TRUE, TRUE),
            (2, 'InPlay Pressure', 20, 2, FALSE, TRUE, TRUE),
            (3, 'Delta Goal', 20, 2, FALSE, TRUE, TRUE),
            (4, 'Delta 5min', 20, 2, FALSE, TRUE, TRUE),
            (5, 'NPEI', 20, 2, FALSE, FALSE, TRUE),
            (6, 'Omega', 20, 2, FALSE, TRUE, TRUE),
            (7, 'K-Score', 20, 2, FALSE, TRUE, TRUE),
            (9, 'Team Form', 20, 2, FALSE, FALSE, TRUE),
            (10, 'H2H Insights', 20, 2, FALSE, FALSE, TRUE);

        CREATE TABLE strategy_conditions (
            id              BIGSERIAL PRIMARY KEY,
            strategy_slot   INTEGER NOT NULL REFERENCES strategy_rules(strategy_slot),
            metric_key      TEXT NOT NULL,
            scope           TEXT NOT NULL,
            operator        TEXT NOT NULL,
            threshold       DOUBLE PRECISION NOT NULL,
            enabled         BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE (strategy_slot, metric_key, scope, operator)
        );

        CREATE TABLE strategy_thresholds (
            strategy_slot   INTEGER PRIMARY KEY REFERENCES strategy_rules(strategy_slot),
            threshold       DOUBLE PRECISION NOT NULL,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE payments (
            id              BIGSERIAL PRIMARY KEY,
            stripe_event_id TEXT UNIQUE NOT NULL,
            supabase_user_id TEXT NOT NULL,
            price_id        TEXT NOT NULL,
            status          TEXT NOT NULL,
            raw             JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS payments;
        DROP TABLE IF EXISTS strategy_thresholds;
        DROP TABLE IF EXISTS strategy_conditions;
        DROP TABLE IF EXISTS strategy_rules;
        DROP TABLE IF EXISTS cooldowns;
        DROP TABLE IF EXISTS alert_outcomes;
        DROP TABLE IF EXISTS alerts;
        DROP TABLE IF EXISTS match_minutes;
        DROP TABLE IF EXISTS matches;
        """
    )
