"""Synchronous helpers for the scanner process (poll loop is sync today)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_engine: Engine | None = None

INSERT_PENDING = text(
    """
    INSERT INTO alerts (
        match_id, strategy_slot, strategy_key, team, value, minute, score,
        home_team, away_team, payload, delivery_status
    ) VALUES (
        :match_id, :strategy_slot, :strategy_key, :team, :value, :minute, :score,
        :home_team, :away_team, CAST(:payload AS jsonb), 'pending'
    )
    RETURNING id
    """
)


def sync_engine(dsn: str) -> Engine:
    global _engine
    if _engine is None:
        url = dsn
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if "+asyncpg" in url:
            url = url.replace("+asyncpg", "")
        _engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)
    return _engine


def insert_pending_sync(dsn: str, alert: dict[str, Any]) -> int:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        row = conn.execute(
            INSERT_PENDING,
            {
                "match_id": alert.get("match_id"),
                "strategy_slot": int(alert["strategy_slot"]),
                "strategy_key": alert.get("strategy") or alert.get("strategy_key"),
                "team": alert.get("team"),
                "value": float(alert["value"]),
                "minute": int(alert["minute"]),
                "score": alert.get("score"),
                "home_team": alert.get("home"),
                "away_team": alert.get("away"),
                "payload": json.dumps(alert),
            },
        ).one()
        return int(row[0])
