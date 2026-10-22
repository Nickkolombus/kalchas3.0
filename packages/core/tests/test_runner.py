"""Strategy runner smoke test."""

from conftest import timeline_from
from kalchas_core.form import TeamForm
from kalchas_core.runner import (
    board_snapshot,
    evaluate_match,
    home_away_odds,
    live_home_away_odds,
)


def _form(scored: list[int], conceded: list[int]) -> TeamForm:
    return TeamForm(
        games_played=len(scored),
        goals_for=sum(scored),
        goals_against=sum(conceded),
        scored_by_game=tuple(scored),
        conceded_by_game=tuple(conceded),
    )


# Median scored 2 / conceded 1, and median scored 1 / conceded 2.
STRONG_FORM = _form([2, 2, 3, 1, 2, 0, 2], [1, 0, 1, 2, 1, 1, 0])
LEAKY_FORM = _form([1, 0, 1, 2, 1, 1, 0], [2, 2, 3, 1, 2, 0, 2])


def test_quiet_match_yields_no_candidates() -> None:
    timeline = timeline_from(
        {m: {"home": {}, "away": {}} for m in range(10, 21)}, current_minute=20
    )
    assert evaluate_match(timeline, slots=(1, 2, 4, 6)) == []


def test_busy_home_can_produce_pressure_candidate() -> None:
    timeline = timeline_from(
        {
            10: {"home": {}, "away": {}},
            20: {
                "home": {
                    "shots_on_target": 8,
                    "shots_off_target": 6,
                    "corners": 5,
                    "dangerous_attacks": 20,
                },
                "away": {},
            },
        },
        current_minute=20,
    )
    cands = evaluate_match(timeline, slots=(2,), thresholds={2: 10.0})
    assert any(c.strategy_slot == 2 for c in cands)


def test_rule_of_three_needs_three_shots_on_target() -> None:
    """2.2's `min_shots_on_target: 3` gate: a high unrealised-goals reading
    built mostly from shots off target should not fire alone."""
    timeline = timeline_from(
        {45: {"home": {"shots_on_target": 2, "shots_off_target": 30}, "away": {}}},
        current_minute=45,
    )
    assert evaluate_match(timeline, slots=(1,)) == []


def test_rule_of_three_fires_once_shot_gate_is_met() -> None:
    timeline = timeline_from(
        {45: {"home": {"shots_on_target": 3, "shots_off_target": 30}, "away": {}}},
        current_minute=45,
    )
    cands = evaluate_match(timeline, slots=(1,))
    assert any(c.strategy_slot == 1 for c in cands)


def test_board_snapshot_has_strategy_and_stat_lines() -> None:
    timeline = timeline_from(
        {
            10: {"home": {}, "away": {}},
            15: {"home": {}, "away": {}},
            20: {
                "home": {
                    "shots_on_target": 8,
                    "shots_off_target": 6,
                    "corners": 5,
                    "dangerous_attacks": 20,
                    "attacks": 40,
                    "possession": 58,
                },
                "away": {"possession": 42},
            },
        },
        current_minute=20,
    )
    board = board_snapshot(timeline, home_goals=1, away_goals=0)
    status = board["strategy_status"]
    assert "rule_of_three" in status
    assert "delta_goal" in status
    assert "kscore" in status
    assert status["omega"]["threshold"] == 30
    assert board["stat_lines"]["shots_on_target"]["home"] == 8
    assert isinstance(board["hot_score"], int)
    assert board["last_5min"]["sot"]["home"] == 8
    assert board["last_5min"]["start"] == 15
    assert board["last_10min"]["sot"]["home"] == 8
    assert board["last_10min"]["start"] == 10
    assert board["last_10min"]["end"] == 20


def _busy_board_timeline():
    return timeline_from(
        {
            10: {"home": {}, "away": {}},
            20: {
                "home": {
                    "shots_on_target": 8,
                    "shots_off_target": 6,
                    "corners": 5,
                    "dangerous_attacks": 20,
                    "attacks": 40,
                    "possession": 58,
                },
                "away": {"possession": 42},
            },
        },
        current_minute=20,
    )


def test_home_away_odds_prefers_nested_kickoff() -> None:
    assert home_away_odds({"kickoff": {"home": 1.9, "away": 4.2}, "home": 9.9, "away": 9.9}) == (
        1.9,
        4.2,
    )
    assert home_away_odds({"home": 2.1, "away": 3.4}) == (2.1, 3.4)
    assert home_away_odds({"kickoff": {"home": 1.8}}) == (None, None)
    assert home_away_odds({"home": 1.0, "away": 3.4}) == (None, None)
    assert home_away_odds(None) == (None, None)


def _quiet_timeline(minute: int):
    return timeline_from(
        {m: {"home": {}, "away": {}} for m in range(minute - 10, minute + 1)},
        current_minute=minute,
    )


def test_board_snapshot_form_bar_cell_is_goals_behind_pace() -> None:
    board = board_snapshot(
        _quiet_timeline(60),
        home_goals=0,
        away_goals=1,
        home_team_form=STRONG_FORM,
        away_team_form=LEAKY_FORM,
    )
    teams = board["strategy_status"]["delta_goal"]["teams"]
    # Home expects 2 (1.3 by 60'), has 0. Away expects 1 (0.7 by 60'), has 1: done.
    assert teams["home"]["value"] == 1.3
    assert teams["home"]["note"] == "0 of 2 expected · 1.3 by 60′"
    assert "delivered" not in teams["home"]
    assert teams["away"]["value"] == -0.3
    assert teams["away"]["delivered"] is True
    assert board["strategy_status"]["delta_goal"]["threshold"] == 1.0


def test_board_snapshot_form_bar_without_form_is_blank_not_zero() -> None:
    board = board_snapshot(_quiet_timeline(60), home_goals=1, away_goals=0)
    home = board["strategy_status"]["delta_goal"]["teams"]["home"]
    assert home["value"] is None
    assert home["note"] == "Not enough recent games"


def test_form_bar_fires_one_goal_behind_with_its_reading() -> None:
    cands = evaluate_match(
        _quiet_timeline(60),
        slots=(3,),
        home_team_form=STRONG_FORM,
        away_team_form=LEAKY_FORM,
    )
    assert [(c.strategy_slot, c.side.value, c.value) for c in cands] == [(3, "home", 1.33)]
    assert cands[0].detail["note"] == "0 of 2 expected · 1.3 by 60′"


def test_form_bar_pressure_conditions_only_bite_when_switched_on() -> None:
    """The seeded Δ10′/Δ5′/UrG/Omega rows start switched off."""
    row = {
        "left_scope": "triggering",
        "left_metric": "pressure_index",
        "operator": ">=",
        "right_kind": "value",
        "right_value": 75,
        "enabled": False,
    }
    kwargs = {
        "slots": (3,),
        "home_team_form": STRONG_FORM,
        "away_team_form": LEAKY_FORM,
    }
    off = evaluate_match(_quiet_timeline(60), conditions={3: [row]}, **kwargs)
    on = evaluate_match(_quiet_timeline(60), conditions={3: [{**row, "enabled": True}]}, **kwargs)
    assert len(off) == 1
    assert on == []


def _gated_delta5_timeline():
    """Home Δ5' = 1×2 + 4×0.5 = 4.0 and the corroboration gate passes."""
    return timeline_from(
        {
            15: {"home": {}, "away": {}},
            20: {
                "home": {"shots_on_target": 1, "dangerous_attacks": 4},
                "away": {"shots_on_target": 1},
            },
        },
        current_minute=20,
    )


def test_delta_5min_alert_respects_fire_threshold() -> None:
    timeline = _gated_delta5_timeline()
    assert evaluate_match(timeline, slots=(4,), thresholds={4: 6.0}) == []
    cands = evaluate_match(timeline, slots=(4,), thresholds={4: 3.0})
    assert len(cands) == 1
    assert cands[0].strategy_slot == 4
    assert cands[0].value == 4.0


def test_admin_fire_thresholds_silence_alerts_below_the_bar() -> None:
    """UrG, PI, Form Bar, Δ5', and K-Score all honor the admin fire number.

    Omega is excluded: its fire slider is unused; it gates on formula weights.
    """
    timeline = _busy_board_timeline()
    silent = evaluate_match(
        timeline,
        home_goals=1,
        away_goals=0,
        slots=(1, 2, 3, 4, 7),
        thresholds={1: 999.0, 2: 999.0, 3: 999.0, 4: 999.0, 7: 999.0},
    )
    assert silent == []
    pi_cands = evaluate_match(timeline, slots=(2,), thresholds={2: 10.0})
    assert any(c.strategy_slot == 2 for c in pi_cands)


def test_live_home_away_odds_reads_nested_live() -> None:
    assert live_home_away_odds({"live": {"home": 2.1, "away": 3.4}}) == (2.1, 3.4)
    assert live_home_away_odds({"kickoff": {"home": 1.5, "away": 6.0}}) == (None, None)


def test_extra_phi_condition_blocks_delta5_alert_and_board_fire() -> None:
    timeline = _gated_delta5_timeline()
    rows = [
        {
            "left_scope": "triggering",
            "left_metric": "npei",
            "operator": ">=",
            "right_kind": "value",
            "right_value": 90,
        }
    ]
    conditions = {4: rows}
    native = evaluate_match(timeline, slots=(4,), thresholds={4: 3.0})
    assert len(native) == 1
    blocked = evaluate_match(timeline, slots=(4,), thresholds={4: 3.0}, conditions=conditions)
    assert blocked == []
    board = board_snapshot(timeline, thresholds={4: 3.0}, conditions=conditions)
    home = board["strategy_status"]["delta_5min"]["teams"]["home"]
    assert home["value"] == 4.0
    assert "triggered" not in home


def test_extra_conditions_do_not_invent_a_fire() -> None:
    timeline = timeline_from(
        {m: {"home": {}, "away": {}} for m in range(10, 21)}, current_minute=20
    )
    rows = [
        {
            "left_scope": "triggering",
            "left_metric": "corners",
            "operator": ">=",
            "right_kind": "value",
            "right_value": 0,
        }
    ]
    assert evaluate_match(timeline, slots=(4,), conditions={4: rows}) == []
    board = board_snapshot(timeline, conditions={4: rows})
    assert not board["strategy_status"]["delta_5min"]["teams"]["home"].get("triggered")
