"""Differential check: does the 3.0 Rule of Three match 2.2 exactly?

Runs both implementations over a grid of match situations and reports any
divergence. This is a one-off migration aid, not part of the test suite -- it
needs the 2.2 checkout on disk. Delete it once the port is signed off.

    uv run python scripts/verify_rule_of_three_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

from kalchas_core.strategies.rule_of_three import TeamShotProfile, evaluate, legacy_points

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")
TOLERANCE = 1e-9


def load_legacy(root: Path):
    """Import 2.2's rule_of_three directly, without importing the whole project.

    Its `_w()` helper resolves coefficients through a try/except that falls
    back to hardcoded defaults when `utils.strategy_weights` is unavailable.
    Loading the module in isolation therefore exercises the default path --
    which is exactly what `WeightSet.defaults()` reproduces.
    """
    path = root / "utils" / "rule_of_three.py"
    if not path.exists():
        raise SystemExit(f"2.2 checkout not found at {path}")

    spec = importlib.util.spec_from_file_location("legacy_rule_of_three", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cases():
    """A grid spanning the branches: scorelines, accuracy, odds, possession, time."""
    shots = [(0, 0), (1, 0), (3, 2), (5, 1), (8, 7), (12, 3)]
    scores = [(0, 0), (1, 0), (0, 1), (2, 0), (3, 1), (1, 3), (2, 2), (4, 0)]
    possessions = [None, 30, 50, 71]
    odds = [(None, None), (1.5, 6.0), (6.0, 1.5), (2.0, 2.0), (1.2, 12.0)]
    minutes = [None, 0, 15, 30, 45, 60, 61, 75, 76, 90]

    for (hs, ha), (hg, ag), poss, (ho, ao), minute in itertools.product(
        shots, scores, possessions, odds, minutes
    ):
        yield {
            "home_sot": hs,
            "away_sot": ha,
            "home_shots_off_target": ha,
            "away_shots_off_target": hs,
            "home_goals": hg,
            "away_goals": ag,
            "home_possession": poss,
            "away_possession": None if poss is None else 100 - poss,
            "home_odds": ho,
            "away_odds": ao,
            "match_minute": minute,
        }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    legacy = load_legacy(root)

    checked = 0
    divergences: list[str] = []

    for case in cases():
        legacy_home, legacy_away = legacy.unrealised_goals(league_name="ALL", **case)
        _, _, legacy_pts = legacy.unrealised_goals(league_name="ALL", return_points=True, **case)

        result = evaluate(
            TeamShotProfile(
                shots_on_target=case["home_sot"],
                shots_off_target=case["home_shots_off_target"],
                goals=case["home_goals"],
                possession=case["home_possession"],
                kickoff_odds=case["home_odds"],
            ),
            TeamShotProfile(
                shots_on_target=case["away_sot"],
                shots_off_target=case["away_shots_off_target"],
                goals=case["away_goals"],
                possession=case["away_possession"],
                kickoff_odds=case["away_odds"],
            ),
            minute=case["match_minute"],
        )

        checked += 1
        for label, old, new in (
            ("home", legacy_home, result.home.unrealised_goals),
            ("away", legacy_away, result.away.unrealised_goals),
            ("points", legacy_pts, legacy_points(result)),
        ):
            if abs(old - new) > TOLERANCE:
                divergences.append(f"{label}: 2.2={old!r} 3.0={new!r} for {case}")

    print(f"compared {checked} situations x 3 outputs")
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:20]:
            print(f"  {line}")
        return 1

    print("identical across the whole grid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
