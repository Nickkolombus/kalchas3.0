"""Extra-condition parsing and the Fire-gate evaluator."""

from __future__ import annotations


def test_prepare_extra_conditions_metric_vs_metric() -> None:
    from kalchas_core.conditions import prepare_extra_conditions

    rows = prepare_extra_conditions(
        [
            {
                "left_scope": "triggering",
                "left_metric": "corners",
                "operator": ">",
                "right_kind": "metric",
                "right_scope": "opponent",
                "right_metric": "corners",
                "multiplier": 3,
            }
        ]
    )
    assert rows[0]["left_metric"] == "corners"
    assert rows[0]["right_kind"] == "metric"
    assert rows[0]["multiplier"] == 3


def test_legacy_stat_key_becomes_value_row() -> None:
    from kalchas_core.conditions import extra_condition_from_row

    parsed = extra_condition_from_row(
        {"stat_key": "npei", "scope": "triggering", "operator": ">=", "value": 55}
    )
    assert parsed is not None
    assert parsed.left_metric == "npei"
    assert parsed.right_kind == "value"
    assert parsed.right_value == 55


def _match(*, home: dict, away: dict, favourite=None):
    from kalchas_core.conditions import ConditionMatch

    return ConditionMatch(home=home, away=away, favourite=favourite)


def test_phi_gate_blocks_low_efficiency_side() -> None:
    from kalchas_core.conditions import passes_extra_conditions
    from kalchas_core.match import Side

    rows = [
        {
            "left_scope": "triggering",
            "left_metric": "npei",
            "operator": ">=",
            "right_kind": "value",
            "right_value": 50,
        }
    ]
    match = _match(home={"npei": 62}, away={"npei": 20})
    assert passes_extra_conditions(rows, match, Side.HOME) is True
    assert passes_extra_conditions(rows, match, Side.AWAY) is False


def test_homemade_corners_ratio() -> None:
    from kalchas_core.conditions import passes_extra_conditions
    from kalchas_core.match import Side

    rows = [
        {
            "left_scope": "triggering",
            "left_metric": "corners",
            "operator": ">",
            "right_kind": "metric",
            "right_scope": "opponent",
            "right_metric": "corners",
            "multiplier": 3,
        }
    ]
    match = _match(home={"corners": 7}, away={"corners": 2})
    assert passes_extra_conditions(rows, match, Side.HOME) is True
    assert passes_extra_conditions(rows, match, Side.AWAY) is False


def test_and_requires_every_row() -> None:
    from kalchas_core.conditions import passes_extra_conditions
    from kalchas_core.match import Side

    rows = [
        {
            "left_scope": "triggering",
            "left_metric": "npei",
            "operator": ">=",
            "right_kind": "value",
            "right_value": 40,
        },
        {
            "left_scope": "triggering",
            "left_metric": "red_cards",
            "operator": "=",
            "right_kind": "value",
            "right_value": 0,
        },
    ]
    match = _match(home={"npei": 70, "red_cards": 1}, away={"npei": 70, "red_cards": 0})
    assert passes_extra_conditions(rows, match, Side.HOME) is False
    assert passes_extra_conditions(rows, match, Side.AWAY) is True


def test_favourite_scope_uses_kickoff() -> None:
    from kalchas_core.conditions import favourite_from_kickoff, passes_extra_conditions
    from kalchas_core.match import Side

    assert favourite_from_kickoff(1.6, 5.0) is Side.HOME
    rows = [
        {
            "left_scope": "favourite",
            "left_metric": "corners",
            "operator": ">=",
            "right_kind": "value",
            "right_value": 4,
        }
    ]
    match = _match(home={"corners": 5}, away={"corners": 1}, favourite=Side.HOME)
    assert passes_extra_conditions(rows, match, Side.AWAY) is True
    missing = _match(home={"corners": 5}, away={"corners": 1}, favourite=None)
    assert passes_extra_conditions(rows, missing, Side.HOME) is False


def test_empty_conditions_always_pass() -> None:
    from kalchas_core.conditions import passes_extra_conditions
    from kalchas_core.match import Side

    match = _match(home={}, away={})
    assert passes_extra_conditions([], match, Side.HOME) is True
    assert passes_extra_conditions(None, match, Side.HOME) is True
