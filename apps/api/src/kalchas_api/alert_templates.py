"""Admin: edit the text of alert messages per strategy (Telegram, Discord, X).

Templates live in ``alert_templates`` (migrations 0035, 0038), keyed by
(strategy, channel, kind). ``default`` covers every strategy without its own
text. The preview runs the bot's own code (``kalchas_bot.templates``) on real
recent alerts, so what admin sees is what the bot would send.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from kalchas_bot import templates as tpl
from kalchas_bot.format import lead_key, ordered_rows
from kalchas_core.weights import short_label_for
from pydantic import BaseModel, Field

from kalchas_api.admin_auth import require_admin

log = logging.getLogger("kalchas.api.alert_templates")

router = APIRouter(prefix="/api/admin/alert-templates", tags=["admin-alert-templates"])

MAX_BODY = 4000
SAMPLES_PER_KIND = 40


class TemplateIn(BaseModel):
    body: str = Field(default="", max_length=MAX_BODY)
    enabled: bool = True


class PreviewIn(BaseModel):
    strategy: str = tpl.DEFAULT_STRATEGY
    channel: str
    kind: str
    body: str = Field(default="", max_length=MAX_BODY)
    ids: list[int] = Field(default_factory=list, max_length=10)


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def _check_slot(strategy: str, channel: str, kind: str) -> None:
    if not tpl.valid_slot(strategy, channel, kind):
        raise HTTPException(status_code=404, detail="no such template")


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _sample_label(rows: Sequence[Mapping[str, Any]]) -> str:
    first = rows[0]
    shorts = " + ".join(short_label_for(str(row.get("strategy_key") or "")) for row in rows)
    minute = first.get("minute")
    clock = f" · {minute}′" if minute not in (None, "") else ""
    return f"{first.get('home_team') or '?'} vs {first.get('away_team') or '?'}{clock} · {shorts}"


def alert_samples(
    rows: Sequence[Mapping[str, Any]], limit: int = SAMPLES_PER_KIND
) -> list[dict[str, Any]]:
    """One preview choice per sent message: alerts on the same match minute go together.

    ``lead`` is the strategy whose text the message uses (Δ5′ > Δ10′ > Form Bar > UrG > K).
    """
    groups: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    order: list[tuple[str, int]] = []
    for row in rows:
        try:
            minute = int(row.get("minute") or 0)
        except (TypeError, ValueError):
            minute = 0
        key = (str(row.get("match_id") or ""), minute)
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(row)
    out: list[dict[str, Any]] = []
    for key in order:
        group = ordered_rows(groups[key])
        label = _sample_label(group)
        if len(group) > 1:
            label = f"{label} (joint post)"
        out.append({"ids": [int(r["id"]) for r in group], "label": label, "lead": lead_key(group)})
    return _spread(out, limit)


def reply_samples(
    rows: Sequence[Mapping[str, Any]], limit: int = SAMPLES_PER_KIND
) -> list[dict[str, Any]]:
    out = [
        {
            "ids": [int(row["id"])],
            "label": _sample_label([row]),
            "lead": str(row.get("strategy_key") or ""),
        }
        for row in rows
    ]
    return _spread(out, limit)


def _spread(samples: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Newest first, but keep a few of every strategy so each tab has its own samples."""
    per_lead = max(1, limit // max(1, len(tpl.LIVE_STRATEGIES)))
    kept: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for sample in samples:
        lead = sample["lead"]
        if counts.get(lead, 0) >= per_lead:
            continue
        counts[lead] = counts.get(lead, 0) + 1
        kept.append(sample)
    return kept


def _active(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str], str]:
    return {
        (str(row.get("strategy") or tpl.DEFAULT_STRATEGY), str(row["channel"]), str(row["kind"])): (
            str(row["body"])
        )
        for row in rows
        if row.get("enabled") and str(row.get("body") or "").strip()
    }


def _saved_rows(dsn: str | None) -> list[dict[str, Any]]:
    if not dsn:
        return []
    from kalchas_db.alert_templates import list_templates

    try:
        return list_templates(dsn)
    except Exception:  # before migrations 0035 / 0038 the table or column is missing
        log.exception("alert templates not readable")
        return []


def _slot(row: Mapping[str, Any] | None, channel: str, kind: str, body: str) -> dict[str, Any]:
    return {
        "saved": row is not None,
        "body": str(row["body"]) if row else body,
        "enabled": bool(row["enabled"]) if row else False,
        "updated_at": _iso(row.get("updated_at")) if row else None,
        "fallback_count": int(row.get("fallback_count") or 0) if row else 0,
        "last_fallback_at": _iso(row.get("last_fallback_at")) if row else None,
        "last_fallback_reason": row.get("last_fallback_reason") if row else None,
        "limit": tpl.limit_for(channel, kind),
    }


@router.get("")
def get_templates(request: Request) -> dict[str, Any]:
    require_admin(request)
    dsn = _dsn()
    saved = {
        (str(row.get("strategy") or tpl.DEFAULT_STRATEGY), str(row["channel"]), str(row["kind"])): (
            row
        )
        for row in _saved_rows(dsn)
    }
    slots: dict[str, dict[str, dict[str, Any]]] = {}
    for strategy in tpl.STRATEGIES:
        slots[strategy] = {}
        for channel in tpl.CHANNELS:
            slots[strategy][channel] = {}
            for kind in tpl.kinds_for(channel):
                row = saved.get((strategy, channel, kind))
                # A strategy without its own text starts from Default's.
                base = saved.get((tpl.DEFAULT_STRATEGY, channel, kind))
                start = str(base["body"]) if base else tpl.default_template(channel, kind)
                slots[strategy][channel][kind] = _slot(row, channel, kind, start)
    samples: dict[str, list[dict[str, Any]]] = {"alert": [], "goal": [], "miss": []}
    if dsn:
        from kalchas_db.alert_templates import recent_alerts, recent_goals, recent_misses

        try:
            samples["alert"] = alert_samples(recent_alerts(dsn))
            samples["goal"] = reply_samples(recent_goals(dsn))
            samples["miss"] = reply_samples(recent_misses(dsn))
        except Exception:  # the page still works on the made-up example
            log.exception("preview samples not readable")
    return {
        "strategies": [
            {
                "key": key,
                "label": tpl.strategy_label(key),
                "short": "All" if key == tpl.DEFAULT_STRATEGY else short_label_for(key),
            }
            for key in tpl.STRATEGIES
        ],
        "channels": [
            {"key": channel, "kinds": list(tpl.kinds_for(channel))} for channel in tpl.CHANNELS
        ],
        "templates": slots,
        "defaults": {
            channel: {kind: tpl.default_template(channel, kind) for kind in tpl.kinds_for(channel)}
            for channel in tpl.CHANNELS
        },
        "tags": tpl.tag_list(),
        "samples": samples,
    }


def _example_rows(kind: str) -> list[dict[str, Any]]:
    if kind == "alert":
        return tpl.long_rows()[:1]
    if kind == "goal":
        return [tpl.long_goal_row()]
    return [tpl.long_miss_row()]


@router.post("/preview")
def preview_template(body: PreviewIn, request: Request) -> dict[str, Any]:
    require_admin(request)
    _check_slot(body.strategy, body.channel, body.kind)
    dsn = _dsn()
    rows: list[dict[str, Any]] = []
    if dsn and body.ids:
        from kalchas_db.alert_templates import alerts_by_ids

        rows = alerts_by_ids(dsn, body.ids)
    example = not rows
    if example:
        rows = _example_rows(body.kind)
    active = _active(_saved_rows(dsn))
    result = tpl.preview(body.strategy, body.channel, body.kind, body.body, rows, active)
    result["example"] = example
    return result


@router.put("/{strategy}/{channel}/{kind}", response_model=None)
def save_template(
    strategy: str, channel: str, kind: str, body: TemplateIn, request: Request
) -> dict[str, Any] | JSONResponse:
    require_admin(request)
    _check_slot(strategy, channel, kind)
    problems = tpl.validate(channel, kind, body.body)
    if problems:
        return JSONResponse(status_code=422, content={"problems": problems})
    dsn = _dsn()
    if not dsn:
        raise HTTPException(status_code=503, detail="no database")
    from kalchas_db.alert_templates import save_template as store

    store(dsn, strategy=strategy, channel=channel, kind=kind, body=body.body, enabled=body.enabled)
    return {"ok": True}


@router.delete("/{strategy}/{channel}/{kind}")
def reset_template(strategy: str, channel: str, kind: str, request: Request) -> dict[str, bool]:
    require_admin(request)
    _check_slot(strategy, channel, kind)
    dsn = _dsn()
    if not dsn:
        raise HTTPException(status_code=503, detail="no database")
    from kalchas_db.alert_templates import delete_template

    delete_template(dsn, strategy=strategy, channel=channel, kind=kind)
    return {"ok": True}
