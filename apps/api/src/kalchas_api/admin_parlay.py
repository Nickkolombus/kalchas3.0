"""Admin parlay: build a slip like the public /parlay page, check it, post it.

The page gets one payload per slot (every leg on offer and each style's
order, exactly what the public page gets) and builds the slip in the browser,
so every control is instant and the selection logic is the public one.

The server only renders, asks Claude, and saves. A slip is saved exactly as
the admin saw it: if a price or market moved since, saving is refused with
what changed. Posting, settling and the result reply are the bot's job
(``kalchas_bot.parlay_job``), so this request never waits on a channel.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from kalchas_core.watchlist.parlay import MAX_LEGS, MIN_LEGS, STYLES
from kalchas_core.watchlist.parlay_share import (
    STAKE,
    WINDOW_LABEL,
    filter_nightly,
    rebuild_orders,
    slot_day,
)
from kalchas_core.watchlist.parlay_slips import CHOICES, marks, snapshot, verdict
from pydantic import BaseModel, Field

from kalchas_api import watchlist as watchlist_api
from kalchas_api.admin_auth import require_admin

router = APIRouter(prefix="/api/admin/parlay", tags=["admin"])

Slot = Literal["today", "tomorrow", "nightly"]
Style = Literal["safer", "balanced", "bolder"]

CHANNEL_KEYS = ("x", "telegram_free", "telegram_paid", "discord_free", "discord_paid")

STYLE_NATURE: dict[str, str] = {
    "safer": "A cautious slip: short prices on picks that have come in at least 7 times in 10 lately.",
    "balanced": "A middle-ground slip: the day's strongest patterns, neither the safest nor the longest odds.",
    "bolder": "A riskier slip: longer odds on picks whose recent form beats the price. Less likely to all land.",
}


class LegRef(BaseModel):
    """One leg as the admin saw it. The price is checked before anything is saved."""

    match_id: str
    market: str
    price: float


class SlipBody(BaseModel):
    slot: Slot = "today"
    style: Style = "balanced"
    legs: list[LegRef] = Field(default_factory=list)


class EvaluateBody(SlipBody):
    pass


class SaveBody(SlipBody):
    caption: str = ""
    x_text: str = ""
    channels: dict[str, bool] = Field(default_factory=dict)
    autopost: bool = True


class DecideBody(BaseModel):
    match_id: str
    outcome: Literal["landed", "missed", "void"]


class ReplyBody(BaseModel):
    action: Literal["post", "skip", "retry"]


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required")
    return dsn


# ---------------------------------------------------------------- the day


def day_for(slot: Slot) -> dict[str, Any]:
    """Everything the slot can use: the public /parlay payload, Nightly-filtered."""
    today = watchlist_api.board_today()
    target = slot_day(slot, today=today)
    iso = target.isoformat()
    try:
        built = watchlist_api._parlay_for(_dsn(), iso)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"parlay unavailable: {exc}") from exc
    legs = list(built.get("legs") or [])
    order = {s: list((built.get("order") or {}).get(s) or []) for s in STYLES}
    unpriced = list(built.get("unpriced") or [])
    if slot == "nightly":
        legs = filter_nightly(legs)
        order = rebuild_orders(legs)
        unpriced = []  # no kick-off on those rows, so they can't be placed in the window
    if built:
        status = "ready"
    else:
        status = "none" if iso < today.isoformat() else "preparing"
    return {
        "slot": slot,
        "day": iso,
        "today": today.isoformat(),
        "status": status,
        "window_label": WINDOW_LABEL if slot == "nightly" else None,
        "legs": legs,
        "order": order,
        "unpriced": unpriced,
        "stake": STAKE,
        "min_legs": MIN_LEGS,
        "max_legs": MAX_LEGS,
        "claude_ready": bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip()),
    }


def take(slot: Slot, refs: list[LegRef]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The legs the admin picked, from today's data; 409 if any changed since."""
    day = day_for(slot)
    by_id = {str(leg["match_id"]): leg for leg in day["legs"]}
    picked: list[dict[str, Any]] = []
    changed: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.match_id in seen:
            continue
        seen.add(ref.match_id)
        leg = by_id.get(ref.match_id)
        if leg is None:
            changed.append(f"{ref.match_id}: no longer on the list")
        elif leg["market"] != ref.market:
            changed.append(f"{_name(leg)}: the leg is now {leg['label']}")
        elif round(float(leg["price"]), 2) != round(ref.price, 2):
            changed.append(f"{_name(leg)}: price {ref.price:.2f} is now {float(leg['price']):.2f}")
        else:
            picked.append(leg)
    if changed:
        raise HTTPException(
            status_code=409,
            detail={"message": "The list changed since you built this slip.", "changes": changed},
        )
    if not MIN_LEGS <= len(picked) <= MAX_LEGS:
        raise HTTPException(
            status_code=422, detail=f"a slip needs {MIN_LEGS} to {MAX_LEGS} legs, not {len(picked)}"
        )
    picked.sort(key=lambda leg: (str(leg.get("kickoff") or ""), str(leg["match_id"])))
    return day, picked


def _name(leg: dict[str, Any]) -> str:
    return f"{(leg.get('home') or {}).get('name', '')} v {(leg.get('away') or {}).get('name', '')}"


def default_caption(slot: str, style: str, legs: list[dict[str, Any]]) -> str:
    combined = 1.0
    for leg in legs:
        combined *= float(leg["price"])
    word = "Nightly" if slot == "nightly" else "Tomorrow's" if slot == "tomorrow" else "Today's"
    lines = [
        f"{word} Kalchas parlay",
        STYLE_NATURE.get(style, STYLE_NATURE["balanced"]),
        "",
        f"{len(legs)} legs · combined {combined:.2f}",
        f"A {STAKE:.0f} stake returns {STAKE * combined:.2f}",
    ]
    if slot == "nightly":
        lines.append(WINDOW_LABEL)
    lines += ["", "kalchas.live", "For research & football enthusiast purposes only"]
    return "\n".join(lines)


# ---------------------------------------------------------------- endpoints


@router.get("/day")
def get_day(request: Request, slot: Slot = "today") -> dict[str, Any]:
    """Every leg the slot can use and each style's order, like GET /api/watchlist/parlay."""
    require_admin(request)
    return day_for(slot)


@router.post("/preview")
def preview(body: SlipBody, request: Request) -> Response:
    """The thermal slip PNG for exactly these legs."""
    require_admin(request)
    from kalchas_bot.parlay_slip import render_parlay_slip

    day, legs = take(body.slot, body.legs)
    png = render_parlay_slip(legs, slot=body.slot, style=body.style, day=day["day"])
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/caption")
def caption(body: SlipBody, request: Request) -> dict[str, str]:
    require_admin(request)
    _, legs = take(body.slot, body.legs)
    return {"caption": default_caption(body.slot, body.style, legs)}


@router.post("/evaluate")
def evaluate_slip(body: EvaluateBody, request: Request) -> dict[str, Any]:
    """Claude's read: weakest leg and swap ideas from the unused legs. Changes nothing."""
    require_admin(request)
    from kalchas_api.parlay_claude import evaluate

    day, legs = take(body.slot, body.legs)
    chosen = {str(leg["match_id"]) for leg in legs}
    rank = {mid: i for i, mid in enumerate(day["order"].get(body.style) or [])}
    unused = sorted(
        (leg for leg in day["legs"] if str(leg["match_id"]) not in chosen),
        key=lambda leg: (rank.get(str(leg["match_id"]), len(rank)), -float(leg.get("score") or 0)),
    )
    result = evaluate(
        slot=body.slot, style=body.style, day=day["day"], selected=legs, unused=unused
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=str(result.get("error") or "Claude failed"))
    return result


@router.post("/slips")
def save_slip(body: SaveBody, request: Request) -> dict[str, Any]:
    """Save the slip as previewed; the bot posts it within a minute."""
    require_admin(request)
    from kalchas_db.parlay_slips import insert_slip_sync

    channels = {key: bool(body.channels.get(key)) for key in CHANNEL_KEYS}
    if not any(channels.values()):
        raise HTTPException(status_code=422, detail="pick at least one channel")
    day, legs = take(body.slot, body.legs)
    text = body.caption.strip() or default_caption(body.slot, body.style, legs)
    row = insert_slip_sync(
        _dsn(),
        day=date.fromisoformat(day["day"]),
        slot=body.slot,
        style=body.style,
        legs=[snapshot(leg) for leg in legs],
        caption=text,
        x_text=(body.x_text.strip() or text)[:280],
        channels=channels,
        autopost=body.autopost,
    )
    return _out(row)


@router.get("/slips")
def list_slips(request: Request, limit: int = 30) -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.parlay_slips import list_slips_sync

    return {"slips": [_out(row) for row in list_slips_sync(_dsn(), min(max(limit, 1), 100))]}


@router.get("/slips/{slip_id}")
def get_slip(slip_id: int, request: Request) -> dict[str, Any]:
    require_admin(request)
    return _out(_load(slip_id))


@router.get("/slips/{slip_id}/image")
def slip_image(slip_id: int, request: Request) -> Response:
    """The slip as posted, marked up by hand once legs are decided."""
    require_admin(request)
    from kalchas_bot.parlay_slip import render_parlay_slip

    row = _load(slip_id)
    png = render_parlay_slip(
        row["legs"],
        slot=row["slot"],
        style=row["style"],
        day=str(row["day"]),
        settled=marks(row.get("outcomes") or {}) or None,
        seed=f"parlay-{row['id']}",
    )
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/slips/{slip_id}/decide")
def decide(slip_id: int, body: DecideBody, request: Request) -> dict[str, Any]:
    """The admin's call on a leg the result can't settle (same as the Telegram buttons)."""
    require_admin(request)
    from kalchas_db.parlay_slips import decide_leg_sync

    row = _load(slip_id)
    entry = (row.get("outcomes") or {}).get(body.match_id) or {}
    allowed = CHOICES.get(str(entry.get("state") or ""), ())
    if body.outcome not in allowed:
        raise HTTPException(status_code=409, detail="that leg isn't waiting for this answer")
    saved = decide_leg_sync(_dsn(), slip_id, body.match_id, body.outcome, by="admin")
    if saved is None:
        raise HTTPException(status_code=409, detail="this slip no longer takes answers")
    return _out(saved)


@router.post("/slips/{slip_id}/reply")
def reply(slip_id: int, body: ReplyBody, request: Request) -> dict[str, Any]:
    """Post the result reply (or skip it, or retry the channels that failed)."""
    require_admin(request)
    from kalchas_db.parlay_slips import set_reply_sync

    if not set_reply_sync(_dsn(), slip_id, body.action):
        raise HTTPException(status_code=409, detail="the result isn't waiting for that")
    return _out(_load(slip_id))


@router.post("/slips/{slip_id}/retry")
def retry(slip_id: int, request: Request) -> dict[str, Any]:
    """Post a slip again where every channel failed."""
    require_admin(request)
    from kalchas_db.parlay_slips import retry_post_sync

    if not retry_post_sync(_dsn(), slip_id):
        raise HTTPException(status_code=409, detail="only a failed slip can be retried")
    return _out(_load(slip_id))


def _load(slip_id: int) -> dict[str, Any]:
    from kalchas_db.parlay_slips import get_slip_sync

    row = get_slip_sync(_dsn(), slip_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such slip")
    return row


def _out(row: dict[str, Any]) -> dict[str, Any]:
    v = verdict(row["legs"], row.get("outcomes") or {})
    out = {
        key: (value.isoformat() if hasattr(value, "isoformat") else value)
        for key, value in row.items()
    }
    out["verdict"] = v
    return out
