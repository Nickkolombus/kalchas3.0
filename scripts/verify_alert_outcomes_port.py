"""Differential check: does the 3.0 alert-outcome evaluator match 2.2?

Forces the 2.2 evaluator onto its offline defaults (no DB) and compares
`evaluate_on_goal` / `evaluate_on_expiration` / `evaluate_on_match_end` over a
grid of inputs.

    uv run python scripts/verify_alert_outcomes_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from kalchas_core.alert_outcomes import AlertOutcomeEvaluator, StrategyRule

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")

# Exact copy of AlertOutcomeEvaluator._get_default_rules in 2.2.
OFFLINE_RULES_2_2 = [
    {
        "strategy_slot": 1,
        "strategy_name": "Rule of 3",
        "success_window_minutes": 999,
        "expiration_buffer_minutes": 0,
        "infinite_ttl": True,
        "team_specific": True,
        "enabled": True,
    },
    {
        "strategy_slot": 2,
        "strategy_name": "InPlay Pressure",
        "success_window_minutes": 20,
        "expiration_buffer_minutes": 2,
        "infinite_ttl": False,
        "team_specific": True,
        "enabled": True,
    },
    {
        "strategy_slot": 3,
        "strategy_name": "League Bar",
        "success_window_minutes": 20,
        "expiration_buffer_minutes": 2,
        "infinite_ttl": False,
        "team_specific": True,
        "enabled": True,
    },
    {
        "strategy_slot": 4,
        "strategy_name": "Δ(5min)",
        "success_window_minutes": 20,
        "expiration_buffer_minutes": 2,
        "infinite_ttl": False,
        "team_specific": True,
        "enabled": True,
    },
    {
        "strategy_slot": 6,
        "strategy_name": "Omega",
        "success_window_minutes": 20,
        "expiration_buffer_minutes": 2,
        "infinite_ttl": False,
        "team_specific": True,
        "enabled": True,
    },
    {
        "strategy_slot": 9,
        "strategy_name": "Team Form",
        "success_window_minutes": 20,
        "expiration_buffer_minutes": 2,
        "infinite_ttl": False,
        "team_specific": False,
        "enabled": True,
    },
    {
        "strategy_slot": 10,
        "strategy_name": "H2H Insights",
        "success_window_minutes": 20,
        "expiration_buffer_minutes": 2,
        "infinite_ttl": False,
        "team_specific": False,
        "enabled": True,
    },
]


def load_legacy(root: Path):
    for name in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "psycopg2.extensions"):
        sys.modules.setdefault(name, MagicMock())
    sys.path.insert(0, str(root))
    try:
        from utils import alert_outcome_evaluator as legacy  # type: ignore
    except Exception as exc:
        raise SystemExit(f"could not import 2.2 alert_outcome_evaluator: {exc!r}") from exc
    return legacy


def _state(decision) -> str | None:
    if decision is None:
        return None
    return decision.new_state.value


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    legacy = load_legacy(root)

    new_rules = tuple(
        StrategyRule(
            strategy_slot=r["strategy_slot"],
            strategy_name=r["strategy_name"],
            success_window_minutes=r["success_window_minutes"],
            expiration_buffer_minutes=r["expiration_buffer_minutes"],
            infinite_ttl=r["infinite_ttl"],
            team_specific=r["team_specific"],
            enabled=r["enabled"],
        )
        for r in OFFLINE_RULES_2_2
    )
    new = AlertOutcomeEvaluator(rules=new_rules)

    divergences: list[str] = []
    checked = 0

    with patch.object(
        legacy.AlertOutcomeEvaluator,
        "_get_rules",
        lambda self: OFFLINE_RULES_2_2,
    ):
        old = legacy.AlertOutcomeEvaluator()

        strategy_sets = [
            None,
            ["Rule of 3"],
            ["Pressure to Goal (5m)"],
            ["Δ(5min)"],
            ["Omega"],
            ["Unknown Strat"],
        ]
        for alert_m, goal_m, names, scored, trigger in itertools.product(
            (10, 30, 45, 70),
            (15, 35, 50, 55, 90),
            strategy_sets,
            (None, "home", "away"),
            (None, "home", "away"),
        ):
            if goal_m < alert_m:
                continue
            if scored == "away":
                goal_score = "0-1"
            else:
                goal_score = "1-0"
            old_d = old.evaluate_on_goal(
                alert_m,
                goal_m,
                "0-0",
                goal_score,
                scored_team=scored,
                trigger_team=trigger,
                strategy_names=names,
            )
            new_d = new.on_goal(
                alert_m,
                goal_m,
                "0-0",
                goal_score,
                scored_team=scored,
                trigger_team=trigger,
                strategy_names=names,
            )
            checked += 1
            if _state(old_d) != _state(new_d):
                divergences.append(
                    f"on_goal: 2.2={_state(old_d)} 3.0={_state(new_d)} "
                    f"a={alert_m} g={goal_m} names={names} scored={scored} trigger={trigger}"
                )

        for alert_m, cur_m, names, trigger, opp in itertools.product(
            (20, 40),
            (30, 42, 50, 65),
            (None, ["Rule of 3"], ["Δ(5min)"]),
            (None, "home"),
            (None, "away"),
        ):
            old_d = old.evaluate_on_expiration(
                alert_m,
                cur_m,
                strategy_names=names,
                trigger_team=trigger,
                opponent_goal_team=opp,
                opponent_goal_minute=35,
            )
            new_d = new.on_expiration(
                alert_m,
                cur_m,
                strategy_names=names,
                trigger_team=trigger,
                opponent_goal_team=opp,
                opponent_goal_minute=35,
            )
            checked += 1
            if _state(old_d) != _state(new_d):
                divergences.append(
                    f"on_exp: 2.2={_state(old_d)} 3.0={_state(new_d)} "
                    f"a={alert_m} c={cur_m} names={names} t={trigger} opp={opp}"
                )

        for alert_m, a_score, f_score, names, trigger in itertools.product(
            (30, 70),
            ("0-0", "1-0"),
            ("0-0", "1-0", "0-1", "2-1"),
            (None, ["Rule of 3"], ["Δ(5min)"]),
            (None, "home", "away"),
        ):
            old_d = old.evaluate_on_match_end(
                alert_m,
                90,
                a_score,
                f_score,
                strategy_names=names,
                trigger_team=trigger,
            )
            new_d = new.on_match_end(
                alert_m,
                90,
                a_score,
                f_score,
                strategy_names=names,
                trigger_team=trigger,
            )
            checked += 1
            if _state(old_d) != _state(new_d):
                divergences.append(
                    f"on_match_end: 2.2={_state(old_d)} 3.0={_state(new_d)} "
                    f"a={alert_m} {a_score}->{f_score} names={names} t={trigger}"
                )

    print(f"compared {checked} decisions")
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:40]:
            print(f"  {line}")
        return 1
    print("identical across the goal / expiry / match-end grids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
