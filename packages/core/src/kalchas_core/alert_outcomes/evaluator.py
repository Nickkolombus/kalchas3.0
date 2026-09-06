"""Pure alert-outcome decisions.

Ported from `utils/alert_outcome_evaluator.py`. Removed: the 60s Postgres
rules cache, the process singleton, SSOT / FSM lookups inside
`evaluate_match_end`, and the dead `_format_minute_with_half` helper
(wrong for second-half minutes; notification text lives in the tracker).

Callers inject the rule set. The finished-match check stays in the adapter
layer; once a match is known finished, call `on_match_end_from_events` or
`on_match_end_from_score_delta` with the pre-fetched data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from kalchas_core.alert_outcomes.rules import (
    DEFAULT_RULES,
    StrategyRule,
    match_rule,
)
from kalchas_core.alert_outcomes.score import parse_score
from kalchas_core.alert_outcomes.states import AlertState, OutcomeDecision


@dataclass(frozen=True, slots=True)
class GoalEvent:
    """One goal after an alert, as the match-end event path sees it."""

    minute: int
    side: str  # "home" | "away" | ""


@dataclass(frozen=True, slots=True)
class AlertSnapshot:
    """The fields the match-end helpers need from an alert record."""

    alert_minute: int
    alert_score: str
    strategy_names: tuple[str, ...] = ()
    trigger_team: str | None = None
    opponent_goal_team: str | None = None
    opponent_goal_minute: int | None = None


@dataclass
class AlertOutcomeEvaluator:
    """Single source of truth for alert confirmation / failure decisions.

    Rules are injected at construction. Pass `DEFAULT_RULES` (or a DB-loaded
    sequence ordered by `strategy_slot`) — the evaluator never opens a
    connection itself.
    """

    rules: Sequence[StrategyRule] = field(default_factory=lambda: DEFAULT_RULES)

    def rule_for(self, strategy_names: Sequence[str] | None) -> StrategyRule:
        return match_rule(strategy_names, self.rules)

    # ------------------------------------------------------------------
    # On goal
    # ------------------------------------------------------------------

    def on_goal(
        self,
        alert_minute: int,
        goal_minute: int,
        alert_score: str,
        goal_score: str,
        *,
        scored_team: str | None = None,
        trigger_team: str | None = None,
        strategy_names: Sequence[str] | None = None,
    ) -> OutcomeDecision | None:
        """Decide when a goal is scored. `None` means stay PENDING."""
        if alert_score == goal_score:
            return None

        rule = self.rule_for(strategy_names)
        success_window = rule.success_window_minutes
        infinite_ttl = rule.infinite_ttl
        team_specific = rule.team_specific

        # Only apply the team filter when the *rule* says so. Previously this
        # fired whenever trigger_team was set, which blocked non-team-specific
        # strategies that inherited trigger_team from a co-firing strategy.
        if team_specific and trigger_team and scored_team and trigger_team.lower() != "both":
            if trigger_team.lower() != scored_team.lower():
                return None

        if team_specific and not trigger_team:
            return None

        delay = goal_minute - alert_minute

        if infinite_ttl:
            strategy_label = strategy_names[0] if strategy_names else "Strategy"
            reason = (
                f"{strategy_label} Goal at {goal_minute}' "
                f"(Alert {alert_minute}'), delay: {delay} min"
            )
            return OutcomeDecision(AlertState.CONFIRMED, reason)

        if delay <= success_window:
            reason = (
                f"Goal at {goal_minute}' within {success_window}m window "
                f"(Alert {alert_minute}'), delay: {delay} min"
            )
            return OutcomeDecision(AlertState.CONFIRMED, reason)

        reason = (
            f"Goal at {goal_minute}' outside {success_window}m window "
            f"(Alert {alert_minute}'), delay: {delay} min"
        )
        return OutcomeDecision(AlertState.FAILED_TOO_LATE, reason)

    # ------------------------------------------------------------------
    # On expiration
    # ------------------------------------------------------------------

    def on_expiration(
        self,
        alert_minute: int,
        current_minute: int,
        *,
        strategy_names: Sequence[str] | None = None,
        trigger_team: str | None = None,
        opponent_goal_minute: int | None = None,
        opponent_goal_team: str | None = None,
    ) -> OutcomeDecision | None:
        """Decide during a live match whether the window has closed."""
        rule = self.rule_for(strategy_names)
        if rule.infinite_ttl:
            return None

        delay = current_minute - alert_minute
        timeout = rule.success_window_minutes + rule.expiration_buffer_minutes

        if delay > timeout:
            tt = (trigger_team or "").lower()
            if rule.team_specific and tt in ("home", "away") and opponent_goal_team:
                reason = (
                    f"Counter-scored at expiry: {opponent_goal_team} scored at "
                    f"{opponent_goal_minute}' (trigger '{tt}' never equalised)"
                )
                return OutcomeDecision(AlertState.COUNTER_SCORED, reason)
            reason = (
                f"Expired: alert at {alert_minute}', now {current_minute}' "
                f"(> {rule.success_window_minutes}m window)"
            )
            return OutcomeDecision(AlertState.FAILED_EXPIRED, reason)

        return None

    # ------------------------------------------------------------------
    # Match end — score delta
    # ------------------------------------------------------------------

    def on_match_end_from_score_delta(
        self,
        alert: AlertSnapshot,
        *,
        final_score: str,
        final_minute: int,
        source: str = "score_delta",
    ) -> OutcomeDecision | None:
        """Infer a match-end outcome from the final-score delta.

        Returns `None` when the delta is ambiguous. Uses `final_minute` as the
        synthetic goal minute when confirming — which can mark TOO_LATE if
        events are missing and the window is short. Prefer the events path.
        """
        ah, aa = parse_score(alert.alert_score)
        fh, fa = parse_score(final_score)
        home_delta = fh - ah
        away_delta = fa - aa

        if home_delta == 0 and away_delta == 0:
            return None

        rule = self.rule_for(alert.strategy_names)
        team_specific = rule.team_specific
        trigger_team = (alert.trigger_team or "").lower()

        scored_team: str | None = None
        if team_specific and trigger_team in ("home", "away"):
            if trigger_team == "home" and home_delta > 0:
                scored_team = "home"
            elif trigger_team == "away" and away_delta > 0:
                scored_team = "away"
        else:
            if home_delta > 0 and away_delta <= 0:
                scored_team = "home"
            elif away_delta > 0 and home_delta <= 0:
                scored_team = "away"
            elif home_delta > 0 and away_delta > 0:
                scored_team = trigger_team if trigger_team in ("home", "away") else "home"

        if scored_team:
            decision = self.on_goal(
                alert.alert_minute,
                final_minute,
                alert.alert_score,
                final_score,
                scored_team=scored_team,
                trigger_team=trigger_team if team_specific else None,
                strategy_names=alert.strategy_names,
            )
            if decision:
                return decision

        if team_specific and trigger_team in ("home", "away"):
            opp_team = "away" if trigger_team == "home" else "home"
            if (opp_team == "home" and home_delta > 0) or (opp_team == "away" and away_delta > 0):
                reason = (
                    f"Counter-scored ({source}): {opp_team} scored, "
                    f"trigger team '{trigger_team}' never equalised — "
                    f"match ended {final_score}"
                )
                return OutcomeDecision(AlertState.COUNTER_SCORED, reason)

        return None

    # ------------------------------------------------------------------
    # Match end — events
    # ------------------------------------------------------------------

    def on_match_end_from_events(
        self,
        alert: AlertSnapshot,
        events: Sequence[GoalEvent],
        *,
        final_score: str,
        final_minute: int,
    ) -> OutcomeDecision | None:
        """Decide from pre-fetched goal events. No I/O.

        Events may arrive newest-first or oldest-first; we filter to
        post-alert and pick the latest valid minute. Falls back to the
        score-delta path when events are empty or pre-alert only.
        """
        if not events:
            return self.on_match_end_from_score_delta(
                alert,
                final_score=final_score,
                final_minute=final_minute,
                source="match_end_no_events",
            )

        post_alert = [
            GoalEvent(minute=e.minute, side=(e.side or "").lower())
            for e in events
            if e.minute > alert.alert_minute
        ]
        if not post_alert:
            return self.on_match_end_from_score_delta(
                alert,
                final_score=final_score,
                final_minute=final_minute,
                source="match_end_pre_alert_events",
            )

        rule = self.rule_for(alert.strategy_names)
        trigger_team = (alert.trigger_team or "").lower()
        success_window = rule.success_window_minutes
        infinite_ttl = rule.infinite_ttl

        if rule.team_specific and trigger_team in ("home", "away"):
            trigger_events = [e for e in post_alert if e.side == trigger_team]
            if trigger_events:
                valid = [
                    e
                    for e in trigger_events
                    if infinite_ttl or (e.minute - alert.alert_minute) <= success_window
                ]
                if valid:
                    latest = max(valid, key=lambda e: e.minute)
                    return self.on_goal(
                        alert.alert_minute,
                        latest.minute,
                        alert.alert_score,
                        final_score,
                        scored_team=trigger_team,
                        trigger_team=trigger_team,
                        strategy_names=alert.strategy_names,
                    )
                latest = max(trigger_events, key=lambda e: e.minute)
                delay = latest.minute - alert.alert_minute
                reason = (
                    f"Trigger team '{trigger_team}' scored at {latest.minute}' "
                    f"but outside {success_window}m window "
                    f"(alert {alert.alert_minute}'), delay {delay} min"
                )
                return OutcomeDecision(AlertState.FAILED_TOO_LATE, reason)

            opp_team = "away" if trigger_team == "home" else "home"
            opp_events = [e for e in post_alert if e.side == opp_team]
            if opp_events:
                latest_opp = max(opp_events, key=lambda e: e.minute)
                reason = (
                    f"Counter-scored: {opp_team} scored at {latest_opp.minute}' "
                    f"(trigger team '{trigger_team}' never equalised) — "
                    f"match ended {final_score}"
                )
                return OutcomeDecision(AlertState.COUNTER_SCORED, reason)

            return self.on_match_end_from_score_delta(
                alert,
                final_score=final_score,
                final_minute=final_minute,
                source="match_end_events_no_trigger",
            )

        valid_events = [
            e
            for e in post_alert
            if infinite_ttl or (e.minute - alert.alert_minute) <= success_window
        ]
        if valid_events:
            latest = max(valid_events, key=lambda e: e.minute)
            return self.on_goal(
                alert.alert_minute,
                latest.minute,
                alert.alert_score,
                final_score,
                scored_team=latest.side or None,
                trigger_team=None,
                strategy_names=alert.strategy_names,
            )

        if post_alert:
            latest = max(post_alert, key=lambda e: e.minute)
            delay = latest.minute - alert.alert_minute
            reason = (
                f"Goal at {latest.minute}' outside {success_window}m window "
                f"(alert {alert.alert_minute}'), delay {delay} min"
            )
            return OutcomeDecision(AlertState.FAILED_TOO_LATE, reason)

        return None

    # ------------------------------------------------------------------
    # Match end — legacy convenience (no events)
    # ------------------------------------------------------------------

    def on_match_end(
        self,
        alert_minute: int,
        match_final_minute: int,
        alert_score: str,
        final_score: str,
        *,
        strategy_names: Sequence[str] | None = None,
        trigger_team: str | None = None,
    ) -> OutcomeDecision | None:
        """Legacy match-end path used by 2.2's `evaluate_on_match_end`."""
        if alert_score == final_score:
            reason = f"Match ended at {match_final_minute}', no goal after alert at {alert_minute}'"
            return OutcomeDecision(AlertState.FAILED_NO_GOAL, reason)

        alert = AlertSnapshot(
            alert_minute=alert_minute,
            alert_score=alert_score,
            strategy_names=tuple(strategy_names or ()),
            trigger_team=trigger_team,
        )
        decision = self.on_match_end_from_score_delta(
            alert,
            final_score=final_score,
            final_minute=match_final_minute,
            source="evaluate_on_match_end",
        )
        if decision:
            return decision

        reason = (
            f"Match ended {final_score} at {match_final_minute}' — "
            f"goal(s) scored but not credited "
            f"(alert at {alert_minute}', score {alert_score})"
        )
        return OutcomeDecision(AlertState.FAILED_NO_GOAL, reason)


def half_from_minute(minute: int) -> str:
    """Label a minute by half. Unused by the live delay math; kept for parity."""
    if minute <= 45:
        return "1st half"
    if minute <= 90:
        return "2nd half"
    if minute <= 105:
        return "Extra time 1st"
    return "Extra time 2nd"
