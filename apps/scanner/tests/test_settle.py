"""Scanner settle of public Confirmed / Expired snapshots."""

from __future__ import annotations

from kalchas_core.alert_outcomes import (
    PUBLIC_CONFIRMED,
    PUBLIC_EXPIRED,
    PUBLIC_MONITORING,
    AlertOutcomeEvaluator,
    GoalEvent,
)
from kalchas_scanner.settle import goals_from_ssot, outcome_snapshot


def test_goals_from_ssot_skips_cards() -> None:
    events = [
        {"event_type": "goal", "minute": 44, "side": "away"},
        {"event_type": "card", "minute": 30, "side": "home"},
    ]
    assert goals_from_ssot(events) == [GoalEvent(minute=44, side="away")]


def test_ht_score_change_settles_confirmed() -> None:
    snap = outcome_snapshot(
        {
            "id": 11,
            "strategy_slot": 6,
            "strategy_key": "omega",
            "team": "away",
            "minute": 44,
            "score": "0-0",
            "home_team": "Home",
            "away_team": "Away",
            "payload": {"league": "CONCACAF"},
        },
        current_minute=0,
        current_score="0-1",
        status_short="HT",
        goals=[],
        evaluator=AlertOutcomeEvaluator(),
    )
    assert snap is not None
    assert snap["state"] == PUBLIC_CONFIRMED
    assert snap["detail"]["settle_score"] == "0-1"
    assert snap["detail"]["settle_minute"] == 45
    assert snap["detail"]["league"] == "CONCACAF"


def test_still_in_window_does_not_settle() -> None:
    snap = outcome_snapshot(
        {
            "id": 12,
            "strategy_slot": 4,
            "strategy_key": "delta_5min",
            "team": "away",
            "minute": 20,
            "score": "0-0",
            "payload": {},
        },
        current_minute=21,
        current_score="0-0",
        status_short="1H",
        goals=[],
        evaluator=AlertOutcomeEvaluator(),
    )
    assert snap is None


def test_closed_window_settles_expired() -> None:
    snap = outcome_snapshot(
        {
            "id": 13,
            "strategy_slot": 4,
            "strategy_key": "delta_5min",
            "team": "away",
            "minute": 20,
            "score": "0-0",
            "payload": {},
        },
        current_minute=50,
        current_score="0-0",
        status_short="2H",
        goals=[],
        evaluator=AlertOutcomeEvaluator(),
    )
    assert snap is not None
    assert snap["state"] == PUBLIC_EXPIRED
    assert snap["decision"] == "expired"


def test_frozen_feed_settles_expired() -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    snap = outcome_snapshot(
        {
            "id": 15,
            "strategy_slot": 4,
            "strategy_key": "delta_5min",
            "team": "away",
            "minute": 70,
            "score": "3-1",
            "payload": {},
            "created_at": now - timedelta(minutes=612),
        },
        current_minute=70,
        current_score="3-1",
        status_short="2H",
        goals=[],
        evaluator=AlertOutcomeEvaluator(),
    )
    assert snap is not None
    assert snap["state"] == PUBLIC_EXPIRED


def test_admin_checkbox_off_confirms_any_goal() -> None:
    from kalchas_core.alert_outcomes import StrategyRule

    rules = (StrategyRule(6, "Omega", team_specific=False),)
    snap = outcome_snapshot(
        {
            "id": 14,
            "strategy_slot": 6,
            "strategy_key": "omega",
            "team": "home",
            "minute": 20,
            "score": "0-0",
            "payload": {},
        },
        current_minute=28,
        current_score="0-1",
        status_short="1H",
        goals=[GoalEvent(minute=27, side="away")],
        evaluator=AlertOutcomeEvaluator(rules=rules),
    )
    assert snap is not None
    assert snap["state"] == PUBLIC_CONFIRMED


def test_public_labels_unchanged() -> None:
    assert PUBLIC_MONITORING == "Monitoring"
    assert PUBLIC_CONFIRMED == "Confirmed"
    assert PUBLIC_EXPIRED == "Expired"
