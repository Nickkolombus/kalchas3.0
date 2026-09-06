"""Differential check: does the 3.0 Delta 5min match 2.2 exactly?

This one matters more than the others. In 2.2 the coefficients were hardcoded
in `utils/delta_calculator.py` (SOT x 2.0, secondary x 0.5) and the registry
default for `da_weight` was 1.0, which nothing read. 3.0 wires the coefficients
through the registry and corrects that default to 0.5. This script is the proof
that doing so left every computed value and every trigger decision unchanged.

Compares the pressure values, the corroboration gate, and which team triggers.

    uv run python scripts/verify_delta_5min_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import asyncio
import importlib.util
import itertools
import random
import sys
from pathlib import Path

from kalchas_core.match import MatchTimeline
from kalchas_core.strategies.delta_5min import evaluate

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")
TOLERANCE = 1e-9

STATS = ("shots_on_target", "shots_off_target", "dangerous_attacks", "attacks", "corners")


def load_legacy(root: Path):
    """Load 2.2's delta calculator and strategy 4 formula in isolation."""
    if not (root / "utils" / "delta_calculator.py").exists():
        raise SystemExit(f"2.2 checkout not found under {root}")

    sys.path.insert(0, str(root))
    try:
        from utils.delta_calculator import calculate_delta_5min_pressure  # type: ignore

        spec = importlib.util.spec_from_file_location(
            "legacy_strategy_004",
            root / "strategies" / "strategy_004_delta_5min" / "formula.py",
        )
        if spec is None or spec.loader is None:
            raise SystemExit("could not load strategy 4 formula")
        strategy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(strategy)
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(f"could not import 2.2 delta modules: {exc!r}") from exc

    return calculate_delta_5min_pressure, strategy


def build_history(current_minute: int, seed: int, *, allow_regression: bool) -> dict:
    """Cumulative stat history. Optionally lets a counter revise downward.

    Totals stay at or above zero even when regressing. A feed does revise a
    count down (5 shots becomes 4 after review), but a cumulative counter is
    never negative, and generating one would only measure the difference
    between 2.2 reading the raw dict and 3.0 flooring the counter at parse.
    A downward revision still produces the negative *delta* this is testing.
    """
    rng = random.Random(seed)  # noqa: S311 - fixture data, deliberately reproducible
    history: dict = {}
    totals = {(stat, side): 0 for stat in STATS for side in ("home", "away")}

    # Occasionally suppress shots on target entirely, so the possession
    # fallback branch is actually exercised rather than merely ported.
    goalless = rng.random() < 0.25
    home_possession = rng.randint(35, 65)

    for minute in range(1, current_minute + 1):
        for stat in STATS:
            for side in ("home", "away"):
                if goalless and stat == "shots_on_target":
                    continue
                step = rng.randint(0, 4 if stat in ("dangerous_attacks", "attacks") else 2)
                if allow_regression and rng.random() < 0.15:
                    step = -rng.randint(1, 3)
                totals[(stat, side)] = max(0, totals[(stat, side)] + step)

        home_possession = max(20, min(80, home_possession + rng.randint(-4, 4)))
        history[str(minute)] = {
            stat: {side: totals[(stat, side)] for side in ("home", "away")} for stat in STATS
        }
        history[str(minute)]["possession"] = {
            "home": home_possession,
            "away": 100 - home_possession,
        }
    return history


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    calculate_delta, strategy = load_legacy(root)

    minutes = [5, 6, 7, 10, 20, 44, 50, 51, 52, 53, 55, 56, 60, 75, 90, 97, 100, 111, 115]
    regressions = [False, True]

    checked = 0
    negative_delta_cases = 0
    possession_fallback_cases = 0
    divergences: list[str] = []

    for seed, (minute, allow_regression) in enumerate(itertools.product(minutes, regressions)):
        for repeat in range(40):
            history = build_history(minute, seed * 100 + repeat, allow_regression=allow_regression)

            match_data = {
                "match_id": f"verify-{seed}-{repeat}",
                "current_minute": minute,
                "minute_by_minute": history,
                "home_team": "H",
                "away_team": "A",
            }
            # 2.2 required the background monitor to run first and write the
            # delta into the match dict; the strategy only read it back.
            calculate_delta(match_data)
            legacy = asyncio.run(strategy.calculate(match_data))

            result = evaluate(MatchTimeline.from_raw(history, minute))

            legacy_team = legacy.get("team") if legacy else None
            legacy_value = float(legacy["value"]) if legacy else 0.0

            new_side = result.triggering_team if result else None
            new_team = new_side.value if new_side else None
            new_value = result.trigger_value if result else 0.0

            checked += 1
            if result and result.secondary_signal.value == "possession":
                possession_fallback_cases += 1
            if (
                result
                and min(
                    result.home.shots_on_target_delta,
                    result.home.secondary_delta,
                    result.away.shots_on_target_delta,
                    result.away.secondary_delta,
                )
                < 0
            ):
                negative_delta_cases += 1

            context = f"(minute={minute} regression={allow_regression} seed={seed}-{repeat})"

            if legacy_team != new_team:
                divergences.append(f"trigger: 2.2={legacy_team!r} 3.0={new_team!r} {context}")
            elif abs(legacy_value - new_value) > TOLERANCE:
                divergences.append(f"value: 2.2={legacy_value!r} 3.0={new_value!r} {context}")
            elif legacy:
                for label, old, new in (
                    ("home_delta", float(legacy["home_delta"]), result.home.pressure),
                    ("away_delta", float(legacy["away_delta"]), result.away.pressure),
                ):
                    if abs(old - new) > TOLERANCE:
                        divergences.append(f"{label}: 2.2={old!r} 3.0={new!r} {context}")

    print(f"compared {checked} timelines (values, gate, and trigger decision)")
    print(
        f"of which {negative_delta_cases} produced a negative delta "
        "-- the unclamped behaviour this port preserves"
    )
    print(f"and {possession_fallback_cases} took the possession fallback branch")
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:25]:
            print(f"  {line}")
        return 1

    print("identical across the whole grid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
