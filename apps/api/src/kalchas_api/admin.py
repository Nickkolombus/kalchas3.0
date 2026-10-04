"""Password-gated admin API for live strategy tuning."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from kalchas_core.alert_outcomes import DEFAULT_RULES
from kalchas_core.conditions import condition_catalog, prepare_extra_conditions
from kalchas_core.cooldown import (
    DEFAULT_BASE_COOLDOWN,
    DEFAULT_BYPASS_DELTA,
    DEFAULT_OMEGA_COOLDOWN,
)
from kalchas_core.runner import DEFAULT_THRESHOLDS
from kalchas_core.weights import BUILTIN_PRESETS, REGISTRY, STRATEGY_INFO, WeightSet, spec_for
from kalchas_db.settings import KEY_BY_SLOT, SLOT_BY_KEY
from pydantic import BaseModel, Field

from kalchas_api.admin_auth import (
    COOKIE_NAME,
    admin_configured,
    clear_session_cookie,
    password_matches,
    require_admin,
    set_session_cookie,
    token_valid,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class LoginIn(BaseModel):
    password: str


class ThresholdIn(BaseModel):
    slot: int
    threshold: float
    cooldown_minutes: int = Field(ge=0, le=90)
    cooldown_bypass_delta: float | None = None
    enabled: bool = True


class ThresholdsPut(BaseModel):
    items: list[ThresholdIn]


class RuleIn(BaseModel):
    slot: int
    success_window_minutes: int = Field(ge=0, le=999)
    expiration_buffer_minutes: int = Field(ge=0, le=30)
    infinite_ttl: bool
    team_specific: bool
    expire_at_half_end: bool = False
    enabled: bool = True


class RulesPut(BaseModel):
    items: list[RuleIn]


class WeightIn(BaseModel):
    strategy: str
    key: str
    value: float


class WeightResetIn(BaseModel):
    strategy: str
    key: str | None = None


class WeightPresetIn(BaseModel):
    strategy: str
    preset: str


class WeightPresetSaveIn(BaseModel):
    strategy: str
    name: str
    weights: dict[str, float] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)


class WeightPreviewIn(BaseModel):
    strategy: str
    weights: dict[str, float] = Field(default_factory=dict)
    match_id: str | None = None
    conditions: list[dict[str, Any]] | None = None


class ConditionsPut(BaseModel):
    strategy: str
    conditions: list[dict[str, Any]] = Field(default_factory=list)


class VariousIn(BaseModel):
    ht1_start: int = Field(ge=0, le=130)
    ht1_end: int = Field(ge=0, le=130)
    ht2_start: int = Field(ge=0, le=130)
    ht2_end: int = Field(ge=0, le=130)
    include_injury_time: bool = False


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required")
    return dsn


def _rule_lookup() -> dict[int, Any]:
    return {r.strategy_slot: r for r in DEFAULT_RULES}


@router.post("/login")
def login(body: LoginIn, response: Response) -> dict[str, bool]:
    if not admin_configured():
        raise HTTPException(status_code=503, detail="ADMIN_PASSWORD is not set")
    if not password_matches(body.password):
        raise HTTPException(status_code=401, detail="invalid password")
    set_session_cookie(response)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/session")
def session(request: Request) -> dict[str, bool]:
    if not admin_configured():
        return {"ok": False, "configured": False}
    return {"ok": token_valid(request.cookies.get(COOKIE_NAME)), "configured": True}


@router.get("/config")
def admin_config(request: Request) -> dict[str, Any]:
    require_admin(request)
    from kalchas_core.sweet_spot import SweetSpotWindows
    from kalchas_db.settings import (
        get_board_settings,
        list_admin_rules,
        list_saved_presets,
        list_strategy_conditions,
        list_thresholds,
        list_weight_overrides,
    )

    dsn = _dsn()
    try:
        stored_th = list_thresholds(dsn)
        stored_w = list_weight_overrides(dsn)
        stored_rules = list_admin_rules(dsn)
        list_saved_names = {key: list_saved_presets(dsn, key) for key in KEY_BY_SLOT.values()}
        try:
            stored_conditions = list_strategy_conditions(dsn)
        except Exception:  # noqa: BLE001 — missing table must not block admin
            stored_conditions = {}
        try:
            various = get_board_settings(dsn)
        except Exception:  # noqa: BLE001 — missing table must not block admin
            various = SweetSpotWindows().as_dict()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"settings unavailable: {exc}") from exc

    weights = WeightSet.from_overrides(stored_w)
    rules_by_slot = {int(r["strategy_slot"]): r for r in stored_rules}
    defaults = _rule_lookup()
    strategies = []
    for slot, key in KEY_BY_SLOT.items():
        info = STRATEGY_INFO.get(key)
        row = rules_by_slot.get(slot)
        fallback = defaults.get(slot)
        strategies.append(
            {
                "slot": slot,
                "key": key,
                "name": info.name if info else key,
                "short": info.short if info else f"S{slot}",
                "equation": info.equation if info else "",
                "blurb": info.blurb if info else "",
                "threshold": float(stored_th.get(slot, DEFAULT_THRESHOLDS.get(slot, 0.0))),
                "cooldown_minutes": int(
                    (row or {}).get("cooldown_minutes")
                    or (DEFAULT_OMEGA_COOLDOWN if slot == 6 else DEFAULT_BASE_COOLDOWN)
                ),
                "cooldown_bypass_delta": (
                    float(row["cooldown_bypass_delta"])
                    if row and row.get("cooldown_bypass_delta") is not None
                    else DEFAULT_BYPASS_DELTA.get(slot)
                ),
                "enabled": bool(row["enabled"]) if row else True,
                "success_window_minutes": int(
                    (row or {}).get("success_window_minutes")
                    or (fallback.success_window_minutes if fallback else 20)
                ),
                "expiration_buffer_minutes": int(
                    (row or {}).get("expiration_buffer_minutes")
                    or (fallback.expiration_buffer_minutes if fallback else 2)
                ),
                "infinite_ttl": bool(
                    row["infinite_ttl"] if row else (fallback.infinite_ttl if fallback else False)
                ),
                "team_specific": bool(
                    row["team_specific"] if row else (fallback.team_specific if fallback else False)
                ),
                "expire_at_half_end": bool(
                    row["expire_at_half_end"]
                    if row and row.get("expire_at_half_end") is not None
                    else False
                ),
                "weights": weights.describe(key),
                "presets": list(BUILTIN_PRESETS.get(key, {}).keys()),
                "saved_presets": list_saved_names.get(key, []),
                "conditions": list(stored_conditions.get(slot) or []),
            }
        )
    return {
        "strategies": strategies,
        "various": various,
        "condition_catalog": condition_catalog(),
    }


@router.put("/thresholds")
def put_thresholds(request: Request, body: ThresholdsPut) -> dict[str, bool]:
    require_admin(request)
    from kalchas_db.settings import list_admin_rules, update_admin_rule, upsert_thresholds

    dsn = _dsn()
    stored = {int(r["strategy_slot"]): r for r in list_admin_rules(dsn)}
    defaults = _rule_lookup()
    values: dict[int, float] = {}
    for item in body.items:
        if item.slot not in KEY_BY_SLOT:
            continue
        values[item.slot] = float(item.threshold)
        current = stored.get(item.slot)
        fallback = defaults.get(item.slot)
        update_admin_rule(
            dsn,
            item.slot,
            {
                "success_window_minutes": int(
                    (current or {}).get("success_window_minutes")
                    or (fallback.success_window_minutes if fallback else 20)
                ),
                "expiration_buffer_minutes": int(
                    (current or {}).get("expiration_buffer_minutes")
                    or (fallback.expiration_buffer_minutes if fallback else 2)
                ),
                "infinite_ttl": bool(
                    (current or {}).get("infinite_ttl")
                    if current
                    else (fallback.infinite_ttl if fallback else False)
                ),
                "team_specific": bool(
                    (current or {}).get("team_specific")
                    if current
                    else (fallback.team_specific if fallback else False)
                ),
                "expire_at_half_end": bool(
                    (current or {}).get("expire_at_half_end") if current else False
                ),
                "enabled": item.enabled,
                "cooldown_minutes": item.cooldown_minutes,
                "cooldown_bypass_delta": item.cooldown_bypass_delta,
            },
        )
    upsert_thresholds(dsn, values)
    from kalchas_api.runtime import clear_board_tuning_cache

    clear_board_tuning_cache()
    return {"ok": True}


@router.put("/rules")
def put_rules(request: Request, body: RulesPut) -> dict[str, bool]:
    require_admin(request)
    from kalchas_db.settings import list_admin_rules, update_admin_rule

    dsn = _dsn()
    stored = {int(r["strategy_slot"]): r for r in list_admin_rules(dsn)}
    for item in body.items:
        current = stored.get(item.slot) or {}
        updated = update_admin_rule(
            dsn,
            item.slot,
            {
                "success_window_minutes": item.success_window_minutes,
                "expiration_buffer_minutes": item.expiration_buffer_minutes,
                "infinite_ttl": item.infinite_ttl,
                "team_specific": item.team_specific,
                "expire_at_half_end": item.expire_at_half_end,
                "enabled": item.enabled,
                "cooldown_minutes": int(current.get("cooldown_minutes") or DEFAULT_BASE_COOLDOWN),
                "cooldown_bypass_delta": current.get("cooldown_bypass_delta"),
            },
        )
        if updated is None:
            raise HTTPException(
                status_code=404, detail=f"No strategy_rules row for slot {item.slot}"
            )
    from kalchas_api.runtime import clear_board_tuning_cache

    clear_board_tuning_cache()
    return {"ok": True}


@router.put("/weights")
def put_weight(request: Request, body: WeightIn) -> dict[str, Any]:
    require_admin(request)
    spec = spec_for(body.strategy, body.key)
    if spec is None or body.strategy not in REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown weight {body.strategy}.{body.key}")
    from kalchas_db.settings import list_weight_overrides, upsert_weight

    dsn = _dsn()
    upsert_weight(dsn, body.strategy, body.key, spec.clamp(body.value))
    from kalchas_api.runtime import clear_board_tuning_cache

    clear_board_tuning_cache()
    weights = WeightSet.from_overrides(list_weight_overrides(dsn))
    return {"ok": True, "weights": weights.describe(body.strategy)}


@router.post("/weights/reset")
def reset_weight(request: Request, body: WeightResetIn) -> dict[str, Any]:
    require_admin(request)
    if body.strategy not in REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown strategy {body.strategy}")
    from kalchas_db.settings import list_weight_overrides, reset_weights

    dsn = _dsn()
    count = reset_weights(dsn, body.strategy, body.key)
    from kalchas_api.runtime import clear_board_tuning_cache

    clear_board_tuning_cache()
    weights = WeightSet.from_overrides(list_weight_overrides(dsn))
    return {"ok": True, "reset_count": count, "weights": weights.describe(body.strategy)}


@router.post("/weights/preset")
def apply_preset(request: Request, body: WeightPresetIn) -> dict[str, Any]:
    require_admin(request)
    if body.strategy not in REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown strategy {body.strategy}")
    from kalchas_db.settings import (
        get_saved_preset_bundle,
        list_weight_overrides,
        replace_strategy_conditions,
        reset_weights,
        upsert_weight,
    )

    dsn = _dsn()
    builtin = BUILTIN_PRESETS.get(body.strategy) or {}
    conditions = None
    if body.preset in builtin:
        values = dict(builtin[body.preset])
    else:
        saved = get_saved_preset_bundle(dsn, body.strategy, body.preset)
        if saved is None:
            raise HTTPException(status_code=400, detail=f"unknown preset {body.preset}")
        values, conditions = saved
    reset_weights(dsn, body.strategy)
    for key, value in values.items():
        spec = spec_for(body.strategy, key)
        if spec is None:
            continue
        upsert_weight(dsn, body.strategy, key, spec.clamp(float(value)))
    if conditions is not None:
        slot = SLOT_BY_KEY.get(body.strategy)
        if slot is not None:
            replace_strategy_conditions(dsn, slot, prepare_extra_conditions(conditions))
    from kalchas_api.runtime import clear_board_tuning_cache

    clear_board_tuning_cache()
    weights = WeightSet.from_overrides(list_weight_overrides(dsn))
    from kalchas_db.settings import list_strategy_conditions

    slot = SLOT_BY_KEY.get(body.strategy)
    return {
        "ok": True,
        "weights": weights.describe(body.strategy),
        "conditions": list(list_strategy_conditions(dsn).get(slot) or []) if slot else [],
    }


def _clamp_weight_map(strategy: str, raw: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in raw.items():
        spec = spec_for(strategy, key)
        if spec is None:
            continue
        try:
            out[key] = spec.clamp(float(value))
        except (TypeError, ValueError):
            continue
    return out


def _preset_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if len(cleaned) < 2 or len(cleaned) > 40:
        raise HTTPException(status_code=400, detail="preset name must be 2-40 characters")
    return cleaned


@router.post("/weights/preset/save")
def save_preset(request: Request, body: WeightPresetSaveIn) -> dict[str, Any]:
    require_admin(request)
    if body.strategy not in REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown strategy {body.strategy}")
    name = _preset_name(body.name)
    builtin = BUILTIN_PRESETS.get(body.strategy) or {}
    if name.lower() in {item.lower() for item in builtin}:
        raise HTTPException(status_code=400, detail="that name is a built-in preset")
    values = _clamp_weight_map(body.strategy, body.weights)
    if not values:
        raise HTTPException(status_code=400, detail="no valid weights to save")
    try:
        extra = prepare_extra_conditions(body.conditions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from kalchas_db.settings import (
        list_saved_presets,
        list_weight_overrides,
        replace_strategy_conditions,
        reset_weights,
        upsert_saved_preset,
        upsert_weight,
    )

    dsn = _dsn()
    upsert_saved_preset(
        dsn,
        body.strategy,
        name,
        {"weights": values, "conditions": extra},
    )
    reset_weights(dsn, body.strategy)
    for key, value in values.items():
        upsert_weight(dsn, body.strategy, key, value)
    slot = SLOT_BY_KEY.get(body.strategy)
    if slot is not None:
        replace_strategy_conditions(dsn, slot, extra)
    from kalchas_api.runtime import clear_board_tuning_cache

    clear_board_tuning_cache()
    weights = WeightSet.from_overrides(list_weight_overrides(dsn))
    return {
        "ok": True,
        "name": name,
        "weights": weights.describe(body.strategy),
        "saved_presets": list_saved_presets(dsn, body.strategy),
        "conditions": extra,
    }


@router.post("/preview")
def preview_weights(request: Request, body: WeightPreviewIn) -> dict[str, Any]:
    require_admin(request)
    if body.strategy not in REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown strategy {body.strategy}")
    from kalchas_api.preview import preview_live_matches

    overlay = _clamp_weight_map(body.strategy, body.weights)
    dsn = _dsn()
    extra = None
    if body.conditions is not None:
        try:
            extra = prepare_extra_conditions(body.conditions)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        matches = preview_live_matches(
            dsn,
            strategy_key=body.strategy,
            overlay=overlay,
            match_id=body.match_id,
            conditions_overlay=extra,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"preview unavailable: {exc}") from exc
    return {"strategy": body.strategy, "matches": matches}


@router.put("/conditions")
def put_conditions(request: Request, body: ConditionsPut) -> dict[str, Any]:
    require_admin(request)
    if body.strategy not in REGISTRY or body.strategy not in SLOT_BY_KEY:
        raise HTTPException(status_code=400, detail=f"unknown strategy {body.strategy}")
    try:
        extra = prepare_extra_conditions(body.conditions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from kalchas_db.settings import replace_strategy_conditions

    dsn = _dsn()
    stored = replace_strategy_conditions(dsn, SLOT_BY_KEY[body.strategy], extra)
    from kalchas_api.runtime import clear_board_tuning_cache

    clear_board_tuning_cache()
    return {"ok": True, "conditions": stored}


def _parse_results_window(since: str | None, until: str | None) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    if since:
        start = datetime.fromisoformat(since.replace("Z", "+00:00"))
    else:
        start = now - timedelta(days=7)
    if until:
        end = datetime.fromisoformat(until.replace("Z", "+00:00"))
        if len(until) <= 10:
            end = end + timedelta(days=1)
    else:
        end = now + timedelta(days=1)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return start, end


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _result_item(row: dict[str, Any]) -> dict[str, Any]:
    payload = _json_object(row.get("payload"))
    detail = _json_object(row.get("detail"))
    return {
        "id": int(row["id"]),
        "match_id": str(row["match_id"]),
        "strategy": str(row["strategy_key"]),
        "slot": int(row["strategy_slot"]),
        "team": str(row["team"]) if row.get("team") else None,
        "value": float(row["value"]),
        "theta": payload.get("theta"),
        "minute": int(row["minute"]),
        "score": str(row["score"]) if row.get("score") else None,
        "home_team": str(row["home_team"]) if row.get("home_team") else None,
        "away_team": str(row["away_team"]) if row.get("away_team") else None,
        "league": payload.get("league") or detail.get("league"),
        "state": str(row["state"]) if row.get("state") else "Monitoring",
        "created_at": _iso(row.get("created_at")),
        "evaluated_at": _iso(row.get("evaluated_at")),
        "settle_score": detail.get("settle_score"),
        "settle_minute": detail.get("settle_minute"),
        "live": bool(row.get("live")),
    }


@router.get("/results")
def admin_results(
    request: Request,
    since: str | None = None,
    until: str | None = None,
    strategy: list[str] | None = Query(default=None),
    state: str | None = None,
    team: str | None = None,
    league: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.alerts import list_alert_results_sync

    start, end = _parse_results_window(since, until)
    keys = [item for item in (strategy or []) if item]
    dsn = _dsn()
    try:
        rows, summary = list_alert_results_sync(
            dsn,
            since=start,
            until=end,
            strategies=keys or None,
            state=state or None,
            team=team or None,
            league=league or None,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"results unavailable: {exc}") from exc
    settled = int(summary["confirmed"]) + int(summary["expired"])
    hit_rate = (int(summary["confirmed"]) / settled) if settled else None
    return {
        "since": start.isoformat(),
        "until": end.isoformat(),
        "summary": {**summary, "hit_rate": hit_rate},
        "items": [_result_item(row) for row in rows],
    }


@router.get("/various")
def get_various(request: Request) -> dict[str, Any]:
    require_admin(request)
    from kalchas_core.sweet_spot import SweetSpotWindows
    from kalchas_db.settings import get_board_settings

    try:
        return {"various": get_board_settings(_dsn())}
    except Exception:  # noqa: BLE001 — missing table falls back to defaults
        return {"various": SweetSpotWindows().as_dict()}


@router.put("/various")
def put_various(request: Request, body: VariousIn) -> dict[str, Any]:
    require_admin(request)
    from kalchas_db.settings import upsert_board_settings

    try:
        saved = upsert_board_settings(_dsn(), body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"settings unavailable: {exc}") from exc
    return {"ok": True, "various": saved}
