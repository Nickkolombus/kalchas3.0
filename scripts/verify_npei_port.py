"""Differential check: does the 3.0 NPEI match 2.2 exactly?

Compares both teams' capped scores, raw scores, ratios, window start and zone
labels over generated timelines (including half-time / ET window clamps and
thinned polling).

    uv run python scripts/verify_npei_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from kalchas_core.match import MatchTimeline
from kalchas_core.npei import compute_npei
from kalchas_core.weights import WeightSet

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")
TOLERANCE = 1e-9

STATS = (
    "attacks",
    "dangerous_attacks",
    "shots_on_target",
    "shots_off_target",
)


def load_legacy(root: Path):
    for name in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "psycopg2.extensions"):
        sys.modules.setdefault(name, MagicMock())
    sys.path.insert(0, str(root))
    try:
        from utils import npei_calculator as legacy  # type: ignore
    except Exception as exc:
        raise SystemExit(f"could not import 2.2 npei_calculator: {exc!r}") from exc
    return legacy


def build_history(current_minute: int, seed: int) -> dict[str, dict[str, dict[str, int]]]:
    rng = random.Random(seed)  # noqa: S311
    history: dict[str, dict[str, dict[str, int]]] = {}
    totals = {(stat, side): 0 for stat in STATS for side in ("home", "away")}

    for minute in range(1, current_minute + 1):
        for stat in STATS:
            for side in ("home", "away"):
                cap = 5 if stat == "attacks" else 3 if "dangerous" in stat else 2
                totals[(stat, side)] += rng.randint(0, cap)
        history[str(minute)] = {
            stat: {side: totals[(stat, side)] for side in ("home", "away")} for stat in STATS
        }
    return history


def drop_minutes(history: dict, keep_every: int) -> dict:
    if keep_every <= 1:
        return history
    minutes = sorted(int(m) for m in history)
    return {str(m): history[str(m)] for m in minutes if m % keep_every == 0 or m == minutes[-1]}


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    legacy = load_legacy(root)
    weights = WeightSet.defaults()

    # Pin 2.2 to registry defaults so a live Railway DB cannot skew the grid.
    defaults = {
        "w1_attack_conv": weights.get("npei", "w1_attack_conv"),
        "w2_shot_accuracy": weights.get("npei", "w2_shot_accuracy"),
        "w3_shot_creation": weights.get("npei", "w3_shot_creation"),
        "min_attacks": weights.get("npei", "min_attacks"),
        "min_shots": weights.get("npei", "min_shots"),
        "zone_max_totally": weights.get("npei", "zone_max_totally"),
        "zone_max_inefficient": weights.get("npei", "zone_max_inefficient"),
        "zone_max_moderate": weights.get("npei", "zone_max_moderate"),
        "zone_max_efficient": weights.get("npei", "zone_max_efficient"),
    }

    def fake_resolve(strategy: str, key: str, default: float = 0.0) -> float:
        if strategy == "npei" and key in defaults:
            return float(defaults[key])
        return float(default)

    minutes = [5, 6, 9, 10, 11, 20, 44, 50, 51, 52, 55, 56, 60, 75, 90, 97, 100, 105, 111]
    thinning = [1, 3, 7]
    checked = 0
    both_none = 0
    divergences: list[str] = []

    with patch.dict("sys.modules", {"utils.strategy_weights": MagicMock(resolve=fake_resolve)}):
        for seed, (minute, keep) in enumerate(itertools.product(minutes, thinning)):
            history = drop_minutes(build_history(minute, seed), keep)
            match_data = {"current_minute": minute, "minute_by_minute": history}

            old = legacy.compute_npei(match_data)
            new = compute_npei(MatchTimeline.from_raw(history, minute), weights=weights)
            checked += 1

            if not old.get("ok") and new is None:
                both_none += 1
                continue
            if bool(old.get("ok")) != (new is not None):
                divergences.append(
                    f"ok mismatch: 2.2={old.get('ok')!r} 3.0={new is not None} "
                    f"minute={minute} keep={keep} seed={seed}"
                )
                continue
            if new is None:
                continue

            pairs = [
                ("home_signal", old["home_signal"], new.home.score),
                ("away_signal", old["away_signal"], new.away.score),
                ("home_raw", old["home_signal_raw"], new.home.raw_score),
                ("away_raw", old["away_signal_raw"], new.away.raw_score),
                ("r1_home", old["r1_home"], new.home.attack_conversion),
                ("r2_home", old["r2_home"], new.home.shot_accuracy),
                ("r3_home", old["r3_home"], new.home.shot_creation),
                ("r1_away", old["r1_away"], new.away.attack_conversion),
                ("r2_away", old["r2_away"], new.away.shot_accuracy),
                ("r3_away", old["r3_away"], new.away.shot_creation),
                ("window_start", old["window_start_minute"], new.window_start_minute),
                ("home_zone", old["home_zone"], new.home.zone.label),
                ("away_zone", old["away_zone"], new.away.zone.label),
            ]
            for label, a, b in pairs:
                if a is None and b is None:
                    continue
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    if abs(float(a) - float(b)) > TOLERANCE:
                        divergences.append(
                            f"{label}: 2.2={a!r} 3.0={b!r} minute={minute} keep={keep}"
                        )
                elif a != b:
                    divergences.append(f"{label}: 2.2={a!r} 3.0={b!r} minute={minute} keep={keep}")

    print(
        f"compared {checked} timelines "
        f"({checked - both_none} with a reading, {both_none} both empty)"
    )
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:40]:
            print(f"  {line}")
        return 1
    print("identical across the NPEI grid (scores, ratios, window, zones)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
