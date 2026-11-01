"""Admin review of the weekly recap: read, edit, preview, approve, skip.

The bot drafts every Monday and posts once a recap is approved; this router
is the human in between. Approval needs the lesson line, which is never
drafted for you.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from kalchas_core.recap import (
    build_recap,
    final_caption,
    headline,
    lesson_missing,
    miss_notes,
    week_bounds,
)
from kalchas_core.runner import DEFAULT_THRESHOLDS
from pydantic import BaseModel, Field

from kalchas_api.admin_auth import require_admin

router = APIRouter(prefix="/api/admin/recap", tags=["admin"])

CAPTION_LIMIT = 1024
TWEET_LIMIT = 280
EDITABLE = ("draft", "failed")


class RecapTexts(BaseModel):
    cover_line: str = ""
    calls: list[str] = Field(default_factory=list)
    honourable: str = ""
    miss: str = ""
    lesson: str = ""
    x: str = ""
    caption: str = ""


class RecapEdit(BaseModel):
    texts: RecapTexts
    channels: dict[str, bool] = Field(default_factory=dict)


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required")
    return dsn


def _week(raw: str) -> date:
    try:
        week = date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="week must be YYYY-MM-DD") from exc
    if week.weekday() != 0:
        raise HTTPException(status_code=400, detail="week must start on a Monday")
    return week


def _deadline(week: date) -> datetime:
    return datetime.combine(week + timedelta(days=8), time(12, 0), tzinfo=UTC)


def _tweet_weight(value: str) -> int:
    from kalchas_bot.twitter_channel import tweet_weight

    return tweet_weight(value)


def _view(row: dict[str, Any]) -> dict[str, Any]:
    data, texts = row["data"], row["texts"]
    caption = final_caption(texts)
    week = row["week_start"]
    return {
        "week_start": week.isoformat(),
        "status": row["status"],
        "editable": row["status"] in EDITABLE,
        "deadline": _deadline(week).isoformat(),
        "headline": headline(data),
        "data": data,
        "texts": texts,
        "channels": row["channels"],
        "post_log": row["post_log"],
        "notes": miss_notes(data["miss"]) if data.get("miss") else [],
        "final_caption": caption,
        "limits": {
            "x": {"used": _tweet_weight(str(texts.get("x") or "")), "max": TWEET_LIMIT},
            "caption": {"used": len(caption), "max": CAPTION_LIMIT},
        },
        "notified_at": _iso(row.get("notified_at")),
        "approved_at": _iso(row.get("approved_at")),
        "posted_at": _iso(row.get("posted_at")),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


@router.get("")
def get_recap(request: Request, week: str | None = None) -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.recaps import get_recap_sync, list_recaps_sync

    dsn = _dsn()
    row = get_recap_sync(dsn, _week(week) if week else None)
    weeks = [
        {"week_start": r["week_start"].isoformat(), "status": r["status"]}
        for r in list_recaps_sync(dsn)
    ]
    last_week = week_bounds(datetime.now(UTC).date())[0]
    return {
        "recap": _view(row) if row else None,
        "weeks": weeks,
        "last_week": last_week.isoformat(),
    }


@router.post("/draft")
def draft_now(request: Request, week: str | None = None) -> dict[str, Any]:
    """Build (or rebuild, while still a draft) a week's recap without waiting for Monday."""
    require_admin(request)
    from kalchas_db.recaps import fetch_week_signals_sync, get_recap_sync, save_draft_sync
    from kalchas_db.settings import KEY_BY_SLOT, list_thresholds

    dsn = _dsn()
    start_day = _week(week) if week else week_bounds(datetime.now(UTC).date())[0]
    start = datetime.combine(start_day, time.min, tzinfo=UTC)
    rows = fetch_week_signals_sync(dsn, start, start + timedelta(days=7))
    overrides = list_thresholds(dsn)
    thresholds = {
        key: overrides.get(slot, DEFAULT_THRESHOLDS.get(slot, 0.0))
        for slot, key in KEY_BY_SLOT.items()
    }
    data = build_recap(rows, week_start=start_day, thresholds=thresholds)
    texts = data.pop("texts")
    if not save_draft_sync(dsn, start_day, data, texts):
        raise HTTPException(status_code=409, detail="that week is already approved or posted")
    row = get_recap_sync(dsn, start_day)
    return {"recap": _view(row) if row else None}


@router.put("/{week}")
def save_recap(week: str, body: RecapEdit, request: Request) -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.recaps import get_recap_sync, update_texts_sync

    dsn = _dsn()
    day = _week(week)
    if not update_texts_sync(dsn, day, body.texts.model_dump(), body.channels):
        raise HTTPException(status_code=409, detail="only a draft or a failed post can be edited")
    row = get_recap_sync(dsn, day)
    return {"recap": _view(row) if row else None}


@router.post("/{week}/preview/{card}")
def preview_card(week: str, card: int, body: RecapEdit, request: Request) -> Response:
    """PNG of one card with the texts as typed, saved or not."""
    require_admin(request)
    from kalchas_bot.recap_cards import render_recap_cards
    from kalchas_db.recaps import get_recap_sync

    row = get_recap_sync(_dsn(), _week(week))
    if row is None:
        raise HTTPException(status_code=404, detail="no recap for that week")
    cards = render_recap_cards(row["data"], body.texts.model_dump())
    if not 1 <= card <= len(cards):
        raise HTTPException(status_code=404, detail="no such card")
    return Response(content=cards[card - 1], media_type="image/png")


@router.post("/{week}/approve")
def approve_recap(week: str, request: Request) -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.recaps import get_recap_sync, set_status_sync

    dsn = _dsn()
    day = _week(week)
    row = get_recap_sync(dsn, day)
    if row is None:
        raise HTTPException(status_code=404, detail="no recap for that week")
    view = _view(row)
    if lesson_missing(row["texts"]):
        raise HTTPException(status_code=422, detail="write what we learned before approving")
    for name, limit in view["limits"].items():
        if limit["used"] > limit["max"]:
            raise HTTPException(status_code=422, detail=f"{name} text is over its limit")
    if not any(bool(on) for on in (row["channels"] or {}).values()):
        raise HTTPException(status_code=422, detail="pick at least one channel")
    if not set_status_sync(dsn, day, "approved", allowed=list(EDITABLE)):
        raise HTTPException(status_code=409, detail=f"a {row['status']} recap cannot be approved")
    fresh = get_recap_sync(dsn, day)
    return {"recap": _view(fresh) if fresh else None}


@router.post("/{week}/skip")
def skip_recap(week: str, request: Request) -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.recaps import get_recap_sync, set_status_sync

    dsn = _dsn()
    day = _week(week)
    if not set_status_sync(dsn, day, "skipped", allowed=["draft"]):
        raise HTTPException(status_code=409, detail="only a draft can be skipped")
    row = get_recap_sync(dsn, day)
    return {"recap": _view(row) if row else None}
