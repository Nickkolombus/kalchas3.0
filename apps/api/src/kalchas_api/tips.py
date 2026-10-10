"""BFbot tips.csv: same 2.2 columns, served from open alerts."""

from __future__ import annotations

import csv
import io
import logging
import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from kalchas_api.admin_auth import require_admin

logger = logging.getLogger("kalchas.api.tips")

CSV_HEADER = ["Provider", "EventName", "MarketType", "SelectionName", "BetType"]
PROVIDER = "Kalchas"
BET_TYPE = "BACK"
CORRELATION_PASSTHROUGH = "passthrough"

public_router = APIRouter(tags=["tips"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin-tips"])


class TipsWindowIn(BaseModel):
    alert_window_seconds: int = Field(ge=1, le=3600)


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def _require_dsn() -> str:
    dsn = _dsn()
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required")
    return dsn


def _clean_name(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or "")).strip()
    return text


def _int_token(part: str) -> int:
    digits = "".join(ch for ch in part if ch.isdigit())
    return int(digits) if digits else 0


def _goals_from_score(score: Any) -> tuple[int, int]:
    text = str(score or "0-0").replace("–", "-").replace("—", "-")
    parts = [p.strip() for p in text.split("-")]
    home = _int_token(parts[0]) if parts else 0
    away = _int_token(parts[1]) if len(parts) > 1 else 0
    return home, away


def market_for(score: Any, minute: int) -> tuple[str, str]:
    """Over current total + 0.5. First-half clock uses FIRST_HALF_GOALS_xx."""
    home, away = _goals_from_score(score)
    line = home + away + 0.5
    market_value = f"{int(line * 10):02d}"
    selection = f"Over {line:.1f} Goals".replace(".0", "")
    if int(minute) <= 45:
        return f"FIRST_HALF_GOALS_{market_value}", selection
    return f"OVER_UNDER_{market_value}", selection


def event_name_for(home: str, away: str) -> str:
    return f"{home} v {away}"


def rows_from_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One CSV row per match: earliest open alert in the window."""
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for alert in alerts:
        match_id = str(alert.get("match_id") or "")
        if not match_id:
            continue
        home = _clean_name(alert.get("home_team"))
        away = _clean_name(alert.get("away_team"))
        strategy = str(alert.get("strategy_key") or "")
        if match_id not in grouped:
            minute = int(alert.get("minute") or 0)
            score = str(alert.get("score") or "0-0")
            market, selection = market_for(score, minute)
            grouped[match_id] = {
                "match_id": match_id,
                "alert_time": str(alert.get("created_at") or ""),
                "api_home": home,
                "api_away": away,
                "event_name": event_name_for(home, away),
                "market_type": market,
                "selection_name": selection,
                "correlation_method": CORRELATION_PASSTHROUGH,
                "fuzzy_applied": None,
                "strategies": [strategy] if strategy else [],
                "minute": minute,
                "score": score,
            }
            order.append(match_id)
        elif strategy and strategy not in grouped[match_id]["strategies"]:
            grouped[match_id]["strategies"].append(strategy)
    return [grouped[key] for key in order]


def render_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(
            [
                PROVIDER,
                row["event_name"],
                row["market_type"],
                row["selection_name"],
                BET_TYPE,
            ]
        )
    return buf.getvalue()


def _live_rows(dsn: str, window: int) -> list[dict[str, Any]]:
    from kalchas_db.tips_export import list_open_alerts_in_window_sync

    alerts = list_open_alerts_in_window_sync(dsn, window_seconds=window)
    return rows_from_alerts(alerts)


def csv_response(body: str) -> Response:
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Access-Control-Allow-Origin": "*",
        },
    )


@public_router.get("/tips.csv")
def tips_csv(request: Request) -> Response:
    """Public BFbot poll endpoint. Empty header-only CSV when nothing is live."""
    from kalchas_db.tips_export import (
        DEFAULT_WINDOW_SECONDS,
        get_settings_sync,
        record_log_rows_sync,
        record_poll_sync,
    )

    rows: list[dict[str, Any]] = []
    dsn = _dsn()
    if dsn:
        try:
            settings = get_settings_sync(dsn)
            window = int(settings.get("alert_window_seconds") or DEFAULT_WINDOW_SECONDS)
            rows = _live_rows(dsn, window)
            try:
                record_log_rows_sync(dsn, rows)
            except Exception:
                logger.exception("tips export log write failed")
            try:
                record_poll_sync(
                    dsn,
                    row_count=len(rows),
                    user_agent=request.headers.get("user-agent"),
                )
            except Exception:
                logger.exception("tips poll log write failed")
        except Exception:
            logger.exception("tips.csv build failed")
            rows = []
    return csv_response(render_csv(rows))


@admin_router.get("/tips")
def admin_tips(
    request: Request,
    days: int = Query(1, ge=1, le=30),
) -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.tips_export import (
        DEFAULT_WINDOW_SECONDS,
        get_settings_sync,
        list_log_sync,
        list_polls_sync,
    )

    dsn = _require_dsn()
    settings = get_settings_sync(dsn)
    window = int(settings.get("alert_window_seconds") or DEFAULT_WINDOW_SECONDS)
    return {
        "settings": settings,
        "feed_path": "/tips.csv",
        "live": _live_rows(dsn, window),
        "history": list_log_sync(dsn, days=days, limit=500),
        "polls": list_polls_sync(dsn, limit=50),
    }


@admin_router.put("/tips/settings")
def admin_tips_settings(request: Request, body: TipsWindowIn) -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.tips_export import set_window_sync

    settings = set_window_sync(_require_dsn(), body.alert_window_seconds)
    return {"ok": True, "settings": settings}
