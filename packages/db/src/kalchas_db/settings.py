"""Persisted admin settings: fire thresholds, formula weights, confirmation rules."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

KEY_BY_SLOT: dict[int, str] = {
    1: "rule_of_three",
    2: "pressure_index",
    3: "delta_goal",
    4: "delta_5min",
    6: "omega",
    7: "kscore",
}
SLOT_BY_KEY: dict[str, int] = {key: slot for slot, key in KEY_BY_SLOT.items()}

LIST_THRESHOLDS = text(
    """
    SELECT strategy_slot, threshold
    FROM strategy_thresholds
    ORDER BY strategy_slot
    """
)

UPSERT_THRESHOLD = text(
    """
    INSERT INTO strategy_thresholds (strategy_slot, threshold, updated_at)
    VALUES (:slot, :threshold, NOW())
    ON CONFLICT (strategy_slot) DO UPDATE SET
        threshold = EXCLUDED.threshold,
        updated_at = NOW()
    """
)

LIST_WEIGHTS = text(
    """
    SELECT strategy_key, coeff_key, value
    FROM strategy_weights
    ORDER BY strategy_key, coeff_key
    """
)

UPSERT_WEIGHT = text(
    """
    INSERT INTO strategy_weights (strategy_key, coeff_key, value, updated_at)
    VALUES (:strategy_key, :coeff_key, :value, NOW())
    ON CONFLICT (strategy_key, coeff_key) DO UPDATE SET
        value = EXCLUDED.value,
        updated_at = NOW()
    """
)

DELETE_WEIGHT = text(
    """
    DELETE FROM strategy_weights
    WHERE strategy_key = :strategy_key
      AND (:coeff_key = '' OR coeff_key = :coeff_key)
    """
)

LIST_RULES = text(
    """
    SELECT strategy_slot, strategy_name, success_window_minutes,
           expiration_buffer_minutes, infinite_ttl, team_specific, enabled,
           cooldown_minutes, cooldown_bypass_delta, expire_at_half_end
    FROM strategy_rules
    ORDER BY strategy_slot
    """
)

UPDATE_RULE = text(
    """
    UPDATE strategy_rules SET
        success_window_minutes = :success_window_minutes,
        expiration_buffer_minutes = :expiration_buffer_minutes,
        infinite_ttl = :infinite_ttl,
        team_specific = :team_specific,
        enabled = :enabled,
        cooldown_minutes = :cooldown_minutes,
        cooldown_bypass_delta = :cooldown_bypass_delta,
        expire_at_half_end = :expire_at_half_end,
        updated_at = NOW()
    WHERE strategy_slot = :slot
    RETURNING strategy_slot, strategy_name, success_window_minutes,
              expiration_buffer_minutes, infinite_ttl, team_specific, enabled,
              cooldown_minutes, cooldown_bypass_delta, expire_at_half_end
    """
)


def list_thresholds(dsn: str) -> dict[int, float]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_THRESHOLDS).mappings().all()
    return {int(r["strategy_slot"]): float(r["threshold"]) for r in rows}


def upsert_thresholds(dsn: str, values: dict[int, float]) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        for slot, threshold in values.items():
            conn.execute(UPSERT_THRESHOLD, {"slot": int(slot), "threshold": float(threshold)})


def list_weight_overrides(dsn: str) -> dict[str, dict[str, float]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_WEIGHTS).mappings().all()
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        out.setdefault(str(row["strategy_key"]), {})[str(row["coeff_key"])] = float(row["value"])
    return out


def upsert_weight(dsn: str, strategy_key: str, coeff_key: str, value: float) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT_WEIGHT,
            {
                "strategy_key": strategy_key,
                "coeff_key": coeff_key,
                "value": float(value),
            },
        )


def reset_weights(dsn: str, strategy_key: str, coeff_key: str | None = None) -> int:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        result = conn.execute(
            DELETE_WEIGHT,
            {"strategy_key": strategy_key, "coeff_key": coeff_key or ""},
        )
    return int(result.rowcount or 0)


def list_admin_rules(dsn: str) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_RULES).mappings().all()
    return [dict(r) for r in rows]


def update_admin_rule(dsn: str, slot: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    payload = {
        "slot": int(slot),
        "success_window_minutes": int(fields["success_window_minutes"]),
        "expiration_buffer_minutes": int(fields["expiration_buffer_minutes"]),
        "infinite_ttl": bool(fields["infinite_ttl"]),
        "team_specific": bool(fields["team_specific"]),
        "enabled": bool(fields["enabled"]),
        "cooldown_minutes": int(fields["cooldown_minutes"]),
        "cooldown_bypass_delta": (
            None
            if fields.get("cooldown_bypass_delta") is None
            else float(fields["cooldown_bypass_delta"])
        ),
        "expire_at_half_end": bool(fields.get("expire_at_half_end")),
    }
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        row = conn.execute(UPDATE_RULE, payload).mappings().first()
    return dict(row) if row else None


def load_runtime_bundle(dsn: str) -> dict[str, Any]:
    """Thresholds, weight overrides, confirmation/cooldown rules, extra conditions."""
    return {
        "thresholds": list_thresholds(dsn),
        "weights": list_weight_overrides(dsn),
        "rules": list_admin_rules(dsn),
        "conditions": list_strategy_conditions(dsn),
    }


LIST_PRESETS = text(
    """
    SELECT name, payload
    FROM strategy_presets
    WHERE strategy_key = :strategy_key
    ORDER BY name
    """
)

GET_PRESET = text(
    """
    SELECT payload
    FROM strategy_presets
    WHERE strategy_key = :strategy_key AND name = :name
    """
)

UPSERT_PRESET = text(
    """
    INSERT INTO strategy_presets (strategy_key, name, payload, updated_at)
    VALUES (:strategy_key, :name, CAST(:payload AS jsonb), NOW())
    ON CONFLICT (strategy_key, name) DO UPDATE SET
        payload = EXCLUDED.payload,
        updated_at = NOW()
    """
)


def list_saved_presets(dsn: str, strategy_key: str) -> list[str]:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = conn.execute(LIST_PRESETS, {"strategy_key": strategy_key}).mappings().all()
    return [str(row["name"]) for row in rows]


def get_saved_preset(dsn: str, strategy_key: str, name: str) -> dict[str, float] | None:
    bundle = get_saved_preset_bundle(dsn, strategy_key, name)
    if bundle is None:
        return None
    return bundle[0]


def get_saved_preset_bundle(
    dsn: str, strategy_key: str, name: str
) -> tuple[dict[str, float], list[dict[str, Any]] | None] | None:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = (
            conn.execute(GET_PRESET, {"strategy_key": strategy_key, "name": name})
            .mappings()
            .first()
        )
    if row is None:
        return None
    return parse_preset_payload(row["payload"])


def parse_preset_payload(
    payload: Any,
) -> tuple[dict[str, float], list[dict[str, Any]] | None]:
    """Weights plus optional extra-condition snapshot.

    Legacy payloads were a flat ``{coeff: float}`` map. New snapshots wrap
    ``weights`` and ``conditions``. ``conditions is None`` means the preset
    predates extra conditions and apply should leave the live rows alone.
    """
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        return {}, None
    conditions: list[dict[str, Any]] | None = None
    raw_weights: Any = payload
    if "weights" in payload or "conditions" in payload:
        raw_weights = payload.get("weights") or {}
        raw_conditions = payload.get("conditions")
        if isinstance(raw_conditions, list):
            conditions = [dict(item) for item in raw_conditions if isinstance(item, dict)]
        else:
            conditions = []
    out: dict[str, float] = {}
    if isinstance(raw_weights, dict):
        for key, value in raw_weights.items():
            try:
                out[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    return out, conditions


GET_BOARD_SETTINGS = text(
    """
    SELECT sweet_spot_ht1_start, sweet_spot_ht1_end,
           sweet_spot_ht2_start, sweet_spot_ht2_end,
           sweet_spot_include_injury
    FROM board_settings
    WHERE id = 1
    """
)

UPSERT_BOARD_SETTINGS = text(
    """
    INSERT INTO board_settings (
        id,
        sweet_spot_ht1_start,
        sweet_spot_ht1_end,
        sweet_spot_ht2_start,
        sweet_spot_ht2_end,
        sweet_spot_include_injury,
        updated_at
    )
    VALUES (
        1,
        :ht1_start,
        :ht1_end,
        :ht2_start,
        :ht2_end,
        :include_injury_time,
        NOW()
    )
    ON CONFLICT (id) DO UPDATE SET
        sweet_spot_ht1_start = EXCLUDED.sweet_spot_ht1_start,
        sweet_spot_ht1_end = EXCLUDED.sweet_spot_ht1_end,
        sweet_spot_ht2_start = EXCLUDED.sweet_spot_ht2_start,
        sweet_spot_ht2_end = EXCLUDED.sweet_spot_ht2_end,
        sweet_spot_include_injury = EXCLUDED.sweet_spot_include_injury,
        updated_at = NOW()
    """
)


def _clamp_board_minute(value: Any, default: int) -> int:
    try:
        minute = int(value)
    except (TypeError, ValueError):
        minute = default
    return max(0, min(130, minute))


def normalize_board_settings(fields: dict[str, Any] | None = None) -> dict[str, Any]:
    data = fields or {}
    ht1 = sorted(
        (
            _clamp_board_minute(data.get("ht1_start"), 28),
            _clamp_board_minute(data.get("ht1_end"), 44),
        )
    )
    ht2 = sorted(
        (
            _clamp_board_minute(data.get("ht2_start"), 72),
            _clamp_board_minute(data.get("ht2_end"), 88),
        )
    )
    return {
        "ht1_start": ht1[0],
        "ht1_end": ht1[1],
        "ht2_start": ht2[0],
        "ht2_end": ht2[1],
        "include_injury_time": bool(data.get("include_injury_time", False)),
    }


def get_board_settings(dsn: str) -> dict[str, Any]:
    defaults = normalize_board_settings()
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = conn.execute(GET_BOARD_SETTINGS).mappings().first()
    if row is None:
        return defaults
    return normalize_board_settings(
        {
            "ht1_start": row["sweet_spot_ht1_start"],
            "ht1_end": row["sweet_spot_ht1_end"],
            "ht2_start": row["sweet_spot_ht2_start"],
            "ht2_end": row["sweet_spot_ht2_end"],
            "include_injury_time": row["sweet_spot_include_injury"],
        }
    )


def upsert_board_settings(dsn: str, fields: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_board_settings(fields)
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(UPSERT_BOARD_SETTINGS, payload)
    return payload


def upsert_saved_preset(
    dsn: str,
    strategy_key: str,
    name: str,
    payload: dict[str, Any],
) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT_PRESET,
            {
                "strategy_key": strategy_key,
                "name": name,
                "payload": json.dumps(payload),
            },
        )


LIST_CONDITIONS = text(
    """
    SELECT id, strategy_slot, enabled, left_scope, left_metric, operator,
           right_kind, right_scope, right_metric, right_value, multiplier, sort_order
    FROM strategy_conditions
    ORDER BY strategy_slot, sort_order, id
    """
)

DELETE_SLOT_CONDITIONS = text(
    """
    DELETE FROM strategy_conditions
    WHERE strategy_slot = :slot
    """
)

INSERT_CONDITION = text(
    """
    INSERT INTO strategy_conditions (
        strategy_slot, enabled, left_scope, left_metric, operator,
        right_kind, right_scope, right_metric, right_value, multiplier, sort_order
    )
    VALUES (
        :slot, :enabled, :left_scope, :left_metric, :operator,
        :right_kind, :right_scope, :right_metric, :right_value, :multiplier, :sort_order
    )
    """
)


def list_strategy_conditions(dsn: str) -> dict[int, list[dict[str, Any]]]:
    eng = sync_engine(dsn)
    try:
        with eng.connect() as conn:
            rows = conn.execute(LIST_CONDITIONS).mappings().all()
    except Exception:  # noqa: BLE001 — table may be missing before migration 0015
        return {}
    out: dict[int, list[dict[str, Any]]] = {slot: [] for slot in KEY_BY_SLOT}
    for row in rows:
        slot = int(row["strategy_slot"])
        if slot not in KEY_BY_SLOT:
            continue
        out.setdefault(slot, []).append(
            {
                "left_scope": str(row["left_scope"]),
                "left_metric": str(row["left_metric"]),
                "operator": str(row["operator"]),
                "right_kind": str(row["right_kind"] or "value"),
                "right_scope": str(row["right_scope"] or "opponent"),
                "right_metric": str(row["right_metric"] or ""),
                "right_value": float(row["right_value"] or 0),
                "multiplier": float(row["multiplier"] or 1),
                "enabled": bool(row["enabled"]),
            }
        )
    return out


def replace_strategy_conditions(
    dsn: str, slot: int, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(DELETE_SLOT_CONDITIONS, {"slot": slot})
        for index, row in enumerate(rows):
            conn.execute(
                INSERT_CONDITION,
                {
                    "slot": slot,
                    "enabled": bool(row.get("enabled", True)),
                    "left_scope": str(row["left_scope"]),
                    "left_metric": str(row["left_metric"]),
                    "operator": str(row["operator"]),
                    "right_kind": str(row.get("right_kind") or "value"),
                    "right_scope": row.get("right_scope"),
                    "right_metric": row.get("right_metric"),
                    "right_value": float(row.get("right_value") or 0),
                    "multiplier": float(row.get("multiplier") or 1),
                    "sort_order": index,
                },
            )
    return list_strategy_conditions(dsn).get(slot, [])
