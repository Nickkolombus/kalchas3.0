"""Alert confirmation and failure decisions — pure, no I/O.

This is the alert-outcome SSOT. Do not confuse it with the Score Landscape
predictor that lived in 2.2's `utils/outcome_engine.py`; that is a separate
concern and is not ported here.
"""

from kalchas_core.alert_outcomes.evaluator import (
    AlertOutcomeEvaluator,
    AlertSnapshot,
    GoalEvent,
    half_from_minute,
)
from kalchas_core.alert_outcomes.rules import (
    ALERT_NAME_HINTS,
    DEFAULT_RULES,
    FALLBACK_RULE,
    StrategyRule,
    match_rule,
)
from kalchas_core.alert_outcomes.score import parse_score
from kalchas_core.alert_outcomes.states import AlertState, OutcomeDecision

__all__ = [
    "ALERT_NAME_HINTS",
    "DEFAULT_RULES",
    "FALLBACK_RULE",
    "AlertOutcomeEvaluator",
    "AlertSnapshot",
    "AlertState",
    "GoalEvent",
    "OutcomeDecision",
    "StrategyRule",
    "half_from_minute",
    "match_rule",
    "parse_score",
]
