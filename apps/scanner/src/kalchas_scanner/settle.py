"""Settle open alerts to Confirmed / Expired for admin Results.

Write-once. The live strip still recomputes; this snapshot does not.
"""

from __future__ import annotations

from typing import Any

from kalchas_core.alert_outcomes import (
    PUBLIC_CONFIRMED,
    PUBLIC_EXPIRED,
    AlertOutcomeEvaluator,
    GoalEvent,
    effective_clock,
    evaluate_public_signal,
)

_SETTLED = {PUBLIC_CONFIRMED, PUBLIC_EXPIRED}


def goals_from_ssot(events: list[dict[str, Any]] | None) -> list[GoalEvent]:
    out: list[GoalEvent] = []
    for event in events or []:
        if str(event.get("event_type") or "") != "goal":
            continue
        out.append(
            GoalEvent(
                minute=int(event.get("minute") or 0),
                side=str(event.get("side") or ""),
            )
        )
    return out


def outcome_snapshot(
    alert: dict[str, Any],
    *,
    current_minute: int,
    current_score: str,
    status_short: str | None,
    goals: list[GoalEvent],
    evaluator: AlertOutcomeEvaluator,
) -> dict[str, Any] | None:
    """Return a persistable outcome, or None while the strip is still Monitoring."""
    state = evaluate_public_signal(
        alert_minute=int(alert["minute"]),
        alert_score=str(alert["score"]) if alert.get("score") else None,
        strategy_slot=int(alert["strategy_slot"])
        if alert.get("strategy_slot") is not None
        else None,
        strategy_key=str(alert["strategy_key"]) if alert.get("strategy_key") else None,
        trigger_team=str(alert["team"]) if alert.get("team") else None,
        current_minute=current_minute,
        current_score=current_score,
        status_short=status_short,
        goals=goals,
        evaluator=evaluator,
    )
    if state not in _SETTLED:
        return None
    payload = alert.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    clock = effective_clock(int(alert["minute"]), current_minute, status_short)
    return {
        "alert_id": int(alert["id"]),
        "state": state,
        "decision": "confirmed" if state == PUBLIC_CONFIRMED else "expired",
        "detail": {
            "fire_score": alert.get("score"),
            "fire_minute": int(alert["minute"]),
            "settle_score": current_score,
            "settle_minute": clock,
            "status_short": status_short,
            "team": alert.get("team"),
            "league": payload.get("league"),
            "home_team": alert.get("home_team"),
            "away_team": alert.get("away_team"),
        },
    }


def persist_settled_alerts(
    dsn: str,
    *,
    match_id: str,
    current_minute: int,
    current_score: str,
    status_short: str | None,
    events: list[dict[str, Any]],
    evaluator: AlertOutcomeEvaluator,
) -> int:
    from kalchas_db.alerts import insert_alert_outcome_sync, list_open_alerts_for_match_sync

    open_rows = list_open_alerts_for_match_sync(dsn, match_id)
    if not open_rows:
        return 0
    goals = goals_from_ssot(events)
    written = 0
    for row in open_rows:
        snap = outcome_snapshot(
            row,
            current_minute=current_minute,
            current_score=current_score,
            status_short=status_short,
            goals=goals,
            evaluator=evaluator,
        )
        if snap is None:
            continue
        insert_alert_outcome_sync(
            dsn,
            alert_id=int(snap["alert_id"]),
            state=str(snap["state"]),
            decision=str(snap["decision"]),
            detail=dict(snap["detail"]),
        )
        written += 1
    return written
