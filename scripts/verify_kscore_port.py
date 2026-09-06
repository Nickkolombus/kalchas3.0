"""Differential check: does the 3.0 K-Score match 2.2 exactly?

K-Score is a meta-strategy -- it blends other strategies' outputs -- so this
compares the pure blend (`_per_team` / `compute_kscore_from_signals`) rather
than the slot-7 orchestrator. Two Omega input shapes are exercised:

* alert path: acceleration only (baseline/level absent → zero) -- reproduces
  the truncated vote that slot 7 shipped
* dashboard path: full accel + baseline + level -- reproduces
  `resolve_match_kscore`

    uv run python scripts/verify_kscore_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path
from unittest.mock import MagicMock

from kalchas_core.match import Side
from kalchas_core.strategies.kscore import (
    MatchContext,
    TeamSignals,
    evaluate,
    evaluate_team,
)
from kalchas_core.weights import WeightSet

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")
TOLERANCE = 1e-12


def load_legacy(root: Path):
    for name in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "psycopg2.extensions"):
        sys.modules.setdefault(name, MagicMock())
    sys.path.insert(0, str(root))
    try:
        from utils import kscore_formula as legacy  # type: ignore
    except Exception as exc:
        raise SystemExit(f"could not import 2.2 kscore_formula: {exc!r}") from exc
    return legacy


def random_signals(rng: random.Random, *, full_omega: bool) -> dict:
    """One team's signals in the shape 2.2's compute_kscore_from_signals expects."""
    signals = {
        "delta_5min": rng.uniform(0, 40),
        "pressure_index": rng.uniform(0, 100),
        "rule_of_three": rng.uniform(-0.3, 1.5),
        "npei": rng.uniform(0, 100),
        "omega_theta": rng.uniform(-45, 45),
        "omega_alpha": rng.uniform(-30, 30),
        "omega_accel": rng.uniform(0, 50),
    }
    if full_omega:
        signals["omega_baseline"] = rng.uniform(-5, 10)
        signals["omega_level"] = rng.uniform(0, 100)
    return signals


def to_team_signals(raw: dict, *, full_omega: bool) -> TeamSignals:
    return TeamSignals(
        delta_5min=raw["delta_5min"],
        pressure_index=raw["pressure_index"],
        rule_of_three=raw["rule_of_three"],
        npei=raw["npei"],
        omega_acceleration=raw["omega_accel"],
        omega_baseline=raw.get("omega_baseline") if full_omega else None,
        omega_level=raw.get("omega_level") if full_omega else None,
        omega_theta=raw["omega_theta"],
        omega_alpha=raw["omega_alpha"],
    )


def random_context(rng: random.Random) -> MatchContext | None:
    if rng.random() < 0.3:
        return None
    home_odds = rng.uniform(1.2, 8.0)
    away_odds = rng.uniform(1.2, 8.0)
    return MatchContext(
        minute=rng.randint(0, 95),
        home_score=rng.randint(0, 4),
        away_score=rng.randint(0, 4),
        home_red_cards=rng.choice([0, 0, 0, 1, 2]),
        away_red_cards=rng.choice([0, 0, 0, 1]),
        home_kickoff_odds=home_odds if rng.random() > 0.2 else None,
        away_kickoff_odds=away_odds if rng.random() > 0.2 else None,
    )


def context_as_legacy(ctx: MatchContext | None) -> dict | None:
    if ctx is None:
        return None
    return {
        "red_cards": {"home": ctx.home_red_cards, "away": ctx.away_red_cards},
        "home_score": ctx.home_score,
        "away_score": ctx.away_score,
        "minute": ctx.minute,
        "ko_odds_home": ctx.home_kickoff_odds,
        "ko_odds_away": ctx.away_kickoff_odds,
    }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    legacy = load_legacy(root)
    weights = WeightSet.defaults()
    legacy_weights = {
        key: weights.get("kscore", key)
        for key in (
            "trust_momentum",
            "trust_pressure",
            "trust_rule3",
            "trust_omega",
            "phi_floor",
            "bias",
            "momentum_scale",
            "horizon",
            "ctx_red_card",
            "ctx_ko_prior",
            "ctx_trailing",
            "ctx_late_minute",
        )
    }

    checked = 0
    alert_path = 0
    dashboard_path = 0
    divergences: list[str] = []

    for seed, full_omega in itertools.product(range(400), (False, True)):
        rng = random.Random(seed)  # noqa: S311
        home_raw = random_signals(rng, full_omega=full_omega)
        away_raw = random_signals(rng, full_omega=full_omega)
        ctx = random_context(rng)

        legacy_signals = {
            "home": home_raw,
            "away": away_raw,
            "context": context_as_legacy(ctx),
        }
        legacy_result = legacy.compute_kscore_from_signals(legacy_signals, weights=legacy_weights)

        result = evaluate(
            to_team_signals(home_raw, full_omega=full_omega),
            to_team_signals(away_raw, full_omega=full_omega),
            context=ctx,
            weights=weights,
        )

        checked += 1
        if full_omega:
            dashboard_path += 1
        else:
            alert_path += 1

        context = f"(seed={seed} full_omega={full_omega})"
        for label, old, new in (
            ("match", legacy_result["match"], result.match_score),
            ("home", legacy_result["home"], result.home.score),
            ("away", legacy_result["away"], result.away.score),
        ):
            if old != new:
                divergences.append(f"{label}: 2.2={old!r} 3.0={new!r} {context}")

        # Also pin the per-team intermediates on a subset, so a score that
        # happens to round the same still can't hide a drift in the logit.
        if seed % 20 == 0:
            for side_name, raw, side in (
                ("home", home_raw, Side.HOME),
                ("away", away_raw, Side.AWAY),
            ):
                legacy_team = legacy._per_team(
                    raw["delta_5min"],
                    raw["pressure_index"],
                    raw["rule_of_three"],
                    raw["npei"],
                    raw["omega_theta"],
                    raw["omega_alpha"],
                    legacy_weights,
                    side=side_name,
                    context=context_as_legacy(ctx),
                    omega_accel=raw["omega_accel"],
                    omega_baseline=raw.get("omega_baseline") if full_omega else None,
                    omega_level=raw.get("omega_level") if full_omega else None,
                )
                team = evaluate_team(
                    to_team_signals(raw, full_omega=full_omega),
                    side=side,
                    context=ctx,
                    weights=weights,
                )
                for label, old, new in (
                    ("logit", legacy_team["logit"], team.logit),
                    ("p", legacy_team["p"], team.probability),
                    ("p_raw", legacy_team["p_raw"], team.probability_raw),
                    ("focus", legacy_team["focus"], team.focus),
                ):
                    if abs(float(old) - float(new)) > TOLERANCE:
                        divergences.append(
                            f"{side_name}.{label}: 2.2={old!r} 3.0={new!r} {context}"
                        )

    print(
        f"compared {checked} signal pairs "
        f"({alert_path} alert-path Omega, {dashboard_path} dashboard-path Omega)"
    )
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:25]:
            print(f"  {line}")
        return 1

    print("identical across the whole grid (scores and intermediate chain)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
