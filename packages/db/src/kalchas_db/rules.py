"""strategy_rules read/write helpers (sync, for API/settings)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

LIST_RULES = text(
    """
    SELECT strategy_slot, strategy_name, success_window_minutes,
           expiration_buffer_minutes, infinite_ttl, team_specific, enabled,
           expire_at_half_end
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


GET_TEAM_SPECIFIC_FOR_UPDATE = text(
    """
    SELECT team_specific FROM strategy_rules WHERE strategy_slot = :slot FOR UPDATE
    """
)


def set_team_specific(dsn: str, slot: int, team_specific: bool) -> dict[str, Any] | None:
    from kalchas_db.settings import record_config_change

    eng = sync_engine(dsn)
    with eng.begin() as conn:
        before = conn.execute(GET_TEAM_SPECIFIC_FOR_UPDATE, {"slot": slot}).mappings().first()
        row = (
            conn.execute(
                UPDATE_TEAM_SPECIFIC,
                {"slot": slot, "team_specific": team_specific},
            )
            .mappings()
            .first()
        )
        if row is not None:
            record_config_change(
                conn,
                kind="rule",
                slot=slot,
                before={"team_specific": bool(before["team_specific"])} if before else None,
                after={"team_specific": bool(row["team_specific"])},
            )
        return dict(row) if row else None
