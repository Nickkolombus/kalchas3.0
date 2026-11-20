"""Settle open alerts to Confirmed / Expired for admin Results.

Write-once. The live strip still recomputes; this snapshot does not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from kalchas_core.alert_outcomes import (
    PUBLIC_CONFIRMED,
    PUBLIC_EXPIRED,
    AlertOutcomeEvaluator,
    GoalEvent,
    effective_clock,
    rule_for_alert,
    score_public_signal,
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
    signal = score_public_signal(
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
        created_at=alert.get("created_at"),
        now=datetime.now(UTC),
    )
    if signal.state not in _SETTLED:
        return None
    payload = alert.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    clock = effective_clock(int(alert["minute"]), current_minute, status_short)
    slot = alert.get("strategy_slot")
    key = alert.get("strategy_key")
    rule = rule_for_alert(
        strategy_slot=int(slot) if slot is not None else None,
        strategy_key=str(key) if key else None,
        rules=evaluator.rules,
    )
    return {
        "alert_id": int(alert["id"]),
        "state": signal.state,
        "decision": "confirmed" if signal.state == PUBLIC_CONFIRMED else "expired",
        "detail": {
            "fire_score": alert.get("score"),
            "fire_minute": int(alert["minute"]),
            "settle_score": current_score,
            "settle_minute": clock,
            "goal_minute": signal.goal_minute,
            "kind": signal.kind,
            "scoring_side": signal.scoring_side,
            "success_window_minutes": rule.success_window_minutes,
            "infinite_ttl": rule.infinite_ttl,
            "status_short": status_short,
            "team": alert.get("team"),
            "league": payload.get("league"),
            "home_team": alert.get("home_team"),
            "away_team": alert.get("away_team"),
        },
    }


def match_end_totals(match: Any) -> tuple[int | None, int | None]:
    """(half-time goals, 90-minute goals) of a finished match, None where unknown.

    Read from the provider row (``match_*_halftime_score`` / ``match_*_ft_score``)
    so extra-time goals never count; a plain FT row falls back to its score.
    """
    from kalchas_football import parse_results

    raw = getattr(match, "raw", None)
    parsed = parse_results([raw]) if isinstance(raw, dict) and raw.get("match_id") else []
    status = (getattr(match, "status_short", "") or "").strip().upper()
    ht = ft = None
    if parsed:
        row = parsed[0]
        if row.get("home_ht") is not None and row.get("away_ht") is not None:
            ht = int(row["home_ht"]) + int(row["away_ht"])
        if row.get("home_90") is not None and row.get("away_90") is not None:
            ft = int(row["home_90"]) + int(row["away_90"])
    if ft is None and status == "FT":
        ft = int(getattr(match, "home_score", 0) or 0) + int(getattr(match, "away_score", 0) or 0)
    return ht, ft


def graded_over_bet_rows(
    alerts: list[dict[str, Any]], *, ht_total: int | None, ft_total: int | None
) -> list[dict[str, Any]]:
    """One write-once row per alert. Alerts fired before ``over_bet`` was stamped
    get their bets rebuilt from the stored ``live_goal_odds`` (first-half alerts
    then show the default bet)."""
    from kalchas_core.over_bet import grade_over_bets, over_bets_for_alert

    rows: list[dict[str, Any]] = []
    for alert in alerts:
        over_bet = alert.get("over_bet")
        if not isinstance(over_bet, dict):
            over_bet = over_bets_for_alert(
                score=alert.get("score"),
                first_half=int(alert.get("minute") or 0) <= 45,
                goal_odds=alert.get("live_goal_odds"),
            )
        graded = grade_over_bets(over_bet, ht_total=ht_total, ft_total=ft_total)
        if not graded or not graded["bets"]:
            continue
        rows.append(
            {
                "alert_id": int(alert["id"]),
                "primary_variant": str(graded["primary"]),
                "bets": graded["bets"],
                "ht_goals": ht_total,
                "ft_goals": ft_total,
            }
        )
    return rows


def persist_graded_over_bets(dsn: str, match: Any) -> int:
    """Grade every not-yet-graded alert of a finished match. Needs the 90-minute total."""
    from kalchas_db.over_bets import (
        insert_graded_over_bets_sync,
        list_ungraded_alerts_for_match_sync,
    )

    ht_total, ft_total = match_end_totals(match)
    if ft_total is None:
        return 0
    alerts = list_ungraded_alerts_for_match_sync(dsn, str(match.match_id))
    if not alerts:
        return 0
    return insert_graded_over_bets_sync(
        dsn, graded_over_bet_rows(alerts, ht_total=ht_total, ft_total=ft_total)
    )


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
