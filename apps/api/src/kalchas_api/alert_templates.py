"""Admin: edit the text of alert messages (Telegram paid/free, Discord).

Templates live in ``alert_templates`` (migration 0035). The preview runs the
bot's own code (``kalchas_bot.templates``) on real recent alerts, so what
admin sees is what the bot would send.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from kalchas_bot import templates as tpl
from kalchas_core.weights import short_label_for
from pydantic import BaseModel, Field

from kalchas_api.admin_auth import require_admin

log = logging.getLogger("kalchas.api.alert_templates")

router = APIRouter(prefix="/api/admin/alert-templates", tags=["admin-alert-templates"])

MAX_BODY = 4000


class TemplateIn(BaseModel):
    body: str = Field(default="", max_length=MAX_BODY)
    enabled: bool = True


class PreviewIn(BaseModel):
    channel: str
    kind: str
    body: str = Field(default="", max_length=MAX_BODY)
    ids: list[int] = Field(default_factory=list, max_length=10)


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def _check_slot(channel: str, kind: str) -> None:
    if channel not in tpl.CHANNELS or kind not in tpl.KINDS:
        raise HTTPException(status_code=404, detail="no such template")


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _sample_label(rows: Sequence[Mapping[str, Any]]) -> str:
    first = rows[0]
    shorts = " + ".join(short_label_for(str(row.get("strategy_key") or "")) for row in rows)
    minute = first.get("minute")
    clock = f" · {minute}′" if minute not in (None, "") else ""
    return f"{first.get('home_team') or '?'} vs {first.get('away_team') or '?'}{clock} · {shorts}"


def alert_samples(rows: Sequence[Mapping[str, Any]], limit: int = 15) -> list[dict[str, Any]]:
    """One preview choice per sent message: alerts on the same match minute go together."""
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
    for key in order[:limit]:
        group = sorted(groups[key], key=lambda r: (int(r.get("strategy_slot") or 0), int(r["id"])))
        label = _sample_label(group)
        if len(group) > 1:
            label = f"{label} (joint post)"
        out.append({"ids": [int(r["id"]) for r in group], "label": label})
    return out


def goal_samples(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{"ids": [int(row["id"])], "label": _sample_label([row])} for row in rows]


def _active(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], str]:
    return {
        (str(row["channel"]), str(row["kind"])): str(row["body"])
        for row in rows
        if row.get("enabled") and str(row.get("body") or "").strip()
    }


def _saved_rows(dsn: str | None) -> list[dict[str, Any]]:
    if not dsn:
        return []
    from kalchas_db.alert_templates import list_templates

    try:
        return list_templates(dsn)
    except Exception:  # before migration 0035 there is no table
        log.exception("alert templates not readable")
        return []


@router.get("")
def get_templates(request: Request) -> dict[str, Any]:
    require_admin(request)
    dsn = _dsn()
    saved = {(str(row["channel"]), str(row["kind"])): row for row in _saved_rows(dsn)}
    slots: dict[str, dict[str, Any]] = {}
    for channel in tpl.CHANNELS:
        slots[channel] = {}
        for kind in tpl.KINDS:
            row = saved.get((channel, kind))
            slots[channel][kind] = {
                "saved": row is not None,
                "body": str(row["body"]) if row else tpl.DEFAULT_TEMPLATES[kind],
                "enabled": bool(row["enabled"]) if row else False,
                "updated_at": _iso(row.get("updated_at")) if row else None,
                "fallback_count": int(row.get("fallback_count") or 0) if row else 0,
                "last_fallback_at": _iso(row.get("last_fallback_at")) if row else None,
                "last_fallback_reason": row.get("last_fallback_reason") if row else None,
                "limit": tpl.limit_for(channel, kind),
            }
    samples: dict[str, list[dict[str, Any]]] = {"alert": [], "goal": []}
    if dsn:
        from kalchas_db.alert_templates import recent_alerts, recent_goals

        try:
            samples["alert"] = alert_samples(recent_alerts(dsn))
            samples["goal"] = goal_samples(recent_goals(dsn))
        except Exception:  # the page still works on the made-up example
            log.exception("preview samples not readable")
    return {
        "templates": slots,
        "defaults": tpl.DEFAULT_TEMPLATES,
        "tags": tpl.tag_list(),
        "samples": samples,
    }


@router.post("/preview")
def preview_template(body: PreviewIn, request: Request) -> dict[str, Any]:
    require_admin(request)
    _check_slot(body.channel, body.kind)
    dsn = _dsn()
    rows: list[dict[str, Any]] = []
    if dsn and body.ids:
        from kalchas_db.alert_templates import alerts_by_ids

        rows = alerts_by_ids(dsn, body.ids)
    example = not rows
    if example:
        rows = tpl.long_rows()[:1] if body.kind == "alert" else [tpl.long_goal_row()]
    active = _active(_saved_rows(dsn))
    result = tpl.preview(body.channel, body.kind, body.body, rows, active)
    result["example"] = example
    return result


@router.put("/{channel}/{kind}", response_model=None)
def save_template(
    channel: str, kind: str, body: TemplateIn, request: Request
) -> dict[str, Any] | JSONResponse:
    require_admin(request)
    _check_slot(channel, kind)
    problems = tpl.validate(channel, kind, body.body)
    if problems:
        return JSONResponse(status_code=422, content={"problems": problems})
    dsn = _dsn()
    if not dsn:
        raise HTTPException(status_code=503, detail="no database")
    from kalchas_db.alert_templates import save_template as store

    store(dsn, channel=channel, kind=kind, body=body.body, enabled=body.enabled)
    return {"ok": True}


@router.delete("/{channel}/{kind}")
def reset_template(channel: str, kind: str, request: Request) -> dict[str, bool]:
    require_admin(request)
    _check_slot(channel, kind)
    dsn = _dsn()
    if not dsn:
        raise HTTPException(status_code=503, detail="no database")
    from kalchas_db.alert_templates import delete_template

    delete_template(dsn, channel=channel, kind=kind)
    return {"ok": True}
