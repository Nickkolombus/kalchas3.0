"""Alert cooldown decisions — pure, clock-injected.

Ported from ``utils/cooldown_manager.py``. Persistence, asyncio locks and
admin-settings lookups stay in the app layer. Core owns the decision tree:

1. Global TSLG mute (any goal within ``goal_cooldown_minutes``)
2. Red-card mute for the trigger team
3. Team stack: one non-Omega speaking turn per side
4. Per-strategy window with optional value-delta bypass
5. Same-minute and reservation blocks
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

Clock = Callable[[], datetime]


DEFAULT_BASE_COOLDOWN = 10
DEFAULT_OMEGA_COOLDOWN = 15
DEFAULT_REARM_DROP_RATIO = 0.5
DEFAULT_TEAM_STACK_MINUTES = 10
DEFAULT_BYPASS_DELTA: Mapping[int, float] = {
    1: 0.5,
    2: 10.0,
    3: 4.0,
    7: 5.0,
}


@dataclass(frozen=True, slots=True)
class CooldownRules:
    strategy_slot: int
    base_cooldown_minutes: int = DEFAULT_BASE_COOLDOWN
    team_specific: bool = True
    value_delta_threshold: float | None = None
    mute_on_red_card: bool = True
    rearm_after_drop: bool = False
    rearm_drop_ratio: float = DEFAULT_REARM_DROP_RATIO

    @staticmethod
    def for_slot(strategy_slot: int) -> CooldownRules:
        if strategy_slot in {4, 6}:
            return CooldownRules(
                strategy_slot=strategy_slot,
                base_cooldown_minutes=(
                    DEFAULT_OMEGA_COOLDOWN if strategy_slot == 6 else DEFAULT_BASE_COOLDOWN
                ),
                value_delta_threshold=None,
                rearm_after_drop=True,
            )
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
    waiting_for_drop: bool = False

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
    team_stack_minutes: int = DEFAULT_TEAM_STACK_MINUTES
    reservation_seconds: int = 10
    rules: dict[int, CooldownRules] = field(default_factory=dict)
    _state: dict[str, CooldownState] = field(default_factory=dict)
    _clock: Clock = field(default=datetime.now, repr=False)

    def rules_for(self, strategy_slot: int) -> CooldownRules:
        if strategy_slot not in self.rules:
            self.rules[strategy_slot] = CooldownRules.for_slot(strategy_slot)
        return self.rules[strategy_slot]

    def _team_stack_block(
        self,
        match_id: str,
        strategy_slot: int,
        current_minute: int,
        team: str | None,
    ) -> CooldownDecision | None:
        """One speaking turn per team. Omega can still interrupt."""
        if strategy_slot == 6 or not team or self.team_stack_minutes <= 0:
            return None
        for state in self._state.values():
            if state.match_id != match_id:
                continue
            if (state.team or "") != team:
                continue
            if state.strategy_slot == strategy_slot:
                continue
            waited = current_minute - state.last_alert_minute
            if 0 <= waited < self.team_stack_minutes:
                return CooldownDecision.block(
                    f"Team already alerted at {state.last_alert_minute}' "
                    f"(S{state.strategy_slot})",
                    "TEAM_STACK",
                    state.last_alert_minute + self.team_stack_minutes,
                )
        return None

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

        stacked = self._team_stack_block(mid, strategy_slot, current_minute, team)
        if stacked is not None:
            return stacked

        key = cooldown_key(mid, strategy_slot, team)
        state = self._state.get(key)
        if state:
            if state.is_reserved(now):
                return CooldownDecision.block(f"Slot reserved for {strategy_slot}", "RESERVATION")
            if current_minute == state.last_alert_minute:
                return CooldownDecision.block(
                    f"Already triggered at {current_minute}'", "SAME_MINUTE"
                )
            if rules.rearm_after_drop and state.waiting_for_drop:
                reset_at = state.last_alert_value * rules.rearm_drop_ratio
                if strategy_value > reset_at:
                    return CooldownDecision.block(
                        f"Same surge still active ({strategy_value:.2f} > {reset_at:.2f})",
                        "STILL_SURGING",
                    )
                state.waiting_for_drop = False
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
                waiting_for_drop=rules.rearm_after_drop,
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
