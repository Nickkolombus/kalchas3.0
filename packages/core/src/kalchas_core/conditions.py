"""Strategy extra-condition rows and the Fire-gate evaluator.

Native strategy thresholds still decide whether a side is eligible. Extra
rows are a second AND filter on that decision. Board, preview, and Telegram
all call ``passes_extra_conditions`` through the runner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kalchas_core.match import Side
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


CONDITION_SCOPES: tuple[tuple[str, str], ...] = (
    ("triggering", "Triggering"),
    ("opponent", "Opponent"),
    ("either", "Either"),
    ("sum", "Sum"),
    ("both", "Both"),
    ("home", "Home"),
    ("away", "Away"),
    ("favourite", "Favourite"),
    ("underdog", "Underdog"),
)

CONDITION_METRICS: tuple[tuple[str, str], ...] = (
    ("npei", "ΦI"),
    ("rule_of_three", "UrG"),
    ("delta_5min", "Δ5′"),
    ("pressure_index", "Δ10′"),
    ("delta_goal", "L Bar"),
    ("omega", "Ω"),
    ("kscore", "K Index"),
    ("shots_on_target", "SOT"),
    ("shots_off_target", "SOFF"),
    ("attacks", "ATT"),
    ("dangerous_attacks", "DA"),
    ("corners", "CRN"),
    ("possession", "POS"),
    ("yellow_cards", "YC"),
    ("red_cards", "RC"),
    ("goals", "Goals"),
    ("kickoff_odds", "Kickoff odds"),
    ("live_odds", "Live odds"),
)

CONDITION_OPERATORS: tuple[str, ...] = (">", ">=", "<", "<=", "=")

_VALID_SCOPES = frozenset(key for key, _label in CONDITION_SCOPES)
_VALID_METRICS = frozenset(key for key, _label in CONDITION_METRICS)
_LEGACY_METRIC = {
    "s1": "rule_of_three",
    "s2": "pressure_index",
    "s3": "delta_goal",
    "s4": "delta_5min",
    "s6": "omega",
    "s6_theta": "omega",
    "urg": "rule_of_three",
    "phi": "npei",
    "npei": "npei",
}

_EQ_TOL = 1e-6


@dataclass(frozen=True, slots=True)
class ExtraCondition:
    """One AND-gate row: left operand, operator, right operand."""

    left_scope: str
    left_metric: str
    operator: str
    right_kind: str
    right_scope: str
    right_metric: str
    right_value: float
    multiplier: float
    enabled: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "left_scope": self.left_scope,
            "left_metric": self.left_metric,
            "operator": self.operator,
            "right_kind": self.right_kind,
            "right_scope": self.right_scope,
            "right_metric": self.right_metric,
            "right_value": self.right_value,
            "multiplier": self.multiplier,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True)
class ConditionMatch:
    """Per-side metric map used by the extra-condition evaluator."""

    home: Mapping[str, float | None]
    away: Mapping[str, float | None]
    favourite: Side | None


def condition_catalog() -> dict[str, Any]:
    """Labels for the admin extra-conditions pane."""
    return {
        "scopes": [{"key": key, "label": label} for key, label in CONDITION_SCOPES],
        "metrics": [{"key": key, "label": label} for key, label in CONDITION_METRICS],
        "operators": list(CONDITION_OPERATORS),
        "logic": "AND",
    }


def favourite_from_kickoff(home_odds: float | None, away_odds: float | None) -> Side | None:
    """Lower kickoff decimal is the favourite. Equal or missing -> None."""
    if home_odds is None or away_odds is None:
        return None
    if home_odds < away_odds:
        return Side.HOME
    if away_odds < home_odds:
        return Side.AWAY
    return None


def extra_condition_from_row(raw: Mapping[str, Any]) -> ExtraCondition | None:
    """Parse one stored/admin row. Legacy stat_key rows become value comparisons."""
    if not isinstance(raw, Mapping):
        return None
    left_metric = _metric_key(raw.get("left_metric") or raw.get("stat_key") or raw.get("metric_key"))
    if not left_metric:
        return None
    left_scope = _scope_key(raw.get("left_scope") or raw.get("scope") or "triggering")
    operator = str(raw.get("operator") or ">=").strip()
    if operator not in _VALID_CONDITION_OPS:
        operator = ">="
    right_kind = str(raw.get("right_kind") or "").strip().lower()
    right_metric = _metric_key(raw.get("right_metric") or "")
    if right_kind not in {"value", "metric"}:
        right_kind = "metric" if right_metric else "value"
    if right_kind == "metric" and not right_metric:
        right_kind = "value"
    right_scope = _scope_key(raw.get("right_scope") or "opponent")
    try:
        right_value = float(
            raw.get("right_value", raw.get("value", raw.get("threshold", 0)))
        )
    except (TypeError, ValueError):
        right_value = 0.0
    if right_value != right_value:
        right_value = 0.0
    try:
        multiplier = float(raw.get("multiplier", 1) or 1)
    except (TypeError, ValueError):
        multiplier = 1.0
    if multiplier != multiplier:
        multiplier = 1.0
    return ExtraCondition(
        left_scope=left_scope,
        left_metric=left_metric,
        operator=operator,
        right_kind=right_kind,
        right_scope=right_scope,
        right_metric=right_metric or left_metric,
        right_value=right_value,
        multiplier=multiplier,
        enabled=bool(raw.get("enabled", True)),
    )


def prepare_extra_conditions(rows: Any) -> list[dict[str, Any]]:
    """Validate admin POST payloads before DB replace."""
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("conditions must be a JSON array")
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"condition at index {i} must be an object")
        parsed = extra_condition_from_row(raw)
        if parsed is None:
            raise ValueError(f"condition at index {i} is missing a metric")
        out.append(parsed.as_dict())
    return out


def normalize_extra_conditions(rows: list | None) -> list[dict[str, Any]]:
    """Read path: skip broken rows."""
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in rows:
        parsed = extra_condition_from_row(raw) if isinstance(raw, dict) else None
        if parsed is None:
            continue
        out.append(parsed.as_dict())
    return out


def passes_extra_conditions(
    rows: list | None,
    match: ConditionMatch,
    side: Side,
) -> bool:
    """True when every enabled extra row passes (AND). Empty list always passes."""
    if not rows:
        return True
    for raw in rows:
        parsed = extra_condition_from_row(raw) if not isinstance(raw, ExtraCondition) else raw
        if parsed is None or not parsed.enabled:
            continue
        if not _row_passes(parsed, match, side):
            return False
    return True


def _metric_key(raw: Any) -> str:
    key = str(raw or "").strip()
    mapped = _LEGACY_METRIC.get(key, key)
    return mapped if mapped in _VALID_METRICS else ""


def _scope_key(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    return key if key in _VALID_SCOPES else "triggering"


def _row_passes(row: ExtraCondition, match: ConditionMatch, side: Side) -> bool:
    if row.left_scope == "either":
        as_trigger = ExtraCondition(
            left_scope="triggering",
            left_metric=row.left_metric,
            operator=row.operator,
            right_kind=row.right_kind,
            right_scope=row.right_scope,
            right_metric=row.right_metric,
            right_value=row.right_value,
            multiplier=row.multiplier,
            enabled=True,
        )
        return _row_passes(as_trigger, match, Side.HOME) or _row_passes(
            as_trigger, match, Side.AWAY
        )
    if row.left_scope == "both":
        as_trigger = ExtraCondition(
            left_scope="triggering",
            left_metric=row.left_metric,
            operator=row.operator,
            right_kind=row.right_kind,
            right_scope=row.right_scope,
            right_metric=row.right_metric,
            right_value=row.right_value,
            multiplier=row.multiplier,
            enabled=True,
        )
        return _row_passes(as_trigger, match, Side.HOME) and _row_passes(
            as_trigger, match, Side.AWAY
        )
    left = _operand(row.left_scope, row.left_metric, match, side)
    right = _rhs(row, match, side)
    return _compare(row.operator, left, right)


def _rhs(row: ExtraCondition, match: ConditionMatch, side: Side) -> float | None:
    if row.right_kind == "metric":
        value = _operand(row.right_scope, row.right_metric, match, side)
        if value is None:
            return None
        return value * row.multiplier
    return row.right_value * row.multiplier


def _operand(scope: str, metric: str, match: ConditionMatch, subject: Side) -> float | None:
    if scope == "sum":
        home = _side_metric(match, Side.HOME, metric)
        away = _side_metric(match, Side.AWAY, metric)
        if home is None or away is None:
            return None
        return home + away
    resolved = _resolve_side(scope, subject, match.favourite)
    if resolved is None:
        return None
    return _side_metric(match, resolved, metric)


def _resolve_side(scope: str, subject: Side, favourite: Side | None) -> Side | None:
    if scope == "triggering":
        return subject
    if scope == "opponent":
        return subject.opponent
    if scope == "home":
        return Side.HOME
    if scope == "away":
        return Side.AWAY
    if scope == "favourite":
        return favourite
    if scope == "underdog":
        return None if favourite is None else favourite.opponent
    return None


def _side_metric(match: ConditionMatch, side: Side, metric: str) -> float | None:
    block = match.home if side is Side.HOME else match.away
    if metric not in _VALID_METRICS:
        return None
    value = block.get(metric)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compare(operator: str, left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    return abs(left - right) <= _EQ_TOL
