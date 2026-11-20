"""Over-goals bet per alert: admin setting, full-time grading and summaries.

See ``kalchas_core.over_bet`` for what the bets are.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text

from kalchas_db.alerts import _results_filter
from kalchas_db.sync import sync_engine

GET_SETTINGS = text("SELECT first_half_mode, updated_at FROM over_bet_settings WHERE id = 1")

UPSERT_MODE = text(
    """
    INSERT INTO over_bet_settings (id, first_half_mode, updated_at)
    VALUES (1, :mode, NOW())
    ON CONFLICT (id) DO UPDATE SET
        first_half_mode = EXCLUDED.first_half_mode,
        updated_at = NOW()
    """
)

LIST_UNGRADED_FOR_MATCH = text(
    """
    SELECT a.id, a.minute, a.score, a.payload->'over_bet' AS over_bet,
           a.payload->'live_goal_odds' AS live_goal_odds,
           a.payload->>'status_short' AS status_short
    FROM alerts a
    LEFT JOIN alert_over_bets ob ON ob.alert_id = a.id
    WHERE a.match_id = :match_id AND ob.alert_id IS NULL
    ORDER BY a.id
    """
)

INSERT_GRADED = text(
    """
    INSERT INTO alert_over_bets (alert_id, primary_variant, bets, ht_goals, ft_goals)
    VALUES (:alert_id, :primary_variant, CAST(:bets AS JSONB), :ht_goals, :ft_goals)
    ON CONFLICT (alert_id) DO NOTHING
    """
)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def get_settings_sync(dsn: str) -> dict[str, Any]:
    from kalchas_core.over_bet import DEFAULT_FIRST_HALF_MODE, normalize_first_half_mode

    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = conn.execute(GET_SETTINGS).mappings().first()
    if row is None:
        return {"first_half_mode": DEFAULT_FIRST_HALF_MODE, "updated_at": None}
    return {
        "first_half_mode": normalize_first_half_mode(row["first_half_mode"]),
        "updated_at": _iso(row["updated_at"]),
    }


def set_first_half_mode_sync(dsn: str, mode: str) -> dict[str, Any]:
    from kalchas_core.over_bet import FIRST_HALF_MODES

    if mode not in FIRST_HALF_MODES:
        raise ValueError(f"first_half_mode must be one of {FIRST_HALF_MODES}")
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(UPSERT_MODE, {"mode": mode})
    return get_settings_sync(dsn)


def list_ungraded_alerts_for_match_sync(dsn: str, match_id: str) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_UNGRADED_FOR_MATCH, {"match_id": match_id}).mappings().all()
    out = []
    for row in rows:
        item = dict(row)
        item["over_bet"] = _json(item.get("over_bet"))
        item["live_goal_odds"] = _json(item.get("live_goal_odds"))
        out.append(item)
    return out


def insert_graded_over_bets_sync(dsn: str, rows: list[dict[str, Any]]) -> int:
    """Write-once rows: ``alert_id``, ``primary_variant``, ``bets``, ``ht_goals``, ``ft_goals``."""
    if not rows:
        return 0
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        for row in rows:
            conn.execute(
                INSERT_GRADED,
                {
                    "alert_id": int(row["alert_id"]),
                    "primary_variant": str(row["primary_variant"]),
                    "bets": json.dumps(row.get("bets") or {}),
                    "ht_goals": row.get("ht_goals"),
                    "ft_goals": row.get("ft_goals"),
                },
            )
    return len(rows)


def over_bet_summary_sync(
    dsn: str,
    *,
    since: datetime,
    until: datetime,
    strategies: list[str] | None = None,
    state: str | None = None,
    team: str | None = None,
    league: str | None = None,
) -> list[dict[str, Any]]:
    """Per bet variant over the same filter as the results list.

    Rows: ``variant``, ``chosen`` (the bet the alert showed), ``graded``, ``won``,
    ``priced`` (graded with a stored price), ``priced_won``, ``avg_price``,
    ``profit`` (1-unit stakes at the stored price, no commission).
    """
    clause, params = _results_filter(
        since=since,
        until=until,
        strategies=strategies,
        state=state,
        team=team,
        league=league,
    )
    sql = text(
        f"""
        WITH bets AS (
            SELECT b.key AS variant,
                   (b.key = ob.primary_variant) AS chosen,
                   b.value->>'won' AS won,
                   CASE WHEN (b.value->>'price') ~ '^[0-9.]+$'
                        THEN (b.value->>'price')::float END AS price
            FROM alerts a
            JOIN alert_over_bets ob ON ob.alert_id = a.id
            LEFT JOIN alert_outcomes o ON o.alert_id = a.id
            CROSS JOIN LATERAL jsonb_each(ob.bets) b
            WHERE {clause}
        )
        SELECT variant, chosen,
               count(*) FILTER (WHERE won IN ('true', 'false'))::int AS graded,
               count(*) FILTER (WHERE won = 'true')::int AS won,
               count(*) FILTER (WHERE won IN ('true', 'false') AND price > 1)::int AS priced,
               count(*) FILTER (WHERE won = 'true' AND price > 1)::int AS priced_won,
               avg(price) FILTER (WHERE won IN ('true', 'false') AND price > 1) AS avg_price,
               coalesce(sum(CASE WHEN price > 1 AND won = 'true' THEN price - 1
                                 WHEN price > 1 AND won = 'false' THEN -1 END), 0) AS profit
        FROM bets
        GROUP BY variant, chosen
        ORDER BY variant, chosen DESC
        """  # noqa: S608
    )
    if strategies:
        sql = sql.bindparams(bindparam("strategies", expanding=True))
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    return [
        {
            "variant": str(row["variant"]),
            "chosen": bool(row["chosen"]),
            "graded": int(row["graded"] or 0),
            "won": int(row["won"] or 0),
            "priced": int(row["priced"] or 0),
            "priced_won": int(row["priced_won"] or 0),
            "avg_price": float(row["avg_price"]) if row["avg_price"] is not None else None,
            "profit": float(row["profit"] or 0),
        }
        for row in rows
    ]
