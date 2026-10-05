"""Score Recent signals from persisted match context (no extra provider HTTP)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from kalchas_core.alert_outcomes import (
    AlertOutcomeEvaluator,
    GoalEvent,
    PublicSignal,
    score_public_signal,
)


def public_alert_signal(
    row: dict[str, Any],
    *,
    current_minute: int | None,
    current_score: str | None,
    status_short: str | None,
    goals: list[GoalEvent],
    evaluator: AlertOutcomeEvaluator,
) -> PublicSignal:
    """Match-facing strip fields. Delivery failures stay out of the public strip."""
    slot = row.get("strategy_slot")
    return score_public_signal(
        alert_minute=int(row["minute"]),
        alert_score=str(row["score"]) if row.get("score") else None,
        strategy_slot=int(slot) if slot is not None else None,
        strategy_key=str(row["strategy_key"]) if row.get("strategy_key") else None,
        trigger_team=str(row["team"]) if row.get("team") else None,
        current_minute=current_minute,
        current_score=current_score,
        status_short=status_short,
        goals=goals,
        evaluator=evaluator,
        created_at=row.get("created_at"),
        now=datetime.now(UTC),
    )


def public_alert_state(
    row: dict[str, Any],
    *,
    current_minute: int | None,
    current_score: str | None,
    status_short: str | None,
    goals: list[GoalEvent],
    evaluator: AlertOutcomeEvaluator,
) -> str:
    """Match-facing label. Delivery failures stay out of the public strip."""
    return public_alert_signal(
        row,
        current_minute=current_minute,
        current_score=current_score,
        status_short=status_short,
        goals=goals,
        evaluator=evaluator,
    ).state


def goals_from_events(events: list[Any]) -> list[GoalEvent]:
    out: list[GoalEvent] = []
    for event in events:
        if isinstance(event, dict):
            if str(event.get("event_type") or "") != "goal":
                continue
            out.append(
                GoalEvent(
                    minute=int(event.get("minute") or 0),
                    side=str(event.get("side") or ""),
                )
            )
            continue
        if getattr(event, "event_type", None) != "goal":
            continue
        out.append(GoalEvent(minute=int(event.minute), side=str(event.side or "")))
    return out
