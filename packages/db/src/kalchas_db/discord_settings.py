"""Admin-editable Discord bot settings: channel ids and per-channel on/off."""

from __future__ import annotations

from typing import Any

import asyncpg
from sqlalchemy import text

from kalchas_db.sync import sync_engine

DEFAULTS: dict[str, Any] = {
    "free_channel_id": None,
    "paid_channel_id": None,
    "free_enabled": True,
    "paid_enabled": True,
}

GET_DISCORD_SETTINGS = text(
    """
    SELECT free_channel_id, paid_channel_id, free_enabled, paid_enabled
    FROM discord_settings
    WHERE id = 1
    """
)

UPSERT_DISCORD_SETTINGS = text(
    """
    INSERT INTO discord_settings (
        id, free_channel_id, paid_channel_id, free_enabled, paid_enabled, updated_at
    )
    VALUES (1, :free_channel_id, :paid_channel_id, :free_enabled, :paid_enabled, NOW())
    ON CONFLICT (id) DO UPDATE SET
        free_channel_id = EXCLUDED.free_channel_id,
        paid_channel_id = EXCLUDED.paid_channel_id,
        free_enabled = EXCLUDED.free_enabled,
        paid_enabled = EXCLUDED.paid_enabled,
        updated_at = NOW()
    """
)

FETCH_DISCORD_SETTINGS = """
SELECT free_channel_id, paid_channel_id, free_enabled, paid_enabled
FROM discord_settings
WHERE id = 1
"""


def _channel_id(value: Any) -> str | None:
    text_value = str(value).strip() if value is not None else ""
    return text_value or None


def normalize_discord_settings(fields: dict[str, Any] | None = None) -> dict[str, Any]:
    data = fields or {}
    return {
        "free_channel_id": _channel_id(data.get("free_channel_id")),
        "paid_channel_id": _channel_id(data.get("paid_channel_id")),
        "free_enabled": bool(data.get("free_enabled", True)),
        "paid_enabled": bool(data.get("paid_enabled", True)),
    }


def get_discord_settings(dsn: str) -> dict[str, Any]:
    """Sync read for the admin API."""
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = conn.execute(GET_DISCORD_SETTINGS).mappings().first()
    if row is None:
        return dict(DEFAULTS)
    return normalize_discord_settings(dict(row))


def upsert_discord_settings(dsn: str, fields: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_discord_settings(fields)
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(UPSERT_DISCORD_SETTINGS, payload)
    return payload


async def fetch_discord_settings(conn: asyncpg.Connection) -> dict[str, Any]:
    """Async read for the delivery worker. Missing table == everything off."""
    try:
        row = await conn.fetchrow(FETCH_DISCORD_SETTINGS)
    except Exception:  # noqa: BLE001 — table may be missing before migration 0027
        return dict(DEFAULTS)
    if row is None:
        return dict(DEFAULTS)
    return normalize_discord_settings(dict(row))
