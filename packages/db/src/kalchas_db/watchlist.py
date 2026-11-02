"""Watchlist archive: the scanner writes each day's match pages and list, the
API reads them. Kept for good, so past days can be revisited with results."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

UPSERT_MATCH = text(
    """
    INSERT INTO watchlist_matches (match_id, day, payload, settled, updated_at)
    VALUES (:match_id, :day, CAST(:payload AS jsonb), :settled, NOW())
    ON CONFLICT (match_id) DO UPDATE SET
        day = EXCLUDED.day,
        payload = EXCLUDED.payload,
        settled = EXCLUDED.settled,
        updated_at = NOW()
    """
)

MATCHES_ON = text("SELECT payload FROM watchlist_matches WHERE day = :day")

ONE_MATCH = text("SELECT payload FROM watchlist_matches WHERE match_id = :match_id")

DELETE_MATCH = text("DELETE FROM watchlist_matches WHERE match_id = :match_id")

UPSERT_DAY = text(
    """
    INSERT INTO watchlist_days (day, payload, summary, updated_at)
    VALUES (:day, CAST(:payload AS jsonb), CAST(:summary AS jsonb), NOW())
    ON CONFLICT (day) DO UPDATE SET
        payload = EXCLUDED.payload,
        summary = EXCLUDED.summary,
        updated_at = NOW()
    """
)

ONE_DAY = text("SELECT payload FROM watchlist_days WHERE day = :day")

MONTH = text(
    """
    SELECT day, summary FROM watchlist_days
    WHERE day >= :start AND day < :end
    ORDER BY day
    """
)

FIRST_DAY = text("SELECT MIN(day) AS day FROM watchlist_days")


def _doc(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, dict) else None


def save_watchlist_match(dsn: str, day: str, payload: dict[str, Any], *, settled: bool) -> None:
    with sync_engine(dsn).begin() as conn:
        conn.execute(
            UPSERT_MATCH,
            {
                "match_id": str(payload["match_id"]),
                "day": date.fromisoformat(day),
                "payload": json.dumps(payload),
                "settled": settled,
            },
        )


def load_watchlist_matches_on(dsn: str, day: str) -> list[dict[str, Any]]:
    with sync_engine(dsn).connect() as conn:
        rows = conn.execute(MATCHES_ON, {"day": date.fromisoformat(day)}).mappings().all()
    return [doc for doc in (_doc(r["payload"]) for r in rows) if doc]


def load_watchlist_match(dsn: str, match_id: str) -> dict[str, Any] | None:
    with sync_engine(dsn).connect() as conn:
        row = conn.execute(ONE_MATCH, {"match_id": match_id}).mappings().first()
    return _doc(row["payload"]) if row else None


def delete_watchlist_match(dsn: str, match_id: str) -> None:
    with sync_engine(dsn).begin() as conn:
        conn.execute(DELETE_MATCH, {"match_id": match_id})


def save_watchlist_day(dsn: str, day: str, payload: dict[str, Any]) -> None:
    with sync_engine(dsn).begin() as conn:
        conn.execute(
            UPSERT_DAY,
            {
                "day": date.fromisoformat(day),
                "payload": json.dumps(payload),
                "summary": json.dumps(payload.get("summary") or {}),
            },
        )


def load_watchlist_day(dsn: str, day: str) -> dict[str, Any] | None:
    with sync_engine(dsn).connect() as conn:
        row = conn.execute(ONE_DAY, {"day": date.fromisoformat(day)}).mappings().first()
    return _doc(row["payload"]) if row else None


def load_watchlist_month(dsn: str, start: date, end: date) -> list[dict[str, Any]]:
    """``[{"day": "2026-11-02", "summary": {...}}]`` for days in [start, end)."""
    with sync_engine(dsn).connect() as conn:
        rows = conn.execute(MONTH, {"start": start, "end": end}).mappings().all()
    return [{"day": r["day"].isoformat(), "summary": _doc(r["summary"]) or {}} for r in rows]


def first_watchlist_day(dsn: str) -> str | None:
    with sync_engine(dsn).connect() as conn:
        row = conn.execute(FIRST_DAY).mappings().first()
    return row["day"].isoformat() if row and row["day"] else None
