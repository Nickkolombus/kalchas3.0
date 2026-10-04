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
from kalchas_core.alert_outcomes.public import (
    PUBLIC_CONFIRMED,
    PUBLIC_EXPIRED,
    PUBLIC_MONITORING,
    PublicSignal,
    effective_clock,
    evaluate_public_signal,
    evaluator_from_rule_rows,
    match_is_terminal,
    public_label,
    rule_for_alert,
    score_public_signal,
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
    "PUBLIC_CONFIRMED",
    "PUBLIC_EXPIRED",
    "PUBLIC_MONITORING",
    "AlertOutcomeEvaluator",
    "AlertSnapshot",
    "AlertState",
    "GoalEvent",
    "OutcomeDecision",
    "PublicSignal",
    "StrategyRule",
    "effective_clock",
    "evaluate_public_signal",
    "evaluator_from_rule_rows",
    "half_from_minute",
    "match_is_terminal",
    "match_rule",
    "parse_score",
    "public_label",
    "rule_for_alert",
    "score_public_signal",
]
