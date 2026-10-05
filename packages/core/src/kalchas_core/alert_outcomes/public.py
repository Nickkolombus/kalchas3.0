"""Public Recent-signals labels from live match context.

The dashboard strip is match-facing: Monitoring / Confirmed / Expired.
Telegram delivery_status never enters this mapping.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from kalchas_core.alert_outcomes.evaluator import (
    AlertOutcomeEvaluator,
    AlertSnapshot,
    GoalEvent,
    current_half_has_ended,
)
from kalchas_core.alert_outcomes.rules import DEFAULT_RULES, FALLBACK_RULE, StrategyRule
from kalchas_core.alert_outcomes.score import parse_score
from kalchas_core.alert_outcomes.states import AlertState, OutcomeDecision
from kalchas_core.match_status import FINISHED_STATUS_CODES, MatchPhase, infer_phase

PUBLIC_MONITORING = "Monitoring"
PUBLIC_CONFIRMED = "Confirmed"
PUBLIC_EXPIRED = "Expired"

KIND_MONITORING = "monitoring"
KIND_CONFIRMED = "confirmed"
KIND_NO_GOAL = "no_goal"
KIND_COUNTER = "counter_scored"
KIND_TOO_LATE = "too_late"
KIND_HALF_ENDED = "half_ended"

# Frozen feed: wall time moved, match clock did not.
# A missing board row is a coverage gap until this same wall age; then it is gone.
FROZEN_WALL_MINUTES = 90
FROZEN_CLOCK_SLACK_MINUTES = 5


@dataclass(frozen=True, slots=True)
class PublicSignal:
    """Strip label plus the punchline fields the card needs."""

    state: str
    kind: str = KIND_MONITORING
    scoring_side: str | None = None
    goal_minute: int | None = None
    opponent_side: str | None = None


_SLOT_BY_KEY: dict[str, int] = {
    "rule_of_three": 1,
    "pressure_index": 2,
    "delta_goal": 3,
    "delta_5min": 4,
    "npei": 5,
    "omega": 6,
    "kscore": 7,
}


def public_label(state: AlertState | None) -> str:
    if state is None or state is AlertState.PENDING:
        return PUBLIC_MONITORING
    if state is AlertState.CONFIRMED:
        return PUBLIC_CONFIRMED
    return PUBLIC_EXPIRED


def rule_for_alert(
    *,
    strategy_slot: int | None,
    strategy_key: str | None,
    rules: Sequence[StrategyRule],
) -> StrategyRule:
    slot = strategy_slot
    if slot is None and strategy_key:
        slot = _SLOT_BY_KEY.get(strategy_key)
    if slot is not None:
        for rule in rules:
            if rule.strategy_slot == slot:
                return rule
    return FALLBACK_RULE


def match_is_terminal(status_short: str | None) -> bool:
    return (status_short or "").strip().upper() in FINISHED_STATUS_CODES


def evaluator_from_rule_rows(
    rows: Sequence[Mapping[str, Any]] | None,
) -> AlertOutcomeEvaluator:
    if not rows:
        return AlertOutcomeEvaluator()
    rules = tuple(
        StrategyRule(
            strategy_slot=int(row["strategy_slot"]),
            strategy_name=str(row["strategy_name"]),
            success_window_minutes=int(row["success_window_minutes"]),
            expiration_buffer_minutes=int(row["expiration_buffer_minutes"]),
            infinite_ttl=bool(row["infinite_ttl"]),
            team_specific=bool(row["team_specific"]),
            enabled=bool(row["enabled"]),
            expire_at_half_end=bool(row.get("expire_at_half_end")),
        )
        for row in rows
    )
    return AlertOutcomeEvaluator(rules=rules or DEFAULT_RULES)


def _is_break(status_short: str | None) -> bool:
    return infer_phase(status_short=status_short or "") in {
        MatchPhase.HALF_TIME,
        MatchPhase.EXTRA_TIME_BREAK,
    }


def effective_clock(
    alert_minute: int,
    current_minute: int | None,
    status_short: str | None,
) -> int | None:
    """Playing minute for confirmation. HT/BT often arrive as 0; that is not a live clock."""
    phase = infer_phase(status_short=status_short or "")
    if phase is MatchPhase.HALF_TIME:
        return max(int(alert_minute or 0), int(current_minute or 0), 45)
    if phase is MatchPhase.EXTRA_TIME_BREAK:
        return max(int(alert_minute or 0), int(current_minute or 0), 90)
    if current_minute is None:
        return None
    return int(current_minute)


def _goal_is_after_alert(
    goal_minute: int,
    alert_minute: int,
    status_short: str | None,
    current_minute: int | None = None,
) -> bool:
    if goal_minute >= alert_minute:
        return True
    if goal_minute > 0:
        return False
    # Provider restamps a late first-half goal as 0 when the feed flips to HT.
    return _is_break(status_short) or (current_minute is not None and int(current_minute) <= 0)


def _only_pre_alert_goals(
    goals: Sequence[GoalEvent],
    alert_minute: int,
    status_short: str | None,
    current_minute: int | None = None,
) -> bool:
    if not goals:
        return False
    return all(
        not _goal_is_after_alert(int(g.minute), alert_minute, status_short, current_minute)
        for g in goals
    )


def evaluate_public_signal(
    *,
    alert_minute: int,
    alert_score: str | None,
    strategy_slot: int | None = None,
    strategy_key: str | None = None,
    trigger_team: str | None = None,
    current_minute: int | None,
    current_score: str | None,
    status_short: str | None,
    goals: Sequence[GoalEvent],
    evaluator: AlertOutcomeEvaluator | None = None,
    created_at: datetime | str | None = None,
    now: datetime | None = None,
) -> str:
    """Score one alert against persisted goals / clock. No I/O."""
    return score_public_signal(
        alert_minute=alert_minute,
        alert_score=alert_score,
        strategy_slot=strategy_slot,
        strategy_key=strategy_key,
        trigger_team=trigger_team,
        current_minute=current_minute,
        current_score=current_score,
        status_short=status_short,
        goals=goals,
        evaluator=evaluator,
        created_at=created_at,
        now=now,
    ).state


def score_public_signal(
    *,
    alert_minute: int,
    alert_score: str | None,
    strategy_slot: int | None = None,
    strategy_key: str | None = None,
    trigger_team: str | None = None,
    current_minute: int | None,
    current_score: str | None,
    status_short: str | None,
    goals: Sequence[GoalEvent],
    evaluator: AlertOutcomeEvaluator | None = None,
    created_at: datetime | str | None = None,
    now: datetime | None = None,
) -> PublicSignal:
    """Same scoring as ``evaluate_public_signal``, with punchline fields."""
    clock = effective_clock(alert_minute, current_minute, status_short)
    if clock is None:
        # Provider dropouts must stay Monitoring so a returning match can rescore.
        if _missing_match_is_stale(created_at, now):
            return PublicSignal(PUBLIC_EXPIRED, KIND_NO_GOAL)
        return PublicSignal(PUBLIC_MONITORING, KIND_MONITORING)

    ev = evaluator or AlertOutcomeEvaluator()
    rule = rule_for_alert(
        strategy_slot=strategy_slot,
        strategy_key=strategy_key,
        rules=ev.rules,
    )
    names = (rule.strategy_name,)
    start_score = alert_score or "0-0"
    live_score = current_score or start_score
    team = (trigger_team or "").lower() or None

    post_alert = sorted(
        (
            GoalEvent(
                minute=clock if int(g.minute) <= 0 else int(g.minute),
                side=(g.side or "").lower(),
            )
            for g in goals
            if _goal_is_after_alert(int(g.minute), alert_minute, status_short, current_minute)
        ),
        key=lambda g: g.minute,
    )
    for goal in post_alert:
        decision = ev.on_goal(
            alert_minute,
            goal.minute,
            start_score,
            live_score,
            scored_team=goal.side or None,
            trigger_team=team if rule.team_specific else None,
            strategy_names=names,
            status_short=status_short,
        )
        if decision is not None:
            side = _side(goal.side)
            return _from_decision(
                decision,
                rule=rule,
                alert_minute=alert_minute,
                status_short=status_short,
                scoring_side=side,
                goal_minute=int(goal.minute),
            )

    if live_score != start_score and not _only_pre_alert_goals(
        goals, alert_minute, status_short, current_minute
    ):
        snap = AlertSnapshot(
            alert_minute=alert_minute,
            alert_score=start_score,
            strategy_names=names,
            trigger_team=team,
        )
        decision = ev.on_match_end_from_score_delta(
            snap,
            final_score=live_score,
            final_minute=clock,
            source="live_score_delta",
        )
        if decision is not None and decision.new_state is AlertState.CONFIRMED:
            return _from_decision(
                decision,
                rule=rule,
                alert_minute=alert_minute,
                status_short=status_short,
                scoring_side=_scoring_side_from_scores(
                    start_score,
                    live_score,
                    trigger=team if rule.team_specific else None,
                    team_specific=rule.team_specific,
                ),
                goal_minute=clock,
            )

    if match_is_terminal(status_short):
        decision = _on_match_end(
            ev,
            alert_minute=alert_minute,
            alert_score=start_score,
            names=names,
            trigger_team=team,
            goals=goals,
            final_score=live_score,
            final_minute=clock,
        )
        if decision is None:
            return PublicSignal(PUBLIC_EXPIRED, KIND_NO_GOAL)
        opp, opp_min = _opponent_goal(post_alert, team if rule.team_specific else None)
        scored, gmin = _goal_fields(post_alert, team if rule.team_specific else None)
        if scored is None:
            scored = _scoring_side_from_scores(
                start_score,
                live_score,
                trigger=team if rule.team_specific else None,
                team_specific=rule.team_specific,
            )
        return _from_decision(
            decision,
            rule=rule,
            alert_minute=alert_minute,
            status_short=status_short,
            scoring_side=scored,
            goal_minute=gmin,
            opponent_side=opp,
            opponent_minute=opp_min,
        )

    opp_team, opp_minute = _opponent_goal(post_alert, team if rule.team_specific else None)
    decision = ev.on_expiration(
        alert_minute,
        clock,
        strategy_names=names,
        trigger_team=team,
        opponent_goal_minute=opp_minute,
        opponent_goal_team=opp_team,
        status_short=status_short,
    )
    if decision is not None:
        return _from_decision(
            decision,
            rule=rule,
            alert_minute=alert_minute,
            status_short=status_short,
            opponent_side=opp_team,
            opponent_minute=opp_minute,
            goal_minute=opp_minute,
        )
    if _feed_is_frozen(alert_minute, clock, created_at, now):
        return PublicSignal(PUBLIC_EXPIRED, KIND_NO_GOAL)
    return PublicSignal(PUBLIC_MONITORING, KIND_MONITORING)


def _created_age_minutes(created_at: datetime | str | None, now: datetime | None) -> float | None:
    if created_at is None or now is None:
        return None
    if isinstance(created_at, datetime):
        then = created_at
    else:
        text = str(created_at).strip()
        if not text:
            return None
        try:
            then = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    instant = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return max(0.0, (instant - then).total_seconds() / 60.0)


def _missing_match_is_stale(
    created_at: datetime | str | None,
    now: datetime | None,
) -> bool:
    age = _created_age_minutes(created_at, now)
    return age is not None and age >= FROZEN_WALL_MINUTES


def _feed_is_frozen(
    alert_minute: int,
    clock: int,
    created_at: datetime | str | None,
    now: datetime | None,
) -> bool:
    age = _created_age_minutes(created_at, now)
    if age is None:
        return False
    delay = int(clock) - int(alert_minute)
    return age >= FROZEN_WALL_MINUTES and delay < FROZEN_CLOCK_SLACK_MINUTES


def _side(raw: str | None) -> str | None:
    side = (raw or "").lower()
    return side if side in ("home", "away") else None


def _scoring_side_from_scores(
    start: str,
    live: str,
    *,
    trigger: str | None,
    team_specific: bool,
) -> str | None:
    ah, aa = parse_score(start)
    fh, fa = parse_score(live)
    dh, da = fh - ah, fa - aa
    if team_specific and trigger in ("home", "away"):
        if trigger == "home" and dh > 0:
            return "home"
        if trigger == "away" and da > 0:
            return "away"
        return None
    if dh > 0 and da <= 0:
        return "home"
    if da > 0 and dh <= 0:
        return "away"
    if dh > 0:
        return "home"
    if da > 0:
        return "away"
    return None


def _goal_fields(
    post_alert: Sequence[GoalEvent],
    trigger_team: str | None,
) -> tuple[str | None, int | None]:
    if not post_alert:
        return None, None
    if trigger_team in ("home", "away"):
        mine = [g for g in post_alert if g.side == trigger_team]
        if mine:
            latest = mine[-1]
            return _side(latest.side), int(latest.minute)
    latest = post_alert[-1]
    return _side(latest.side), int(latest.minute)


def _from_decision(
    decision: OutcomeDecision,
    *,
    rule: StrategyRule,
    alert_minute: int,
    status_short: str | None,
    scoring_side: str | None = None,
    goal_minute: int | None = None,
    opponent_side: str | None = None,
    opponent_minute: int | None = None,
) -> PublicSignal:
    state = public_label(decision.new_state)
    if decision.new_state is AlertState.CONFIRMED:
        return PublicSignal(
            state,
            KIND_CONFIRMED,
            scoring_side=scoring_side,
            goal_minute=goal_minute,
        )
    if decision.new_state is AlertState.COUNTER_SCORED:
        return PublicSignal(
            state,
            KIND_COUNTER,
            opponent_side=opponent_side,
            goal_minute=opponent_minute if opponent_minute is not None else goal_minute,
        )
    if decision.new_state is AlertState.FAILED_TOO_LATE:
        return PublicSignal(
            state,
            KIND_TOO_LATE,
            scoring_side=scoring_side,
            goal_minute=goal_minute,
        )
    if decision.new_state is AlertState.FAILED_EXPIRED:
        if rule.expire_at_half_end and current_half_has_ended(alert_minute, status_short):
            return PublicSignal(state, KIND_HALF_ENDED)
        return PublicSignal(state, KIND_NO_GOAL)
    return PublicSignal(state, KIND_NO_GOAL)


def _on_match_end(
    ev: AlertOutcomeEvaluator,
    *,
    alert_minute: int,
    alert_score: str,
    names: tuple[str, ...],
    trigger_team: str | None,
    goals: Sequence[GoalEvent],
    final_score: str,
    final_minute: int,
) -> OutcomeDecision | None:
    snap = AlertSnapshot(
        alert_minute=alert_minute,
        alert_score=alert_score,
        strategy_names=names,
        trigger_team=trigger_team,
    )
    decision = ev.on_match_end_from_events(
        snap,
        goals,
        final_score=final_score,
        final_minute=final_minute,
    )
    if decision is not None:
        return decision
    return ev.on_match_end(
        alert_minute,
        final_minute,
        alert_score,
        final_score,
        strategy_names=names,
        trigger_team=trigger_team,
    )


def _opponent_goal(
    post_alert: Sequence[GoalEvent],
    trigger_team: str | None,
) -> tuple[str | None, int | None]:
    if trigger_team not in ("home", "away"):
        return None, None
    opp = "away" if trigger_team == "home" else "home"
    opp_events = [g for g in post_alert if g.side == opp]
    if not opp_events:
        return None, None
    latest = max(opp_events, key=lambda g: g.minute)
    return opp, latest.minute
