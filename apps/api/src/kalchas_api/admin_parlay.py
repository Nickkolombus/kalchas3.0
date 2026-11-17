"""Admin parlay: build a slip like the public /parlay page, check it, post it.

The page gets one payload per slot (every leg on offer and each style's
order, exactly what the public page gets) and builds the slip in the browser,
so every control is instant and the selection logic is the public one.

The server only renders, asks Claude, and saves. A slip is saved exactly as
the admin saw it: if a price or market moved since, saving is refused with
what changed. Posting, settling and the result reply are the bot's job
(``kalchas_bot.parlay_job``), so this request never waits on a channel.

A second kind of slip, ``any``, takes each match's strongest pattern whatever
the market. We hold a price for only some of those, so the admin types the
odds: a typed price is taken as given, and every leg needs one to be posted.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from kalchas_core.watchlist.parlay import MAX_LEGS, MIN_LEGS, STYLES, picks_order
from kalchas_core.watchlist.parlay_share import (
    STAKE,
    filter_window,
    nightly_window,
    rebuild_orders,
    slot_day,
    window_label,
)
from kalchas_core.watchlist.parlay_slips import CHOICES, marks, snapshot, verdict
from pydantic import BaseModel, Field

from kalchas_api import watchlist as watchlist_api
from kalchas_api.admin_auth import require_admin

router = APIRouter(prefix="/api/admin/parlay", tags=["admin"])

Slot = Literal["today", "tomorrow", "nightly"]
Style = Literal["safer", "balanced", "bolder"]
# priced: the public builder's legs, at the prices we hold. any: each match's
# strongest pattern of any market, at the odds the admin types.
Kind = Literal["priced", "any"]
# What an any-market slip is saved as, where a priced slip keeps its style.
ANY_STYLE = "picks"
ANY_NATURE = "The strongest pattern in each match, whatever the market."
MAX_TYPED_ODDS = 1000.0
# The longest kick-off window a slip can be built from.
MAX_WINDOW = timedelta(days=3)
# Claude gets the style as a fact; this tells it what is different about these legs.
ANY_STYLE_FOR_CLAUDE = (
    "any market: each match's strongest pattern, whatever the market. A null price means "
    "the odds are not typed in yet; recent_games 0 means no recent count is held."
)

CHANNEL_KEYS = ("x", "telegram_free", "telegram_paid", "discord_free", "discord_paid")

STYLE_NATURE: dict[str, str] = {
    "safer": "A cautious slip: short prices on picks that have come in at least 7 times in 10 lately.",
    "balanced": "A middle-ground slip: the day's strongest patterns, neither the safest nor the longest odds.",
    "bolder": "A riskier slip: longer odds on picks whose recent form beats the price. Less likely to all land.",
}


class LegRef(BaseModel):
    """One leg as the admin saw it. The price is checked before anything is
    saved; on an any-market slip it is the odds the admin typed, if any yet."""

    match_id: str
    market: str
    price: float | None = None


class SlipBody(BaseModel):
    slot: Slot = "today"
    style: Style = "balanced"
    kind: Kind = "priced"
    # The kick-off window the admin set, if any; the same one the list came with.
    start: datetime | None = None
    end: datetime | None = None
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


Channel = Literal["x", "telegram_free", "telegram_paid", "discord_free", "discord_paid"]


class ReplyBody(BaseModel):
    action: Literal["post", "skip", "retry"]


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required")
    return dsn


# ---------------------------------------------------------------- the day


def slot_window(slot: Slot, target: date) -> tuple[datetime, datetime]:
    """The kick-offs a slot takes when the admin sets no window: the board's
    whole day for Today and Tomorrow, 00:00–07:00 GMT+3 for Nightly."""
    if slot == "nightly":
        return nightly_window(target)
    start = datetime.combine(target, time(0), tzinfo=watchlist_api.board_zone())
    return start, start + timedelta(days=1)


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=watchlist_api.board_zone())


def _built(iso: str) -> dict[str, Any]:
    try:
        return watchlist_api._parlay_for(_dsn(), iso)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"parlay unavailable: {exc}") from exc


def day_for(
    slot: Slot,
    kind: Kind = "priced",
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Everything the slot can use: the public /parlay payload, cut to a window.

    With no ``start``/``end`` Today and Tomorrow are exactly the public page;
    Nightly keeps 00:00–07:00 GMT+3. Either end the admin sets replaces the
    slot's own; the window may run past midnight (up to three days), and then
    every day it touches is loaded. Once a window cuts the list, each style's
    order is rebuilt from what is left. For ``any`` the legs are the any-market
    picks (``price`` may be None) and every style has the one order they come in.
    """
    today = watchlist_api.board_today()
    target = slot_day(slot, today=today)
    iso = target.isoformat()
    own_start, own_end = slot_window(slot, target)
    custom = start is not None or end is not None
    lo = _aware(start) if start is not None else own_start
    hi = _aware(end) if end is not None else own_end
    if hi <= lo:
        raise HTTPException(status_code=422, detail="the window has to end after it starts")
    if hi - lo > MAX_WINDOW:
        raise HTTPException(status_code=422, detail="the window can be at most 3 days long")

    zone = watchlist_api.board_zone()
    first = lo.astimezone(zone).date()
    last = (hi - timedelta(microseconds=1)).astimezone(zone).date()
    days = (
        [first + timedelta(days=i) for i in range((last - first).days + 1)] if custom else [target]
    )
    built_by_day = {d.isoformat(): _built(d.isoformat()) for d in days}
    built = built_by_day.get(iso) or {}

    def gather(key: str) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for got in built_by_day.values():
            for row in got.get(key) or []:
                seen.setdefault(str(row["match_id"]), row)
        return list(seen.values())

    windowed = custom or slot == "nightly"
    legs = gather("legs")
    order = {s: list((built.get("order") or {}).get(s) or []) for s in STYLES}
    # Strong matches with no priced pattern carry no kick-off, so they can't be
    # placed in a window: shown for the slot's own day only, never for Nightly.
    unpriced = list(built.get("unpriced") or []) if slot != "nightly" else []
    if kind == "any":
        legs = gather("picks")
        if windowed:
            legs = filter_window(legs, lo, hi)
        order = dict.fromkeys(STYLES, picks_order(legs))
        unpriced = []
    elif windowed:
        legs = filter_window(legs, lo, hi)
        order = rebuild_orders(legs)
    if any(built_by_day.values()):
        status = "ready"
    else:
        status = "none" if last.isoformat() < today.isoformat() else "preparing"
    return {
        "slot": slot,
        "kind": kind,
        "day": iso,
        "today": today.isoformat(),
        "status": status,
        "window_label": window_label(lo, hi) if windowed else None,
        "window": {
            "start": lo.isoformat(),
            "end": hi.isoformat(),
            "slot_start": own_start.isoformat(),
            "slot_end": own_end.isoformat(),
            "custom": custom,
        },
        "legs": legs,
        "order": order,
        "unpriced": unpriced,
        "stake": STAKE,
        "min_legs": MIN_LEGS,
        "max_legs": MAX_LEGS,
        "claude_ready": bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip()),
    }


def take(body: SlipBody, *, need_odds: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The legs the admin picked, from today's data; 409 if any changed since.

    On an any-market slip the leg takes the odds the admin typed. Every leg
    needs them to be drawn or saved (``need_odds``); Claude's read does not.
    """
    kind, refs = body.kind, body.legs
    day = day_for(body.slot, kind, body.start, body.end)
    by_id = {str(leg["match_id"]): leg for leg in day["legs"]}
    picked: list[dict[str, Any]] = []
    changed: list[str] = []
    no_odds: list[str] = []
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
        elif kind == "any":
            if ref.price is not None and 1 < ref.price <= MAX_TYPED_ODDS:
                picked.append({**leg, "price": round(ref.price, 2)})
            else:
                no_odds.append(_name(leg))
                picked.append({**leg, "price": None})
        elif ref.price is None:
            changed.append(f"{_name(leg)}: no price was sent, it is {float(leg['price']):.2f}")
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
    if no_odds and need_odds:
        raise HTTPException(
            status_code=422,
            detail="Every leg needs odds above 1.00. Still missing: " + "; ".join(no_odds),
        )
    picked.sort(key=lambda leg: (str(leg.get("kickoff") or ""), str(leg["match_id"])))
    return day, picked


def _name(leg: dict[str, Any]) -> str:
    return f"{(leg.get('home') or {}).get('name', '')} v {(leg.get('away') or {}).get('name', '')}"


def default_caption(
    slot: str,
    style: str,
    legs: list[dict[str, Any]],
    kind: str = "priced",
    label: str | None = None,
) -> str:
    combined = 1.0
    for leg in legs:
        combined *= float(leg["price"])
    word = "Nightly" if slot == "nightly" else "Tomorrow's" if slot == "tomorrow" else "Today's"
    lines = [
        f"{word} Kalchas parlay",
        ANY_NATURE if kind == "any" else STYLE_NATURE.get(style, STYLE_NATURE["balanced"]),
        "",
        f"{len(legs)} legs · combined {combined:.2f}",
        f"A {STAKE:.0f} stake returns {STAKE * combined:.2f}",
    ]
    if slot == "nightly" and label:
        lines.append(label)
    lines += ["", "kalchas.live", "For research & football enthusiast purposes only"]
    return "\n".join(lines)


# ---------------------------------------------------------------- endpoints


@router.get("/day")
def get_day(
    request: Request,
    slot: Slot = "today",
    kind: Kind = "priced",
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Every leg the slot can use and each style's order, like GET /api/watchlist/parlay,
    cut to kick-offs from ``start`` up to ``end`` where the admin set them."""
    require_admin(request)
    return day_for(slot, kind, start, end)


@router.post("/preview")
def preview(body: SlipBody, request: Request) -> Response:
    """The thermal slip PNG for exactly these legs."""
    require_admin(request)
    from kalchas_bot.parlay_slip import render_parlay_slip

    day, legs = take(body)
    png = render_parlay_slip(legs, slot=body.slot, style=body.style, day=day["day"])
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/caption")
def caption(body: SlipBody, request: Request) -> dict[str, str]:
    require_admin(request)
    day, legs = take(body)
    return {"caption": default_caption(body.slot, body.style, legs, body.kind, day["window_label"])}


@router.post("/evaluate")
def evaluate_slip(body: EvaluateBody, request: Request) -> dict[str, Any]:
    """Claude's read: weakest leg and swap ideas from the unused legs. Changes nothing."""
    require_admin(request)
    from kalchas_api.parlay_claude import evaluate

    day, legs = take(body, need_odds=False)
    chosen = {str(leg["match_id"]) for leg in legs}
    rank = {mid: i for i, mid in enumerate(day["order"].get(body.style) or [])}
    unused = sorted(
        (leg for leg in day["legs"] if str(leg["match_id"]) not in chosen),
        key=lambda leg: (rank.get(str(leg["match_id"]), len(rank)), -float(leg.get("score") or 0)),
    )
    style = ANY_STYLE_FOR_CLAUDE if body.kind == "any" else body.style
    result = evaluate(slot=body.slot, style=style, day=day["day"], selected=legs, unused=unused)
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
    day, legs = take(body)
    text = body.caption.strip() or default_caption(
        body.slot, body.style, legs, body.kind, day["window_label"]
    )
    row = insert_slip_sync(
        _dsn(),
        day=date.fromisoformat(day["day"]),
        slot=body.slot,
        style=ANY_STYLE if body.kind == "any" else body.style,
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


@router.post("/slips/{slip_id}/retry/{channel}")
def retry_channel(slip_id: int, channel: Channel, request: Request) -> dict[str, Any]:
    """Post a slip again to one channel that failed, leaving the others alone."""
    require_admin(request)
    from kalchas_db.parlay_slips import retry_channel_sync

    if not retry_channel_sync(_dsn(), slip_id, channel):
        raise HTTPException(
            status_code=409,
            detail="that channel can't be retried: it already posted, or the slip has settled",
        )
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
