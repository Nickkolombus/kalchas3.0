"""Alert cooldown decisions — pure, clock-injected.

Ported from ``utils/cooldown_manager.py``. Persistence, asyncio locks and
admin-settings lookups stay in the app layer. Core owns the decision tree:

1. Global TSLG mute (any goal within ``goal_cooldown_minutes``)
2. Red-card mute for the trigger team
3. Per-strategy window with optional value-delta bypass
4. Same-minute and reservation blocks
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

Clock = Callable[[], datetime]


DEFAULT_BASE_COOLDOWN = 10
DEFAULT_BYPASS_DELTA: Mapping[int, float] = {
    1: 0.5,
    2: 10.0,
    3: 4.0,
    4: 1.0,
    6: 1.5,
    7: 5.0,
}


@dataclass(frozen=True, slots=True)
class CooldownRules:
    strategy_slot: int
    base_cooldown_minutes: int = DEFAULT_BASE_COOLDOWN
    team_specific: bool = True
    value_delta_threshold: float | None = None
    mute_on_red_card: bool = True

    @staticmethod
    def for_slot(strategy_slot: int) -> CooldownRules:
        return CooldownRules(
            strategy_slot=strategy_slot,
            base_cooldown_minutes=DEFAULT_BASE_COOLDOWN,
            value_delta_threshold=DEFAULT_BYPASS_DELTA.get(strategy_slot),
        )


@dataclass(frozen=True, slots=True)
class CooldownDecision:
    can_send: bool
    reason: str
    blocked_by: str | None = None
    cooldown_key: str = ""
    next_allowed_minute: int | None = None

    @staticmethod
    def allow(cooldown_key: str, reason: str = "Cooldown check passed") -> CooldownDecision:
        return CooldownDecision(can_send=True, reason=reason, cooldown_key=cooldown_key)

    @staticmethod
    def block(
        reason: str,
        blocked_by: str,
        next_allowed_minute: int | None = None,
    ) -> CooldownDecision:
        return CooldownDecision(
            can_send=False,
            reason=reason,
            blocked_by=blocked_by,
            next_allowed_minute=next_allowed_minute,
        )


@dataclass
class CooldownState:
    match_id: str
    strategy_slot: int
    team: str | None
    last_alert_minute: int
    last_alert_value: float
    last_alert_time: datetime
    reserved_until: datetime | None = None

    def is_reserved(self, now: datetime) -> bool:
        return self.reserved_until is not None and now < self.reserved_until


def normalize_match_id(match_id: Any) -> str:
    if match_id is None:
        return "unknown"
    return str(match_id)


def cooldown_key(match_id: Any, strategy_slot: int, team: str | None = None) -> str:
    mid = normalize_match_id(match_id)
    if team:
        return f"{mid}:S{strategy_slot}:{team}"
    return f"{mid}:S{strategy_slot}"


def last_goal_minute(
    *,
    goal_events: list[dict[str, Any]] | None = None,
    last_goal: dict[str, Any] | None = None,
    current_minute: int,
) -> int | None:
    """Most recent goal minute at or before ``current_minute``."""
    candidates: list[int] = []
    for event in goal_events or []:
        t = _goal_event_minute(event)
        if t is not None and t <= current_minute:
            candidates.append(t)
    if isinstance(last_goal, dict) and last_goal.get("minute") is not None:
        try:
            t = int(last_goal["minute"])
            if t <= current_minute:
                candidates.append(t)
        except (TypeError, ValueError):
            pass
    return max(candidates) if candidates else None


def _goal_event_minute(event: dict[str, Any]) -> int | None:
    for key in ("minute", "elapsed", "time"):
        val = event.get(key)
        if isinstance(val, dict):
            for nested in ("elapsed", "extra"):
                n = val.get(nested)
                if n is not None:
                    try:
                        return int(n)
                    except (TypeError, ValueError):
                        pass
            continue
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    return None


@dataclass
class CooldownBook:
    """In-memory cooldown ledger. Callers serialise access if multi-threaded."""

    goal_cooldown_minutes: int = 10
    reservation_seconds: int = 10
    rules: dict[int, CooldownRules] = field(default_factory=dict)
    _state: dict[str, CooldownState] = field(default_factory=dict)
    _clock: Clock = field(default=datetime.now, repr=False)

    def rules_for(self, strategy_slot: int) -> CooldownRules:
        if strategy_slot not in self.rules:
            self.rules[strategy_slot] = CooldownRules.for_slot(strategy_slot)
        return self.rules[strategy_slot]

    def decide(
        self,
        match_id: Any,
        strategy_slot: int,
        current_minute: int,
        strategy_value: float,
        *,
        team: str | None = None,
        goal_events: list[dict[str, Any]] | None = None,
        last_goal: dict[str, Any] | None = None,
        red_cards: Mapping[str, int] | None = None,
        reserve: bool = True,
    ) -> CooldownDecision:
        """Check whether an alert may fire. Optionally reserves the slot."""
        mid = normalize_match_id(match_id)
        now = self._clock()

        lg = last_goal_minute(
            goal_events=goal_events,
            last_goal=last_goal,
            current_minute=current_minute,
        )
        if lg is not None and (current_minute - lg) < self.goal_cooldown_minutes:
            return CooldownDecision.block(
                f"TSLG mute: last goal at {lg}' ({current_minute - lg}m ago)",
                "TSLG_GLOBAL_MUTE",
            )

        rules = self.rules_for(strategy_slot)
        if rules.mute_on_red_card and team and red_cards:
            if int(red_cards.get(team, 0) or 0) > 0:
                return CooldownDecision.block(
                    f"Strategy {strategy_slot} muted: {team} has red card",
                    "RED_CARD_MUTE",
                )

        key = cooldown_key(mid, strategy_slot, team)
        state = self._state.get(key)
        if state:
            if state.is_reserved(now):
                return CooldownDecision.block(f"Slot reserved for {strategy_slot}", "RESERVATION")
            if current_minute == state.last_alert_minute:
                return CooldownDecision.block(
                    f"Already triggered at {current_minute}'", "SAME_MINUTE"
                )
            minutes_since = current_minute - state.last_alert_minute
            if minutes_since < rules.base_cooldown_minutes:
                if rules.value_delta_threshold is not None:
                    increase = strategy_value - state.last_alert_value
                    if increase >= rules.value_delta_threshold:
                        pass  # bypass — fall through to reserve
                    else:
                        next_allowed = state.last_alert_minute + rules.base_cooldown_minutes
                        return CooldownDecision.block(
                            f"In cooldown ({minutes_since}m < {rules.base_cooldown_minutes}m)",
                            f"S{strategy_slot}_COOLDOWN",
                            next_allowed,
                        )
                else:
                    next_allowed = state.last_alert_minute + rules.base_cooldown_minutes
                    return CooldownDecision.block(
                        f"In cooldown ({minutes_since}m < {rules.base_cooldown_minutes}m)",
                        f"S{strategy_slot}_COOLDOWN",
                        next_allowed,
                    )

        if reserve:
            self._state[key] = CooldownState(
                match_id=mid,
                strategy_slot=strategy_slot,
                team=team,
                last_alert_minute=current_minute,
                last_alert_value=strategy_value,
                last_alert_time=now,
                reserved_until=now + timedelta(seconds=self.reservation_seconds),
            )
        return CooldownDecision.allow(
            key, f"Strategy {strategy_slot} allowed (Value: {strategy_value:.2f})"
        )

    def confirm(self, key: str) -> None:
        """Clear reservation after a successful send; keep the alert minute."""
        state = self._state.get(key)
        if state is not None:
            state.reserved_until = None

    def rollback(self, key: str) -> None:
        """Drop a reserved slot that never sent."""
        self._state.pop(key, None)
