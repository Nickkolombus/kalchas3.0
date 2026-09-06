"""Alert lifecycle states and the decision DTO."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AlertState(Enum):
    """Alert lifecycle states.

    Values match the strings written to `alerts_history.outcome` in 2.2.
    `COUNTER_SCORED` is a neutral terminal: excluded from win/loss stats.
    `CANCELLED_VAR` is transitioned by the tracker, not by this evaluator.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED_TOO_LATE = "too_late"
    FAILED_EXPIRED = "expired"
    FAILED_NO_GOAL = "no_goal"
    CANCELLED_VAR = "cancelled"
    COUNTER_SCORED = "counter_scored"


@dataclass(frozen=True, slots=True)
class OutcomeDecision:
    """Result of one evaluation call."""

    new_state: AlertState
    reason: str
    should_notify: bool = True

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"OutcomeDecision(state={self.new_state.value}, "
            f"reason={self.reason!r}, notify={self.should_notify})"
        )
