"""7-day JSON cache for overlay payloads (H2H first)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

GET_FRESH = text(
    """
    SELECT payload
    FROM panel_cache
    WHERE cache_key = :cache_key
      AND cached_at > NOW() - make_interval(hours => :ttl_hours)
    LIMIT 1
    """
)

UPSERT = text(
    """
    INSERT INTO panel_cache (cache_key, payload, cached_at)
    VALUES (:cache_key, CAST(:payload AS jsonb), NOW())
    ON CONFLICT (cache_key) DO UPDATE SET
        payload = EXCLUDED.payload,
        cached_at = NOW()
    """
)


def pair_cache_key(prefix: str, team1_id: int, team2_id: int) -> str:
    lo, hi = sorted((int(team1_id), int(team2_id)))
    return f"{prefix}_{lo}_{hi}"


def load_panel_cache(
    dsn: str,
    cache_key: str,
    *,
    ttl_days: int = 7,
    ttl_hours: int | None = None,
) -> dict[str, Any] | None:
    hours = int(ttl_hours) if ttl_hours is not None else int(ttl_days) * 24
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = (
            conn.execute(GET_FRESH, {"cache_key": cache_key, "ttl_hours": hours}).mappings().first()
        )
    if row is None:
        return None
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return dict(payload) if isinstance(payload, dict) else None


def save_panel_cache(dsn: str, cache_key: str, payload: dict[str, Any]) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT,
            {"cache_key": cache_key, "payload": json.dumps(payload)},
        )


FRESH_BY_PREFIX = text(
    """
    SELECT payload
    FROM panel_cache
    WHERE cache_key LIKE :pattern
      AND cached_at > NOW() - make_interval(hours => :hours)
    """
)


def load_panel_cache_prefix(dsn: str, prefix: str, *, hours: int) -> list[dict[str, Any]]:
    """Every fresh payload whose key starts with `prefix`."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(FRESH_BY_PREFIX, {"pattern": f"{prefix}%", "hours": int(hours)})
        payloads = [r["payload"] for r in rows.mappings().all()]
    out: list[dict[str, Any]] = []
    for payload in payloads:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict):
            out.append(dict(payload))
    return out


DELETE_OLDER = text(
    """
    DELETE FROM panel_cache
    WHERE cache_key LIKE :pattern
      AND cached_at < NOW() - make_interval(hours => :hours)
    """
)


def delete_panel_cache_older(dsn: str, prefix: str, *, hours: int) -> int:
    """Drop rows whose key starts with `prefix` and that are older than `hours`.

    The watchlist writes a row per match per day; this keeps them from piling up.
    """
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        result = conn.execute(DELETE_OLDER, {"pattern": f"{prefix}%", "hours": int(hours)})
    return int(result.rowcount or 0)
