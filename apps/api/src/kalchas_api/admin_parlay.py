"""Admin parlay compose + thermal slip preview (Phase 1–2).

Load today's / tomorrow's / Nightly legs from the watchlist parlay builder,
let the admin drop legs, and render a thermal receipt PNG. Posting to
channels lands in a later phase.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from kalchas_core.watchlist.parlay import MIN_LEGS, STYLES
from kalchas_core.watchlist.parlay_share import (
    STAKE,
    WINDOW_LABEL,
    can_post,
    combined_odds,
    filter_nightly,
    rebuild_orders,
    returns_for,
    select_legs,
    slot_day,
)
from pydantic import BaseModel, Field

from kalchas_api import watchlist as watchlist_api
from kalchas_api.admin_auth import require_admin

router = APIRouter(prefix="/api/admin/parlay", tags=["admin"])

Slot = Literal["today", "tomorrow", "nightly"]
Style = Literal["safer", "balanced", "bolder"]


class PreviewBody(BaseModel):
    slot: Slot = "today"
    style: Style = "balanced"
    day: str | None = None
    match_ids: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required")
    return dsn


def _compose(slot: Slot, style: Style, exclude: list[str] | None = None) -> dict[str, Any]:
    today = watchlist_api.board_today()
    target = slot_day(slot, today=today)
    day = target.isoformat()
    try:
        built = watchlist_api._parlay_for(_dsn(), day)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"parlay unavailable: {exc}") from exc

    legs: list[dict[str, Any]] = list(built.get("legs") or [])
    orders = dict(built.get("order") or {})
    if slot == "nightly":
        legs = filter_nightly(legs)
        orders = rebuild_orders(legs)

    style_key = style if style in STYLES else "balanced"
    style_order = list(orders.get(style_key) or [])
    selected = select_legs(legs, style_order, exclude=exclude or [])
    today_s = today.isoformat()
    if not legs:
        status = "none" if day < today_s else "preparing"
    else:
        status = "ready"

    return {
        "slot": slot,
        "style": style_key,
        "day": day,
        "today": today_s,
        "status": status,
        "window_label": WINDOW_LABEL if slot == "nightly" else None,
        "stake": STAKE,
        "min_legs": MIN_LEGS,
        "legs": legs,
        "order": {s: list(orders.get(s) or []) for s in STYLES},
        "selected": selected,
        "combined": combined_odds(selected) if selected else None,
        "returns": returns_for(selected) if selected else None,
        "can_post": can_post(selected),
        "exclude": list(exclude or []),
    }


@router.get("")
def get_parlay(
    request: Request,
    slot: Slot = "today",
    style: Style = "balanced",
    exclude: str = "",
) -> dict[str, Any]:
    """Compose the admin slip for a slot. ``exclude`` is a comma-separated match id list."""
    require_admin(request)
    dropped = [part for part in exclude.split(",") if part.strip()]
    return _compose(slot, style, dropped)


@router.post("/preview")
def preview_slip(body: PreviewBody, request: Request) -> Response:
    """Thermal slip PNG for the chosen legs (or style order minus exclusions)."""
    require_admin(request)
    from kalchas_bot.parlay_slip import render_parlay_slip

    composed = _compose(body.slot, body.style, body.exclude)
    by_id = {str(leg["match_id"]): leg for leg in composed["legs"]}
    if body.match_ids:
        legs = [by_id[mid] for mid in body.match_ids if mid in by_id]
        # Keep the admin's order for the image, but sort by kick-off for the receipt feel.
        legs.sort(key=lambda leg: (str(leg.get("kickoff") or ""), str(leg["match_id"])))
    else:
        legs = composed["selected"]
    if len(legs) < MIN_LEGS:
        raise HTTPException(status_code=422, detail=f"need at least {MIN_LEGS} legs for a slip")
    png = render_parlay_slip(
        legs,
        slot=body.slot,
        style=body.style,
        day=composed["day"],
    )
    return Response(content=png, media_type="image/png")


@router.get("/meta")
def parlay_meta(request: Request) -> dict[str, Any]:
    """Static labels the admin UI needs (no DB)."""
    require_admin(request)
    return {
        "slots": [
            {"key": "today", "label": "Today"},
            {"key": "tomorrow", "label": "Tomorrow"},
            {"key": "nightly", "label": "Nightly", "window": WINDOW_LABEL, "admin_only": True},
        ],
        "styles": list(STYLES),
        "stake": STAKE,
        "min_legs": MIN_LEGS,
        "timezone_label": "GMT+3",
        "now": datetime.now(UTC).isoformat(),
    }
