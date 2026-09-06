"""Strategy confirmation rules and name→rule matching.

In 2.2 rules lived in Postgres (`strategy_rules`) and were cached for 60s
inside the evaluator. Here they are an injected sequence: adapters load them
once and hand them over. Resolution order is unchanged.

3.0 product default: slots 2–4 are match-level (``team_specific=False``, any
goal counts). Rule of 3 / Omega / K-Score stay team-specific. Admins can
override any row via ``strategy_rules.team_specific`` in settings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

# (needle, slot). First hit wins; order matches 2.2's `_ALERT_HINTS`.
ALERT_NAME_HINTS: Final[tuple[tuple[str, int], ...]] = (
    # slot 2 — InPlay Pressure / Pressure Index display variants
    ("pressure index", 2),
    ("inplay pressure", 2),
    ("in-play pressure", 2),
    ("in play pressure", 2),
    # slot 3 — League Bar (legacy: Delta Goal / Pressure-to-Goal)
    ("league bar", 3),
    ("pressure to goal", 3),
    ("enhanced pressure to goal", 3),
    ("delta goal", 3),
    # slot 4 — Δ(5min) display variants
    ("δ(5min)", 4),
    ("delta(5min)", 4),
    ("delta 5", 4),
    ("δ5", 4),
    # slot 6 — Omega (previously Nephos Delta)
    ("nephos", 6),
    ("omega", 6),
    ("ω", 6),
)


@dataclass(frozen=True, slots=True)
class StrategyRule:
    """One row of confirmation criteria."""

    strategy_slot: int
    strategy_name: str
    success_window_minutes: int = 20
    expiration_buffer_minutes: int = 2
    infinite_ttl: bool = False
    team_specific: bool = False
    enabled: bool = True


# Hardcoded fallback when no strategy name matches anything. Not team-specific.
FALLBACK_RULE: Final = StrategyRule(
    strategy_slot=0,
    strategy_name="default",
    success_window_minutes=20,
    expiration_buffer_minutes=2,
    infinite_ttl=False,
    team_specific=False,
    enabled=True,
)


# Offline / seed defaults. Postgres ``strategy_rules`` overrides at runtime.
DEFAULT_RULES: Final[tuple[StrategyRule, ...]] = (
    StrategyRule(1, "Rule of 3", 999, 0, True, True),
    StrategyRule(2, "InPlay Pressure", 20, 2, False, False),
    StrategyRule(3, "League Bar", 20, 2, False, False),
    StrategyRule(4, "Δ(5min)", 20, 2, False, False),
    StrategyRule(6, "Omega", 20, 2, False, True),
    StrategyRule(7, "K-Score", 20, 2, False, True),
    StrategyRule(9, "Team Form", 20, 2, False, False),
    StrategyRule(10, "H2H Insights", 20, 2, False, False),
)


def match_rule(
    strategy_names: Sequence[str] | None,
    rules: Sequence[StrategyRule],
) -> StrategyRule:
    """Resolve the confirmation rule for a list of strategy display names.

    Order (matches 2.2):
    1. Bidirectional substring match against `strategy_name` (first rule wins;
       callers should pass rules ordered by `strategy_slot`).
    2. `ALERT_NAME_HINTS` needle → slot → rule by `strategy_slot`.
    3. `FALLBACK_RULE` (20m / not infinite / not team-specific).
    """
    if not strategy_names:
        return FALLBACK_RULE

    for rule in rules:
        rule_name = rule.strategy_name
        for strategy_name in strategy_names:
            if (
                rule_name.lower() in strategy_name.lower()
                or strategy_name.lower() in rule_name.lower()
            ):
                return rule

    for strategy_name in strategy_names:
        sn = strategy_name.lower()
        for needle, slot in ALERT_NAME_HINTS:
            if needle in sn:
                for rule in rules:
                    if rule.strategy_slot == slot:
                        return rule
                break

    return FALLBACK_RULE
