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
      AND cached_at > NOW() - make_interval(days => :ttl_days)
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


def load_panel_cache(dsn: str, cache_key: str, *, ttl_days: int = 7) -> dict[str, Any] | None:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = conn.execute(
            GET_FRESH, {"cache_key": cache_key, "ttl_days": int(ttl_days)}
        ).mappings().first()
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
