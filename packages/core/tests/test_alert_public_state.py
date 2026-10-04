"""Public Monitoring / Confirmed / Expired labels for the live strip."""

from __future__ import annotations

from kalchas_core.alert_outcomes import (
    PUBLIC_CONFIRMED,
    PUBLIC_EXPIRED,
    PUBLIC_MONITORING,
    AlertOutcomeEvaluator,
    GoalEvent,
    evaluate_public_signal,
    score_public_signal,
)


def _score(
    *,
    alert_minute: int = 20,
    alert_score: str = "0-0",
    strategy_slot: int = 4,
    strategy_key: str = "delta_5min",
    trigger_team: str | None = "away",
    current_minute: int | None = 21,
    current_score: str = "0-0",
    status_short: str | None = "1H",
    goals: list[GoalEvent] | None = None,
) -> str:
    return evaluate_public_signal(
        alert_minute=alert_minute,
        alert_score=alert_score,
        strategy_slot=strategy_slot,
        strategy_key=strategy_key,
        trigger_team=trigger_team,
        current_minute=current_minute,
        current_score=current_score,
        status_short=status_short,
        goals=goals or (),
    )


class TestEvaluatePublicSignal:
    def test_still_in_window_without_goal_is_monitoring(self) -> None:
        assert _score() == PUBLIC_MONITORING

    def test_goal_inside_window_is_confirmed(self) -> None:
        assert (
            _score(
                current_minute=28,
                current_score="0-1",
                goals=[GoalEvent(minute=27, side="away")],
            )
            == PUBLIC_CONFIRMED
        )

    def test_pre_alert_goal_does_not_confirm(self) -> None:
        assert (
            _score(
                current_minute=22,
                current_score="1-0",
                goals=[GoalEvent(minute=12, side="home")],
            )
            == PUBLIC_MONITORING
        )

    def test_window_closed_without_goal_is_expired(self) -> None:
        assert _score(current_minute=43, current_score="0-0") == PUBLIC_EXPIRED

    def test_goal_after_window_is_expired(self) -> None:
        assert (
            _score(
                current_minute=50,
                current_score="0-1",
                goals=[GoalEvent(minute=45, side="away")],
            )
            == PUBLIC_EXPIRED
        )

    def test_omega_ignores_opponent_goal(self) -> None:
        assert (
            _score(
                strategy_slot=6,
                strategy_key="omega",
                trigger_team="home",
                current_minute=28,
                current_score="0-1",
                goals=[GoalEvent(minute=27, side="away")],
            )
            == PUBLIC_MONITORING
        )

    def test_omega_confirms_trigger_team_goal(self) -> None:
        assert (
            _score(
                strategy_slot=6,
                strategy_key="omega",
                trigger_team="home",
                current_minute=28,
                current_score="1-0",
                goals=[GoalEvent(minute=27, side="home")],
            )
            == PUBLIC_CONFIRMED
        )

    def test_finished_nil_nil_is_expired(self) -> None:
        assert (
            _score(
                current_minute=90,
                current_score="0-0",
                status_short="FT",
            )
            == PUBLIC_EXPIRED
        )

    def test_missing_clock_stays_monitoring(self) -> None:
        assert _score(current_minute=None) == PUBLIC_MONITORING

    def test_injected_rules_are_used(self) -> None:
        from kalchas_core.alert_outcomes import StrategyRule

        short = StrategyRule(4, "Δ(5min)", success_window_minutes=5, expiration_buffer_minutes=0)
        state = evaluate_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            current_minute=26,
            current_score="0-0",
            status_short="1H",
            goals=(),
            evaluator=AlertOutcomeEvaluator(rules=(short,)),
        )
        assert state == PUBLIC_EXPIRED

    def test_expire_at_half_end_closes_at_ht(self) -> None:
        from kalchas_core.alert_outcomes import StrategyRule

        rule = StrategyRule(
            4,
            "Δ(5min)",
            success_window_minutes=40,
            expiration_buffer_minutes=0,
            expire_at_half_end=True,
        )
        state = evaluate_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            current_minute=45,
            current_score="0-0",
            status_short="HT",
            goals=(),
            evaluator=AlertOutcomeEvaluator(rules=(rule,)),
        )
        assert state == PUBLIC_EXPIRED

    def test_expire_at_half_end_keeps_first_half_monitoring(self) -> None:
        from kalchas_core.alert_outcomes import StrategyRule

        rule = StrategyRule(
            4,
            "Δ(5min)",
            success_window_minutes=40,
            expiration_buffer_minutes=0,
            expire_at_half_end=True,
        )
        state = evaluate_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            current_minute=38,
            current_score="0-0",
            status_short="1H",
            goals=(),
            evaluator=AlertOutcomeEvaluator(rules=(rule,)),
        )
        assert state == PUBLIC_MONITORING

    def test_expire_at_half_end_keeps_first_half_added_time_monitoring(self) -> None:
        from kalchas_core.alert_outcomes import StrategyRule

        rule = StrategyRule(
            4,
            "Δ(5min)",
            success_window_minutes=40,
            expiration_buffer_minutes=0,
            expire_at_half_end=True,
        )
        state = evaluate_public_signal(
            alert_minute=9,
            alert_score="0-0",
            strategy_slot=4,
            current_minute=47,
            current_score="0-0",
            status_short="1H",
            goals=(),
            evaluator=AlertOutcomeEvaluator(rules=(rule,)),
        )
        assert state == PUBLIC_MONITORING

    def test_expire_at_half_end_confirms_added_time_goal(self) -> None:
        from kalchas_core.alert_outcomes import StrategyRule

        rule = StrategyRule(
            4,
            "Δ(5min)",
            success_window_minutes=40,
            expiration_buffer_minutes=0,
            expire_at_half_end=True,
        )
        state = evaluate_public_signal(
            alert_minute=9,
            alert_score="0-0",
            strategy_slot=4,
            current_minute=47,
            current_score="1-0",
            status_short="1H",
            goals=[GoalEvent(minute=47, side="home")],
            evaluator=AlertOutcomeEvaluator(rules=(rule,)),
        )
        assert state == PUBLIC_CONFIRMED

    def test_expire_at_half_end_rejects_second_half_goal(self) -> None:
        from kalchas_core.alert_outcomes import StrategyRule

        rule = StrategyRule(
            4,
            "Δ(5min)",
            success_window_minutes=40,
            expiration_buffer_minutes=0,
            expire_at_half_end=True,
        )
        state = evaluate_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            current_minute=60,
            current_score="0-1",
            status_short="2H",
            goals=[GoalEvent(minute=55, side="away")],
            evaluator=AlertOutcomeEvaluator(rules=(rule,)),
        )
        assert state == PUBLIC_EXPIRED

    def test_ht_zero_clock_confirms_from_live_score_without_events(self) -> None:
        assert (
            _score(
                strategy_slot=6,
                strategy_key="omega",
                trigger_team="away",
                alert_minute=44,
                alert_score="0-0",
                current_minute=0,
                current_score="0-1",
                status_short="HT",
                goals=[],
            )
            == PUBLIC_CONFIRMED
        )
        assert (
            _score(
                alert_minute=43,
                alert_score="0-1",
                current_minute=0,
                current_score="0-2",
                status_short="HT",
                goals=[],
            )
            == PUBLIC_CONFIRMED
        )

    def test_same_minute_goal_confirms(self) -> None:
        assert (
            _score(
                alert_minute=44,
                current_minute=0,
                current_score="0-1",
                status_short="HT",
                goals=[GoalEvent(minute=44, side="away")],
            )
            == PUBLIC_CONFIRMED
        )

    def test_ht_zero_stamped_goal_confirms(self) -> None:
        assert (
            _score(
                alert_minute=44,
                current_minute=0,
                current_score="0-1",
                status_short="HT",
                goals=[GoalEvent(minute=0, side="away")],
            )
            == PUBLIC_CONFIRMED
        )

    def test_ht_score_delta_does_not_confirm_omega_opponent(self) -> None:
        assert (
            _score(
                strategy_slot=6,
                strategy_key="omega",
                trigger_team="home",
                alert_minute=44,
                alert_score="0-0",
                current_minute=0,
                current_score="0-1",
                status_short="HT",
                goals=[],
            )
            == PUBLIC_MONITORING
        )

    def test_expire_at_half_end_closes_when_ht_clock_is_zero(self) -> None:
        from kalchas_core.alert_outcomes import StrategyRule

        rule = StrategyRule(
            4,
            "Δ(5min)",
            success_window_minutes=40,
            expiration_buffer_minutes=0,
            expire_at_half_end=True,
        )
        state = evaluate_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            current_minute=0,
            current_score="0-0",
            status_short="HT",
            goals=(),
            evaluator=AlertOutcomeEvaluator(rules=(rule,)),
        )
        assert state == PUBLIC_EXPIRED

    def test_expire_at_half_end_confirms_same_half_goal(self) -> None:
        from kalchas_core.alert_outcomes import StrategyRule

        rule = StrategyRule(
            4,
            "Δ(5min)",
            success_window_minutes=40,
            expiration_buffer_minutes=0,
            expire_at_half_end=True,
        )
        state = evaluate_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            current_minute=38,
            current_score="0-1",
            status_short="1H",
            goals=[GoalEvent(minute=27, side="away")],
            evaluator=AlertOutcomeEvaluator(rules=(rule,)),
        )
        assert state == PUBLIC_CONFIRMED


class TestScorePublicSignal:
    def test_confirmed_includes_scoring_side(self) -> None:
        signal = score_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            strategy_key="delta_5min",
            trigger_team="away",
            current_minute=28,
            current_score="0-1",
            status_short="1H",
            goals=[GoalEvent(minute=27, side="away")],
        )
        assert signal.state == PUBLIC_CONFIRMED
        assert signal.kind == "confirmed"
        assert signal.scoring_side == "away"
        assert signal.goal_minute == 27

    def test_window_closed_is_no_goal(self) -> None:
        signal = score_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            strategy_key="delta_5min",
            trigger_team="away",
            current_minute=43,
            current_score="0-0",
            status_short="1H",
            goals=(),
        )
        assert signal.state == PUBLIC_EXPIRED
        assert signal.kind == "no_goal"

    def test_late_goal_is_too_late(self) -> None:
        signal = score_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            strategy_key="delta_5min",
            trigger_team="away",
            current_minute=50,
            current_score="0-1",
            status_short="2H",
            goals=[GoalEvent(minute=45, side="away")],
        )
        assert signal.state == PUBLIC_EXPIRED
        assert signal.kind == "too_late"
        assert signal.goal_minute == 45

    def test_omega_opponent_after_window_is_counter(self) -> None:
        signal = score_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=6,
            strategy_key="omega",
            trigger_team="home",
            current_minute=43,
            current_score="0-1",
            status_short="1H",
            goals=[GoalEvent(minute=27, side="away")],
        )
        assert signal.state == PUBLIC_EXPIRED
        assert signal.kind == "counter_scored"
        assert signal.opponent_side == "away"

    def test_half_end_kind(self) -> None:
        from kalchas_core.alert_outcomes import StrategyRule

        rule = StrategyRule(
            4,
            "Δ(5min)",
            success_window_minutes=40,
            expiration_buffer_minutes=0,
            expire_at_half_end=True,
        )
        signal = score_public_signal(
            alert_minute=20,
            alert_score="0-0",
            strategy_slot=4,
            current_minute=45,
            current_score="0-0",
            status_short="HT",
            goals=(),
            evaluator=AlertOutcomeEvaluator(rules=(rule,)),
        )
        assert signal.state == PUBLIC_EXPIRED
        assert signal.kind == "half_ended"
