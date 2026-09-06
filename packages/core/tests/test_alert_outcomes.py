"""Alert outcome evaluator.

Ported behaviours from `tests/test_alert_outcome_evaluator.py`, plus pins for
hints, missing trigger_team, counter-scored at expiry, and the events path.
"""

from __future__ import annotations

import pytest
from kalchas_core.alert_outcomes import (
    ALERT_NAME_HINTS,
    DEFAULT_RULES,
    FALLBACK_RULE,
    AlertOutcomeEvaluator,
    AlertSnapshot,
    AlertState,
    GoalEvent,
    StrategyRule,
    half_from_minute,
    match_rule,
    parse_score,
)


@pytest.fixture
def evaluator() -> AlertOutcomeEvaluator:
    return AlertOutcomeEvaluator()


class TestParseScore:
    def test_happy_path(self) -> None:
        assert parse_score("2-1") == (2, 1)

    def test_empty_and_garbage(self) -> None:
        assert parse_score("") == (0, 0)
        assert parse_score(None) == (0, 0)
        assert parse_score("2") == (0, 0)
        assert parse_score("a-b") == (0, 0)


class TestMatchRule:
    def test_no_names_returns_fallback(self) -> None:
        assert match_rule(None, DEFAULT_RULES) is FALLBACK_RULE
        assert match_rule([], DEFAULT_RULES) is FALLBACK_RULE

    def test_substring_match_first_hit_wins(self) -> None:
        rule = match_rule(["Rule of 3"], DEFAULT_RULES)
        assert rule.strategy_slot == 1
        assert rule.infinite_ttl is True

    def test_hint_pressure_to_goal_resolves_slot_3(self) -> None:
        rule = match_rule(["Pressure to Goal (5m)"], DEFAULT_RULES)
        assert rule.strategy_slot == 3
        assert rule.strategy_name == "League Bar"

    def test_hint_omega_resolves_slot_6(self) -> None:
        assert match_rule(["Ω Surge"], DEFAULT_RULES).strategy_slot == 6
        assert match_rule(["Nephos Delta"], DEFAULT_RULES).strategy_slot == 6

    def test_unknown_name_falls_back(self) -> None:
        assert match_rule(["Completely Unknown"], DEFAULT_RULES) == FALLBACK_RULE

    def test_hints_table_is_non_empty(self) -> None:
        assert len(ALERT_NAME_HINTS) >= 10


class TestOnGoal:
    def test_goal_within_window(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_goal(30, 38, "0-0", "1-0")
        assert decision is not None
        assert decision.new_state is AlertState.CONFIRMED
        assert decision.should_notify is True
        assert "within 20m window" in decision.reason

    def test_goal_at_exact_window_edge(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_goal(40, 60, "0-0", "1-0")
        assert decision is not None
        assert decision.new_state is AlertState.CONFIRMED
        assert "delay: 20 min" in decision.reason

    def test_goal_outside_window(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_goal(30, 55, "0-0", "1-0")
        assert decision is not None
        assert decision.new_state is AlertState.FAILED_TOO_LATE
        assert "outside 20m window" in decision.reason

    def test_no_score_change(self, evaluator: AlertOutcomeEvaluator) -> None:
        assert evaluator.on_goal(30, 35, "0-0", "0-0") is None

    def test_team_specific_ignores_wrong_team(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_goal(
            30,
            35,
            "0-0",
            "0-1",
            scored_team="away",
            trigger_team="home",
            strategy_names=["Rule of 3"],
        )
        assert decision is None

    def test_team_specific_confirms_trigger_team(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_goal(
            30,
            35,
            "0-0",
            "1-0",
            scored_team="home",
            trigger_team="home",
            strategy_names=["Rule of 3"],
        )
        assert decision is not None
        assert decision.new_state is AlertState.CONFIRMED

    def test_team_specific_missing_trigger_team_stays_pending(
        self, evaluator: AlertOutcomeEvaluator
    ) -> None:
        decision = evaluator.on_goal(
            30,
            35,
            "0-0",
            "1-0",
            scored_team="home",
            trigger_team=None,
            strategy_names=["Rule of 3"],
        )
        assert decision is None

    def test_infinite_ttl_confirms_late_goal(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_goal(
            10,
            80,
            "0-0",
            "1-0",
            scored_team="home",
            trigger_team="home",
            strategy_names=["Rule of 3"],
        )
        assert decision is not None
        assert decision.new_state is AlertState.CONFIRMED

    def test_non_team_specific_ignores_inherited_trigger_team(self) -> None:
        """A non-team-specific rule must not filter on an inherited trigger_team."""
        rules = (StrategyRule(4, "Δ(5min)", team_specific=False),)
        ev = AlertOutcomeEvaluator(rules=rules)
        decision = ev.on_goal(
            30,
            35,
            "0-0",
            "0-1",
            scored_team="away",
            trigger_team="home",
            strategy_names=["Δ(5min)"],
        )
        assert decision is not None
        assert decision.new_state is AlertState.CONFIRMED

    def test_halftime_boundary(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_goal(45, 46, "0-0", "1-0")
        assert decision is not None
        assert decision.new_state is AlertState.CONFIRMED


class TestOnExpiration:
    def test_outside_window_plus_buffer(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_expiration(30, 53)
        assert decision is not None
        assert decision.new_state is AlertState.FAILED_EXPIRED

    def test_within_window(self, evaluator: AlertOutcomeEvaluator) -> None:
        assert evaluator.on_expiration(42, 48) is None

    def test_infinite_ttl_never_expires(self, evaluator: AlertOutcomeEvaluator) -> None:
        assert evaluator.on_expiration(10, 90, strategy_names=["Rule of 3"]) is None

    def test_counter_scored_at_expiry(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_expiration(
            30,
            55,
            strategy_names=["Omega"],
            trigger_team="home",
            opponent_goal_team="away",
            opponent_goal_minute=40,
        )
        assert decision is not None
        assert decision.new_state is AlertState.COUNTER_SCORED


class TestOnMatchEnd:
    def test_no_goal(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_match_end(40, 90, "0-0", "0-0")
        assert decision is not None
        assert decision.new_state is AlertState.FAILED_NO_GOAL
        assert "no goal after alert" in decision.reason.lower()

    def test_goal_without_trigger_team_too_late(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_match_end(40, 90, "0-0", "1-0")
        assert decision is not None
        assert decision.new_state is AlertState.FAILED_TOO_LATE

    def test_trigger_team_scored(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_match_end(
            73,
            90,
            "4-0",
            "4-1",
            strategy_names=["Δ(5min)"],
            trigger_team="away",
        )
        assert decision is not None
        assert decision.new_state is AlertState.CONFIRMED

    def test_opponent_scored_counter(self, evaluator: AlertOutcomeEvaluator) -> None:
        decision = evaluator.on_match_end(
            73,
            90,
            "4-0",
            "5-0",
            strategy_names=["Rule of 3"],
            trigger_team="away",
        )
        assert decision is not None
        assert decision.new_state is AlertState.COUNTER_SCORED


class TestMatchEndFromEvents:
    def test_trigger_goal_within_window_confirms(self, evaluator: AlertOutcomeEvaluator) -> None:
        alert = AlertSnapshot(
            alert_minute=30,
            alert_score="0-0",
            strategy_names=("Rule of 3",),
            trigger_team="home",
        )
        decision = evaluator.on_match_end_from_events(
            alert,
            [GoalEvent(35, "home"), GoalEvent(50, "away")],
            final_score="1-1",
            final_minute=90,
        )
        assert decision is not None
        assert decision.new_state is AlertState.CONFIRMED

    def test_opponent_only_is_counter_scored(self, evaluator: AlertOutcomeEvaluator) -> None:
        alert = AlertSnapshot(
            alert_minute=30,
            alert_score="0-0",
            strategy_names=("Rule of 3",),
            trigger_team="home",
        )
        decision = evaluator.on_match_end_from_events(
            alert,
            [GoalEvent(40, "away")],
            final_score="0-1",
            final_minute=90,
        )
        assert decision is not None
        assert decision.new_state is AlertState.COUNTER_SCORED

    def test_empty_events_falls_back_to_score_delta(self, evaluator: AlertOutcomeEvaluator) -> None:
        alert = AlertSnapshot(
            alert_minute=30,
            alert_score="0-0",
            strategy_names=("Rule of 3",),
            trigger_team="home",
        )
        decision = evaluator.on_match_end_from_events(
            alert,
            [],
            final_score="1-0",
            final_minute=90,
        )
        assert decision is not None
        assert decision.new_state is AlertState.CONFIRMED


class TestHalfFromMinute:
    def test_labels(self) -> None:
        assert half_from_minute(30) == "1st half"
        assert half_from_minute(60) == "2nd half"
        assert half_from_minute(95) == "Extra time 1st"
        assert half_from_minute(110) == "Extra time 2nd"


class TestDefaultRules:
    def test_slots_2_to_4_default_to_any_goal(self) -> None:
        by_slot = {r.strategy_slot: r for r in DEFAULT_RULES}
        assert by_slot[2].team_specific is False
        assert by_slot[3].team_specific is False
        assert by_slot[4].team_specific is False

    def test_rule_of_three_stays_team_specific(self) -> None:
        by_slot = {r.strategy_slot: r for r in DEFAULT_RULES}
        assert by_slot[1].team_specific is True
