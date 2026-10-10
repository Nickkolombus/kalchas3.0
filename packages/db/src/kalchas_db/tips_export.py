"""Persistence for the BFbot /tips.csv feed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

DEFAULT_WINDOW_SECONDS = 1800
MAX_WINDOW_SECONDS = 3600
MAX_ALERT_AGE = timedelta(hours=4)

GET_SETTINGS = text(
    """
    SELECT alert_window_seconds, last_polled_at, last_row_count, poll_count, updated_at
    FROM tips_export_settings
    WHERE id = 1
    """
)

UPSERT_WINDOW = text(
    """
    INSERT INTO tips_export_settings (id, alert_window_seconds, updated_at)
    VALUES (1, :window, NOW())
    ON CONFLICT (id) DO UPDATE SET
        alert_window_seconds = EXCLUDED.alert_window_seconds,
        updated_at = NOW()
    """
)

LIST_OPEN_IN_WINDOW = text(
    """
    SELECT a.match_id, a.strategy_key, a.minute, a.score,
           a.home_team, a.away_team, a.created_at
    FROM alerts a
    LEFT JOIN alert_outcomes o ON o.alert_id = a.id
    WHERE a.created_at >= :cutoff
      AND a.created_at >= :max_age
      AND o.alert_id IS NULL
    ORDER BY a.created_at ASC
    """
)

INSERT_LOG = text(
    """
    INSERT INTO tips_export_log (
        match_id, alert_time, api_home, api_away, event_name,
        market_type, selection_name, correlation_method, fuzzy_applied, strategies
    )
    VALUES (
        :match_id, :alert_time, :api_home, :api_away, :event_name,
        :market_type, :selection_name, :correlation_method, :fuzzy_applied, :strategies
    )
    ON CONFLICT (match_id, alert_time) DO NOTHING
    """
)

LIST_LOG = text(
    """
    SELECT recorded_at, match_id, alert_time, api_home, api_away, event_name,
           market_type, selection_name, correlation_method, fuzzy_applied, strategies
    FROM tips_export_log
    WHERE recorded_at >= :since
    ORDER BY recorded_at DESC
    LIMIT :limit
    """
)

RECORD_POLL = text(
    """
    INSERT INTO tips_export_polls (row_count, user_agent)
    VALUES (:row_count, :user_agent)
    """
)

BUMP_POLL_STATS = text(
    """
    INSERT INTO tips_export_settings (id, last_polled_at, last_row_count, poll_count, updated_at)
    VALUES (1, NOW(), :row_count, 1, NOW())
    ON CONFLICT (id) DO UPDATE SET
        last_polled_at = NOW(),
        last_row_count = EXCLUDED.last_row_count,
        poll_count = tips_export_settings.poll_count + 1
    """
)

TRIM_POLLS = text(
    """
    DELETE FROM tips_export_polls
    WHERE polled_at < NOW() - INTERVAL '7 days'
    """
)

LIST_POLLS = text(
    """
    SELECT polled_at, row_count, user_agent
    FROM tips_export_polls
    ORDER BY polled_at DESC
    LIMIT :limit
    """
)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_settings_sync(dsn: str) -> dict[str, Any]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = conn.execute(GET_SETTINGS).mappings().first()
    if row is None:
        return {
            "alert_window_seconds": DEFAULT_WINDOW_SECONDS,
            "last_polled_at": None,
            "last_row_count": 0,
            "poll_count": 0,
            "updated_at": None,
        }
    return {
        "alert_window_seconds": int(row["alert_window_seconds"] or DEFAULT_WINDOW_SECONDS),
        "last_polled_at": _iso(row["last_polled_at"]),
        "last_row_count": int(row["last_row_count"] or 0),
        "poll_count": int(row["poll_count"] or 0),
        "updated_at": _iso(row["updated_at"]),
    }


def set_window_sync(dsn: str, seconds: int) -> dict[str, Any]:
    window = max(1, min(MAX_WINDOW_SECONDS, int(seconds)))
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(UPSERT_WINDOW, {"window": window})
    return get_settings_sync(dsn)


def list_open_alerts_in_window_sync(dsn: str, *, window_seconds: int) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=max(1, int(window_seconds)))
    max_age = now - MAX_ALERT_AGE
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(
            LIST_OPEN_IN_WINDOW, {"cutoff": cutoff, "max_age": max_age}
        ).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["created_at"] = _iso(item.get("created_at"))
        out.append(item)
    return out


def record_log_rows_sync(dsn: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        for row in rows:
            conn.execute(
                INSERT_LOG,
                {
                    "match_id": row["match_id"],
                    "alert_time": row["alert_time"],
                    "api_home": row.get("api_home") or "",
                    "api_away": row.get("api_away") or "",
                    "event_name": row["event_name"],
                    "market_type": row.get("market_type") or "",
                    "selection_name": row.get("selection_name") or "",
                    "correlation_method": row.get("correlation_method") or "",
                    "fuzzy_applied": row.get("fuzzy_applied"),
                    "strategies": ",".join(str(s) for s in (row.get("strategies") or [])),
                },
            )


def list_log_sync(dsn: str, *, days: int = 1, limit: int = 500) -> list[dict[str, Any]]:
    days = max(1, min(int(days), 30))
    limit = max(1, min(int(limit), 2000))
    since = datetime.now(UTC) - timedelta(days=days)
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_LOG, {"since": since, "limit": limit}).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["recorded_at"] = _iso(item.get("recorded_at"))
        strat = item.get("strategies") or ""
        item["strategies"] = [s.strip() for s in str(strat).split(",") if s.strip()]
        out.append(item)
    return out


def record_poll_sync(dsn: str, *, row_count: int, user_agent: str | None) -> None:
    eng = sync_engine(dsn)
    ua = (user_agent or "")[:300]
    with eng.begin() as conn:
        conn.execute(RECORD_POLL, {"row_count": int(row_count), "user_agent": ua})
        conn.execute(BUMP_POLL_STATS, {"row_count": int(row_count)})
        conn.execute(TRIM_POLLS)


def list_polls_sync(dsn: str, *, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_POLLS, {"limit": limit}).mappings().all()
    return [
        {
            "polled_at": _iso(row["polled_at"]),
            "row_count": int(row["row_count"] or 0),
            "user_agent": row["user_agent"] or "",
        }
        for row in rows
    ]
