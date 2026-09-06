"""Differential check: does the 3.0 Delta Goal match 2.2 exactly?

Strategy 3 is the one with real arithmetic depth -- normalisation, two
sigmoids, a confidence blend and a weighted composite -- so this compares the
whole intermediate chain per team, not just the final decision. Any drift in
an early term would otherwise hide behind the threshold.

2.2's formula.py reaches for PostgreSQL and the learning layer on import, so
the singleton is patched before use: the shadow-mode engine, the feature
collector and the learning recorder are all stubbed out. None of them feed the
alert number, which is the point being demonstrated.

    uv run python scripts/verify_delta_goal_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import asyncio
import itertools
import random
import sys
from pathlib import Path
from unittest.mock import MagicMock

from kalchas_core.match import MatchTimeline
from kalchas_core.strategies.delta_goal import MAX_THREAT_SCORE, evaluate

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")
TOLERANCE = 1e-9

STATS = (
    "shots_on_target",
    "shots_off_target",
    "corners",
    "dangerous_attacks",
    "fouls",
)

LEAGUES = ["152", "175", "207", "73", "999999", None]


class _NullCollector:
    """Stands in for DataCollector, which writes feature rows to PostgreSQL."""

    def log_features(self, *args: object, **kwargs: object) -> None:
        return None

    def log_shadow_decision(self, *args: object, **kwargs: object) -> None:
        return None


class _NullLearning:
    """Stands in for SafeLearningSystem, which persists weights to JSON."""

    def record_prediction(self, *args: object, **kwargs: object) -> None:
        return None


def stub_absent_drivers() -> None:
    """Satisfy 2.2's import-time database dependencies.

    `formula.py` imports `data_collector`, which imports `psycopg2` at module
    scope. 3.0's core has no database driver and never will, so the driver is
    faked well enough to get through the import. That the alert math runs to
    completion against a fake driver is itself part of the finding.
    """
    for name in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "psycopg2.extensions"):
        sys.modules.setdefault(name, MagicMock())


def load_legacy(root: Path):
    """Load 2.2's strategy 3 singleton with its IO dependencies stubbed."""
    formula_path = root / "strategies" / "strategy_003_delta_goal" / "formula.py"
    if not formula_path.exists():
        raise SystemExit(f"2.2 checkout not found under {root}")

    stub_absent_drivers()
    sys.path.insert(0, str(root))
    try:
        # The module uses relative imports, so it has to load as part of its package.
        import strategies.strategy_003_delta_goal.formula as legacy  # type: ignore
    except Exception as exc:
        raise SystemExit(f"could not import 2.2 strategy 3: {exc!r}") from exc

    singleton = legacy.enhanced_strategy3_formula

    # Detach every side effect. Shadow mode would build a MathEngine per match
    # and log to Postgres; the learning layer would append to JSON files.
    singleton.data_collector = _NullCollector()
    singleton.safe_learning = _NullLearning()
    singleton.shadow_engines = _NoShadow()

    return legacy, singleton


class _NoShadow(dict):
    """A dict that refuses to hold shadow engines, short-circuiting shadow mode."""

    def __contains__(self, key: object) -> bool:
        return True

    def __getitem__(self, key: object) -> object:
        raise RuntimeError("shadow mode disabled for verification")


def build_history(current_minute: int, seed: int, *, intensity: str) -> dict:
    """Cumulative stat history at a chosen level of attacking activity."""
    rng = random.Random(seed)  # noqa: S311 - fixture data, deliberately reproducible
    ceilings = {
        "quiet": {"shots_on_target": 0, "shots_off_target": 1, "corners": 0, "fouls": 1},
        "normal": {"shots_on_target": 1, "shots_off_target": 1, "corners": 1, "fouls": 1},
        "intense": {"shots_on_target": 2, "shots_off_target": 2, "corners": 2, "fouls": 2},
        "fouls_only": {"shots_on_target": 0, "shots_off_target": 0, "corners": 0, "fouls": 3},
    }[intensity]

    history: dict = {}
    totals = {(stat, side): 0 for stat in STATS for side in ("home", "away")}

    for minute in range(1, current_minute + 1):
        # Drop the occasional minute, so the snapshot backfill is exercised.
        if minute < current_minute and rng.random() < 0.15:
            continue
        for stat in STATS:
            ceiling = ceilings.get(stat, 4)
            for side in ("home", "away"):
                totals[(stat, side)] += rng.randint(0, ceiling)
        history[str(minute)] = {
            stat: {side: totals[(stat, side)] for side in ("home", "away")} for stat in STATS
        }
    return history


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    _, singleton = load_legacy(root)

    minutes = [10, 11, 15, 25, 44, 46, 50, 60, 70, 76, 85, 90, 95]
    intensities = ["quiet", "normal", "intense", "fouls_only"]
    scorelines = [(0, 0), (1, 0), (0, 2), (2, 2)]

    checked = 0
    triggered = 0
    over_max = 0
    divergences: list[str] = []

    grid = itertools.product(minutes, intensities, scorelines, LEAGUES)

    for seed, (minute, intensity, (home_score, away_score), league) in enumerate(grid):
        history = build_history(minute, seed, intensity=intensity)

        match_data = {
            "match_id": f"verify-{seed}",
            "current_minute": minute,
            "minute_by_minute": history,
            "home_team": "H",
            "away_team": "A",
            "score": {"home": home_score, "away": away_score},
            "league_id": league if league is not None else "ALL",
        }

        legacy_result = asyncio.run(singleton.calculate(match_data))
        result = evaluate(
            MatchTimeline.from_raw(history, minute),
            home_score=home_score,
            away_score=away_score,
            league_id=league if league is not None else "ALL",
            threshold=singleton.config.alert_threshold,
        )

        checked += 1
        context = (
            f"(minute={minute} {intensity} {home_score}-{away_score} league={league} seed={seed})"
        )

        legacy_triggered = bool(legacy_result and legacy_result.get("triggered"))
        new_side = result.triggering_team
        new_triggered = new_side is not None

        if legacy_triggered:
            triggered += 1

        if legacy_triggered != new_triggered:
            divergences.append(f"triggered: 2.2={legacy_triggered} 3.0={new_triggered} {context}")
            continue

        if not legacy_triggered:
            continue

        if new_side is None:
            continue
        team = result.team(new_side)
        if team.threat > MAX_THREAT_SCORE:
            over_max += 1

        for label, old, new in (
            ("team", legacy_result["team"], new_side.value),
            ("threat_score", legacy_result["threat_score"], team.threat),
            ("value", legacy_result["value"], result.trigger_value),
            ("tier", legacy_result["tier"], team.tier.value if team.tier else None),
            ("pressure_score", legacy_result["pressure_score"], team.pressure_score),
            ("lift", legacy_result["lift"], team.lift),
            ("lambda", legacy_result["lambda"], team.confidence),
            ("raw_probability", legacy_result["raw_probability"], team.probability),
        ):
            differs = (
                abs(float(old) - float(new)) > TOLERANCE
                if isinstance(old, (int, float))
                else old != new
            )
            if differs:
                divergences.append(f"{label}: 2.2={old!r} 3.0={new!r} {context}")

    print(f"compared {checked} matches, {triggered} of which triggered in 2.2")
    print(f"{over_max} triggering scores exceeded the nominal 20 ceiling")
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:25]:
            print(f"  {line}")
        return 1

    print("identical across the whole grid (decision, tier, team and every intermediate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
