"""Differential check: does the 3.0 Pressure Index match 2.2 exactly?

Runs both implementations over generated match timelines and reports any
divergence in either team's pressure. One-off migration aid, not part of the
test suite -- it needs the 2.2 checkout on disk.

    uv run python scripts/verify_pressure_index_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

from kalchas_core.match import MatchTimeline
from kalchas_core.strategies.pressure_index import evaluate

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")
TOLERANCE = 1e-9

STATS = ("shots_on_target", "shots_off_target", "corners", "dangerous_attacks")


def load_legacy(root: Path):
    """Import 2.2's pressure index service with the repo root on sys.path."""
    if not (root / "utils" / "pressure_index_service.py").exists():
        raise SystemExit(f"2.2 checkout not found under {root}")

    sys.path.insert(0, str(root))
    try:
        from utils.pressure_index_service import PressureIndexService  # type: ignore
    except Exception as exc:
        raise SystemExit(f"could not import 2.2 pressure index service: {exc!r}") from exc
    return PressureIndexService


def build_history(current_minute: int, seed: int) -> dict[str, dict[str, dict[str, int]]]:
    """A plausible cumulative stat history up to `current_minute`."""
    rng = random.Random(seed)  # noqa: S311 - fixture data, deliberately reproducible
    history: dict[str, dict[str, dict[str, int]]] = {}
    totals = {(stat, side): 0 for stat in STATS for side in ("home", "away")}

    for minute in range(1, current_minute + 1):
        for stat in STATS:
            for side in ("home", "away"):
                cap = 4 if stat == "dangerous_attacks" else 2
                totals[(stat, side)] += rng.randint(0, cap)
        history[str(minute)] = {
            stat: {side: totals[(stat, side)] for side in ("home", "away")} for stat in STATS
        }
    return history


def drop_minutes(history: dict, keep_every: int) -> dict:
    """Thin the history to simulate gaps in polling."""
    if keep_every <= 1:
        return history
    minutes = sorted(int(m) for m in history)
    return {str(m): history[str(m)] for m in minutes if m % keep_every == 0 or m == minutes[-1]}


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    service = load_legacy(root)()

    if service.window_minutes != 10:
        print(f"note: 2.2 service configured for a {service.window_minutes}-minute window")

    minutes = [5, 6, 9, 10, 11, 20, 44, 50, 51, 52, 55, 56, 60, 75, 90, 97, 100, 111, 115]
    scores = [(0, 0), (1, 0), (0, 1), (2, 0), (0, 2), (3, 1)]
    thinning = [1, 3, 7]

    checked = 0
    divergences: list[str] = []

    for seed, (minute, (home_goals, away_goals), keep) in enumerate(
        itertools.product(minutes, scores, thinning)
    ):
        history = drop_minutes(build_history(minute, seed), keep)
        match_data = {
            "current_minute": minute,
            "minute_by_minute": history,
            "home_score": home_goals,
            "away_score": away_goals,
            "match_id": f"verify-{seed}",
        }

        legacy = service.calculate_from_json_data(match_data)
        result = evaluate(
            MatchTimeline.from_raw(history, minute),
            home_goals=home_goals,
            away_goals=away_goals,
            window_minutes=service.window_minutes,
        )

        new_home = result.home.pressure if result else 0.0
        new_away = result.away.pressure if result else 0.0

        checked += 1
        for label, old, new in (
            ("home", legacy["home"], new_home),
            ("away", legacy["away"], new_away),
        ):
            if abs(old - new) > TOLERANCE:
                divergences.append(
                    f"{label}: 2.2={old!r} 3.0={new!r} "
                    f"(minute={minute} score={home_goals}-{away_goals} keep_every={keep})"
                )

    print(f"compared {checked} timelines x 2 teams")
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:25]:
            print(f"  {line}")
        return 1

    print("identical across the whole grid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
