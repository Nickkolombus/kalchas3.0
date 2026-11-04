"""Admin review of recaps, weekly and daily: read, edit, preview, approve, skip.

The bot drafts the weekly one every Monday; a daily one is drafted only when
the admin asks for it, on a day worth telling. Either way nothing posts until
it is approved here, and every word on the cards is a field the admin can
rewrite. A weekly recap with a miss also needs the lesson line, which is never
drafted for you.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from kalchas_core.recap import (
    build_daily,
    build_recap,
    final_caption,
    headline,
    lesson_missing,
    miss_notes,
    normalize_texts,
    text_fields,
    week_bounds,
)
from kalchas_core.runner import DEFAULT_THRESHOLDS
from pydantic import BaseModel, Field

from kalchas_api.admin_auth import require_admin

router = APIRouter(prefix="/api/admin/recap", tags=["admin"])

CAPTION_LIMIT = 1024
TWEET_LIMIT = 280
EDITABLE = ("draft", "failed")
Kind = Literal["week", "day"]


class RecapEdit(BaseModel):
    texts: dict[str, str] = Field(default_factory=dict)
    channels: dict[str, bool] = Field(default_factory=dict)


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required")
    return dsn


def _start(raw: str, kind: Kind) -> date:
    try:
        start = date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc
    if kind == "week" and start.weekday() != 0:
        raise HTTPException(status_code=400, detail="week must start on a Monday")
    return start


def _deadline(week: date) -> datetime:
    return datetime.combine(week + timedelta(days=8), time(12, 0), tzinfo=UTC)


def _tweet_weight(value: str) -> int:
    from kalchas_bot.twitter_channel import tweet_weight

    return tweet_weight(value)


def _texts(body: RecapEdit, kind: Kind) -> dict[str, str]:
    """Only the fields this kind of recap has; anything else is dropped."""
    allowed = {key for key, *_ in text_fields(kind)}
    return {key: value for key, value in body.texts.items() if key in allowed}


def _fields(data: dict[str, Any], kind: Kind) -> list[dict[str, Any]]:
    calls = data.get("calls") or []
    miss = data.get("miss")
    out = []
    for key, label, where, rows in text_fields(kind):
        hint = ""
        if key.startswith("call_"):
            index = int(key.split("_")[1]) - 1
            if index >= len(calls):
                continue  # no fourth call this time
            call = calls[index]
            label = f"{label} · {call['home']} v {call['away']}"
            hint = f"picked: {call['why']}"
        elif key in ("miss", "readout_note", "lesson", "lesson_label", "miss_kicker") and not miss:
            continue
        elif key == "miss" and miss:
            label = f"{label} · {miss['home']} v {miss['away']}"
            hint = f"picked: {miss['why']}"
        out.append({"key": key, "label": label, "where": where, "rows": rows, "hint": hint})
    return out


def _view(row: dict[str, Any]) -> dict[str, Any]:
    data = row["data"]
    kind: Kind = row.get("kind") or data.get("kind") or "week"
    texts = normalize_texts(row["texts"], data)
    caption = final_caption(texts)
    start = row["week_start"]
    needs_lesson = kind == "week" and bool(data.get("miss"))
    return {
        "kind": kind,
        "week_start": start.isoformat(),
        "status": row["status"],
        "editable": row["status"] in EDITABLE,
        "deadline": _deadline(start).isoformat() if kind == "week" else None,
        "headline": headline(data),
        "data": data,
        "texts": texts,
        "fields": _fields(data, kind),
        "needs_lesson": needs_lesson,
        "channels": row["channels"],
        "post_log": row["post_log"],
        "notes": miss_notes(data["miss"]) if data.get("miss") else [],
        "final_caption": caption,
        "card_count": 1 if kind == "day" else 1 + bool(data.get("calls")) + bool(data.get("miss")),
        "limits": {
            "x": {"used": _tweet_weight(texts.get("x", "")), "max": TWEET_LIMIT},
            "caption": {"used": len(caption), "max": CAPTION_LIMIT},
        },
        "notified_at": _iso(row.get("notified_at")),
        "approved_at": _iso(row.get("approved_at")),
        "posted_at": _iso(row.get("posted_at")),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _thresholds(dsn: str) -> dict[str, float]:
    from kalchas_db.settings import KEY_BY_SLOT, list_thresholds

    overrides = list_thresholds(dsn)
    return {
        key: overrides.get(slot, DEFAULT_THRESHOLDS.get(slot, 0.0))
        for slot, key in KEY_BY_SLOT.items()
    }


@router.get("")
def get_recap(request: Request, week: str | None = None, kind: Kind = "week") -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.recaps import get_recap_sync, list_recaps_sync

    dsn = _dsn()
    row = get_recap_sync(dsn, _start(week, kind) if week else None, kind=kind)
    weeks = [
        {"week_start": r["week_start"].isoformat(), "status": r["status"]}
        for r in list_recaps_sync(dsn, kind=kind)
    ]
    today = datetime.now(UTC).date()
    last_week = week_bounds(today)[0]
    return {
        "kind": kind,
        "recap": _view(row) if row else None,
        "weeks": weeks,
        "last_week": last_week.isoformat(),
        # Still running: a preview. Monday's draft replaces it with the full week.
        "this_week": (last_week + timedelta(days=7)).isoformat(),
        "today": today.isoformat(),
        "yesterday": (today - timedelta(days=1)).isoformat(),
    }


@router.post("/draft")
def draft_now(request: Request, week: str | None = None, kind: Kind = "week") -> dict[str, Any]:
    """Build (or rebuild, while still a draft) a recap now: last week, or a chosen day."""
    require_admin(request)
    from kalchas_db.recaps import fetch_week_signals_sync, get_recap_sync, save_draft_sync

    dsn = _dsn()
    today = datetime.now(UTC).date()
    default = week_bounds(today)[0] if kind == "week" else today - timedelta(days=1)
    start_day = _start(week, kind) if week else default
    start = datetime.combine(start_day, time.min, tzinfo=UTC)
    rows = fetch_week_signals_sync(dsn, start, start + timedelta(days=7 if kind == "week" else 1))
    if kind == "week":
        data = build_recap(rows, week_start=start_day, thresholds=_thresholds(dsn))
    else:
        data = build_daily(rows, day=start_day, thresholds=_thresholds(dsn))
    texts = data.pop("texts")
    if not save_draft_sync(dsn, start_day, data, texts, kind=kind):
        raise HTTPException(status_code=409, detail="that recap is already approved or posted")
    row = get_recap_sync(dsn, start_day, kind=kind)
    return {"recap": _view(row) if row else None}


@router.put("/{week}")
def save_recap(week: str, body: RecapEdit, request: Request, kind: Kind = "week") -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.recaps import get_recap_sync, update_texts_sync

    dsn = _dsn()
    start = _start(week, kind)
    row = get_recap_sync(dsn, start, kind=kind)
    if row is None:
        raise HTTPException(status_code=404, detail="no recap for that date")
    texts = {**normalize_texts(row["texts"], row["data"]), **_texts(body, kind)}
    if not update_texts_sync(dsn, start, texts, body.channels, kind=kind):
        raise HTTPException(status_code=409, detail="only a draft or a failed post can be edited")
    fresh = get_recap_sync(dsn, start, kind=kind)
    return {"recap": _view(fresh) if fresh else None}


@router.post("/{week}/preview/{card}")
def preview_card(
    week: str, card: int, body: RecapEdit, request: Request, kind: Kind = "week"
) -> Response:
    """PNG of one card with the texts as typed, saved or not."""
    require_admin(request)
    from kalchas_bot.recap_cards import render_recap_cards
    from kalchas_db.recaps import get_recap_sync

    row = get_recap_sync(_dsn(), _start(week, kind), kind=kind)
    if row is None:
        raise HTTPException(status_code=404, detail="no recap for that date")
    texts = {**normalize_texts(row["texts"], row["data"]), **_texts(body, kind)}
    cards = render_recap_cards(row["data"], texts)
    if not 1 <= card <= len(cards):
        raise HTTPException(status_code=404, detail="no such card")
    return Response(content=cards[card - 1], media_type="image/png")


@router.post("/{week}/approve")
def approve_recap(week: str, request: Request, kind: Kind = "week") -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.recaps import get_recap_sync, set_status_sync

    dsn = _dsn()
    start = _start(week, kind)
    row = get_recap_sync(dsn, start, kind=kind)
    if row is None:
        raise HTTPException(status_code=404, detail="no recap for that date")
    view = _view(row)
    if view["needs_lesson"] and lesson_missing(view["texts"]):
        raise HTTPException(status_code=422, detail="write what we learned before approving")
    for name, limit in view["limits"].items():
        if limit["used"] > limit["max"]:
            raise HTTPException(status_code=422, detail=f"{name} text is over its limit")
    if not any(bool(on) for on in (row["channels"] or {}).values()):
        raise HTTPException(status_code=422, detail="pick at least one channel")
    if not set_status_sync(dsn, start, "approved", allowed=list(EDITABLE), kind=kind):
        raise HTTPException(status_code=409, detail=f"a {row['status']} recap cannot be approved")
    fresh = get_recap_sync(dsn, start, kind=kind)
    return {"recap": _view(fresh) if fresh else None}


@router.post("/{week}/skip")
def skip_recap(week: str, request: Request, kind: Kind = "week") -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.recaps import get_recap_sync, set_status_sync

    dsn = _dsn()
    start = _start(week, kind)
    if not set_status_sync(dsn, start, "skipped", allowed=["draft"], kind=kind):
        raise HTTPException(status_code=409, detail="only a draft can be skipped")
    row = get_recap_sync(dsn, start, kind=kind)
    return {"recap": _view(row) if row else None}
