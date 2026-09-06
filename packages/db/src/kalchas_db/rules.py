"""strategy_rules read/write helpers (sync, for API/settings)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

LIST_RULES = text(
    """
    SELECT strategy_slot, strategy_name, success_window_minutes,
           expiration_buffer_minutes, infinite_ttl, team_specific, enabled
    FROM strategy_rules
    ORDER BY strategy_slot
    """
)

UPDATE_TEAM_SPECIFIC = text(
    """
    UPDATE strategy_rules
    SET team_specific = :team_specific, updated_at = NOW()
    WHERE strategy_slot = :slot
    RETURNING strategy_slot, strategy_name, success_window_minutes,
              expiration_buffer_minutes, infinite_ttl, team_specific, enabled
    """
)


def list_strategy_rules(dsn: str) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_RULES).mappings().all()
        return [dict(r) for r in rows]


def set_team_specific(dsn: str, slot: int, team_specific: bool) -> dict[str, Any] | None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        row = conn.execute(
            UPDATE_TEAM_SPECIFIC,
            {"slot": slot, "team_specific": team_specific},
        ).mappings().first()
        return dict(row) if row else None
