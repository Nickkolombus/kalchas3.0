"""Admin parlay: compose like the public page, evaluate with Claude, post.

Same builder as /parlay (Safer / Balanced / Bolder + leg count), plus admin-only
Nightly, per-leg Remove, thermal slip, Claude stress-test, and channel fan-out.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from kalchas_core.watchlist.parlay import MAX_LEGS, MIN_LEGS, STYLES
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

STYLE_BLURBS: dict[str, str] = {
    "safer": "Shortest prices first, and only legs that came in at least 7 times in 10 recently.",
    "balanced": "The strongest patterns of the day, in the order the watchlist ranks them.",
    "bolder": "Legs whose recent record beats the price by the most. Longer odds, less likely to all come in.",
}

STYLE_NATURE: dict[str, str] = {
    "safer": "A cautious slip: short prices on picks that have come in at least 7 times in 10 lately.",
    "balanced": "A middle-ground slip: the day's strongest patterns, neither the safest nor the longest odds.",
    "bolder": "A riskier slip: longer odds on picks whose recent form beats the price. Less likely to all land.",
}

CHANNEL_KEYS = ("x", "telegram_free", "telegram_paid", "discord_free", "discord_paid")


class PreviewBody(BaseModel):
    slot: Slot = "today"
    style: Style = "balanced"
    legs: int | None = None
    match_ids: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class EvaluateBody(BaseModel):
    slot: Slot = "today"
    style: Style = "balanced"
    legs: int | None = None
    match_ids: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class PostBody(BaseModel):
    slot: Slot = "today"
    style: Style = "balanced"
    legs: int | None = None
    match_ids: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    channels: dict[str, bool] = Field(default_factory=dict)
    caption: str = ""
    x_text: str = ""
    autopost: bool = True


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required")
    return dsn


def _one_in(odds: float) -> str:
    if odds < 2:
        return "better than even"
    n = round(odds)
    if n >= 10_000:
        return f"about 1 in {round(n / 1000):,}000"
    if n >= 1000:
        return f"about 1 in {round(n / 100) * 100:,}"
    return f"about 1 in {n}"


def _compose(
    slot: Slot,
    style: Style,
    exclude: list[str] | None = None,
    wanted: int | None = None,
) -> dict[str, Any]:
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
    most = len(style_order)
    n = wanted
    if n is None:
        n = min(5, most) if most else 0
    n = max(min(n, most), min(MIN_LEGS, most)) if most else 0
    selected = select_legs(legs, style_order, exclude=exclude or [], wanted=n or None)
    # If excludes shrink below floor, keep what remains (UI blocks post).
    today_s = today.isoformat()
    if not legs:
        status = "none" if day < today_s else "preparing"
    else:
        status = "ready"

    looks = sum(1 for leg in selected if leg.get("watch") == "look")
    combined = combined_odds(selected) if selected else None
    explanation_parts = [
        STYLE_BLURBS.get(style_key, ""),
        (
            f"Same builder as the public /parlay page: one priced leg per match, "
            f"ordered by {style_key}, then the first {len(selected)} after your removals."
            if selected
            else ""
        ),
    ]
    if combined is not None and selected:
        explanation_parts.append(
            f"All {len(selected)} have to land. At these prices bookmakers rate that {_one_in(combined)}."
        )
    if looks:
        explanation_parts.append(
            f"{looks} {'leg' if looks == 1 else 'legs'} from Worth a look, added to reach {len(selected)}."
        )
    if slot == "nightly":
        explanation_parts.append(f"Nightly window {WINDOW_LABEL}, admin-only.")

    return {
        "slot": slot,
        "style": style_key,
        "style_blurb": STYLE_BLURBS.get(style_key, ""),
        "day": day,
        "today": today_s,
        "status": status,
        "window_label": WINDOW_LABEL if slot == "nightly" else None,
        "stake": STAKE,
        "min_legs": MIN_LEGS,
        "max_legs": MAX_LEGS,
        "presets": [p for p in (3, 5, 8, 12, 18) if p <= max(most, MIN_LEGS) or p <= most],
        "available": most,
        "wanted": n,
        "legs": legs,
        "order": {s: list(orders.get(s) or []) for s in STYLES},
        "selected": selected,
        "combined": combined,
        "returns": returns_for(selected) if selected else None,
        "can_post": can_post(selected),
        "exclude": list(exclude or []),
        "explanation": " ".join(p for p in explanation_parts if p).strip(),
        "claude_ready": bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip()),
    }


def _resolve_legs(body_match_ids: list[str], composed: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {str(leg["match_id"]): leg for leg in composed["legs"]}
    if body_match_ids:
        legs = [by_id[mid] for mid in body_match_ids if mid in by_id]
        legs.sort(key=lambda leg: (str(leg.get("kickoff") or ""), str(leg["match_id"])))
        return legs
    return list(composed["selected"])


def _default_caption(composed: dict[str, Any], legs: list[dict[str, Any]]) -> str:
    slot = composed["slot"]
    style = composed["style"]
    combined = combined_odds(legs) if legs else 0
    slot_word = (
        "Nightly" if slot == "nightly" else "Tomorrow's" if slot == "tomorrow" else "Today's"
    )
    lines = [
        f"{slot_word} Kalchas parlay",
        STYLE_NATURE.get(style, STYLE_NATURE["balanced"]),
        "",
        f"{len(legs)} legs · combined {combined:.2f}",
        f"A 10 stake returns {returns_for(legs):.2f}",
    ]
    if slot == "nightly":
        lines.append(WINDOW_LABEL)
    lines.extend(["", "kalchas.live", "For research/enthusiast purposes only"])
    return "\n".join(lines)


@router.get("")
def get_parlay(
    request: Request,
    slot: Slot = "today",
    style: Style = "balanced",
    legs: int | None = None,
    exclude: str = "",
) -> dict[str, Any]:
    """Compose the admin slip for a slot (same builder as public /parlay)."""
    require_admin(request)
    dropped = [part for part in exclude.split(",") if part.strip()]
    return _compose(slot, style, dropped, wanted=legs)


@router.post("/preview")
def preview_slip(body: PreviewBody, request: Request) -> Response:
    """Thermal slip PNG for the chosen legs."""
    require_admin(request)
    from kalchas_bot.parlay_slip import render_parlay_slip

    composed = _compose(body.slot, body.style, body.exclude, wanted=body.legs)
    legs = _resolve_legs(body.match_ids, composed)
    if len(legs) < MIN_LEGS:
        raise HTTPException(status_code=422, detail=f"need at least {MIN_LEGS} legs for a slip")
    png = render_parlay_slip(legs, slot=body.slot, style=body.style, day=composed["day"])
    return Response(content=png, media_type="image/png")


@router.post("/evaluate")
def evaluate_slip(body: EvaluateBody, request: Request) -> dict[str, Any]:
    """Claude stress-test: weakest leg + optional swap. Does not change the slip."""
    require_admin(request)
    from kalchas_api.parlay_claude import evaluate

    composed = _compose(body.slot, body.style, body.exclude, wanted=body.legs)
    legs = _resolve_legs(body.match_ids, composed)
    if len(legs) < MIN_LEGS:
        raise HTTPException(status_code=422, detail=f"need at least {MIN_LEGS} legs")
    selected_ids = {str(leg["match_id"]) for leg in legs}
    unused = [leg for leg in composed["legs"] if str(leg["match_id"]) not in selected_ids]
    result = evaluate(
        slot=body.slot,
        style=body.style,
        day=composed["day"],
        selected=legs,
        unused=unused,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=str(result.get("error") or "Claude failed"))
    return result


@router.post("/post")
def post_slip(body: PostBody, request: Request) -> dict[str, Any]:
    """Render the thermal slip and post it to the chosen channels."""
    require_admin(request)
    from kalchas_bot.parlay_slip import render_parlay_slip

    from kalchas_api.parlay_post import fanout

    composed = _compose(body.slot, body.style, body.exclude, wanted=body.legs)
    legs = _resolve_legs(body.match_ids, composed)
    if len(legs) < MIN_LEGS:
        raise HTTPException(status_code=422, detail=f"need at least {MIN_LEGS} legs")
    channels = {key: bool(body.channels.get(key)) for key in CHANNEL_KEYS}
    if not any(channels.values()):
        raise HTTPException(status_code=422, detail="pick at least one channel")

    caption = (body.caption or "").strip() or _default_caption(composed, legs)
    x_text = (body.x_text or "").strip() or caption[:280]
    png = render_parlay_slip(legs, slot=body.slot, style=body.style, day=composed["day"])

    discord = None
    try:
        from kalchas_db.discord_settings import get_discord_settings

        discord = get_discord_settings(_dsn())
    except Exception:  # noqa: BLE001 — missing table / bad DSN must not block a post
        discord = None

    post_log = fanout(
        png,
        caption=caption,
        x_text=x_text,
        channels=channels,
        discord_settings=discord,
    )
    ok_any = any(bool((entry or {}).get("ok")) for entry in post_log.values())
    return {
        "ok": ok_any,
        "post_log": post_log,
        "autopost": body.autopost,
        "day": composed["day"],
        "slot": body.slot,
        "style": body.style,
        "legs": [str(leg["match_id"]) for leg in legs],
        "caption": caption,
    }


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
        "styles": [{"key": s, "label": s.capitalize(), "blurb": STYLE_BLURBS[s]} for s in STYLES],
        "stake": STAKE,
        "min_legs": MIN_LEGS,
        "max_legs": MAX_LEGS,
        "presets": [3, 5, 8, 12, 18],
        "timezone_label": "GMT+3",
        "channels": list(CHANNEL_KEYS),
        "claude_ready": bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip()),
        "now": datetime.now(UTC).isoformat(),
    }
