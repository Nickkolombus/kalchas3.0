"""Strategy condition value normalization (Omega linear refactor)."""

from __future__ import annotations

import pytest
from kalchas_core.conditions import (
    normalize_strategy_condition,
    prepare_strategy_conditions_for_save,
)


def test_s6_degree_value_converted_to_accel() -> None:
    row = {"stat_key": "s6", "value": 20.0, "operator": ">"}
    out = normalize_strategy_condition(row, k_scale=15.0)
    assert out["value"] == 5.46


def test_s6_linear_value_unchanged() -> None:
    row = {"stat_key": "s6", "value": 5.5, "operator": ">"}
    out = normalize_strategy_condition(row, k_scale=15.0)
    assert out["value"] == 5.5


def test_s6_theta_not_converted() -> None:
    row = {"stat_key": "s6_theta", "value": 45.0, "operator": ">"}
    out = normalize_strategy_condition(row, k_scale=15.0)
    assert out["value"] == 45.0


def test_prepare_rejects_non_list() -> None:
    with pytest.raises(ValueError, match="JSON array"):
        prepare_strategy_conditions_for_save({})


def test_prepare_s6_slot6_row() -> None:
    rows = [
        {
            "stat_key": "s6",
            "scope": "triggering",
            "operator": ">",
            "value": 5.5,
            "logic_group": "AND",
            "team_specific": True,
        }
    ]
    out = prepare_strategy_conditions_for_save(rows, k_scale=1.2)
    assert out[0]["stat_key"] == "s6"
    assert out[0]["value"] == 5.5


def test_normalize_strategy_conditions_skips_invalid_and_converts_legacy_s6() -> None:
    from kalchas_core.conditions import normalize_strategy_conditions

    out = normalize_strategy_conditions(
        [
            {"stat_key": "s6", "value": 20.0},
            {"stat_key": "", "value": 1.0},
            "not-a-dict",
            {"stat_key": "npei", "value": 50.0},
        ],
        k_scale=15.0,
    )
    assert len(out) == 2
    assert out[0]["value"] == 5.46
    assert out[1]["stat_key"] == "npei"
    assert normalize_strategy_conditions(None) == []
    assert normalize_strategy_conditions({"x": 1}) == []  # type: ignore[arg-type]
