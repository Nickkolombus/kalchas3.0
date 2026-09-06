"""Strategy extra-condition row normalization.

Ported from `utils/condition_evaluator.py` (normalize / prepare only — not the
full runtime evaluator that walks match_data). Legacy Omega rows stored ``s6``
thresholds in degrees; values clearly above the linear range (>15) are
converted via ``degrees_to_slope``.
"""

from __future__ import annotations

from typing import Any

from kalchas_core.strategies.omega import degrees_to_slope

_VALID_CONDITION_OPS = frozenset({">", ">=", "<", "<=", "="})
_VALID_LOGIC_GROUPS = frozenset({"AND", "OR"})
_S6_DEGREE_CUTOFF = 15.0


def normalize_strategy_condition(
    row: dict[str, Any],
    *,
    k_scale: float = 0.5,
) -> dict[str, Any]:
    """Normalize one strategy_conditions row for display and evaluation."""
    out = dict(row)
    stat = str(out.get("stat_key") or "")
    try:
        val = float(out.get("value", 0))
    except (TypeError, ValueError):
        return out
    if stat == "s6" and val > _S6_DEGREE_CUTOFF:
        out["value"] = round(degrees_to_slope(val, k_scale), 3)
    return out


def prepare_strategy_conditions_for_save(
    rows: Any,
    *,
    k_scale: float = 0.5,
) -> list[dict[str, Any]]:
    """Validate and normalize admin POST payloads before DB replace."""
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("conditions must be a JSON array")

    out: list[dict[str, Any]] = []
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"condition at index {i} must be an object")
        stat_key = str(raw.get("stat_key") or "").strip()
        if not stat_key:
            raise ValueError(f"condition at index {i} is missing stat_key")
        scope = str(raw.get("scope") or "either").strip() or "either"
        operator = str(raw.get("operator") or ">=").strip()
        if operator not in _VALID_CONDITION_OPS:
            operator = ">="
        logic_group = str(raw.get("logic_group") or "AND").strip().upper()
        if logic_group not in _VALID_LOGIC_GROUPS:
            logic_group = "AND"
        try:
            value = float(raw.get("value", 0))
        except (TypeError, ValueError):
            value = 0.0
        if value != value:  # NaN
            value = 0.0
        row = {
            "stat_key": stat_key[:50],
            "scope": scope[:20],
            "operator": operator[:5],
            "value": value,
            "logic_group": logic_group[:3],
            "enabled": bool(raw.get("enabled", True)),
            "team_specific": bool(raw.get("team_specific", False)),
        }
        out.append(normalize_strategy_condition(row, k_scale=k_scale))
    return out


def normalize_strategy_conditions(
    rows: list | None,
    *,
    k_scale: float = 0.5,
) -> list[dict[str, Any]]:
    """Normalize DB/read paths; tolerate legacy rows, skip invalid entries."""
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        if not str(raw.get("stat_key") or "").strip():
            continue
        out.append(normalize_strategy_condition(dict(raw), k_scale=k_scale))
    return out
