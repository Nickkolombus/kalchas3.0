"""Differential: H2H compute_h2h_stats / timing vs 2.2 h2h_service.

uv run python scripts/verify_h2h_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path
from unittest.mock import MagicMock

from kalchas_core.h2h import compute_h2h_stats, compute_timing_counts

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")


def load_legacy(root: Path):
    for name in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "psycopg2.extensions"):
        sys.modules.setdefault(name, MagicMock())
    sys.path.insert(0, str(root))
    from utils import h2h_service as legacy  # type: ignore

    return legacy


def random_fixtures(rng: random.Random, t1: int, t2: int, n: int) -> list[dict]:
    out = []
    for i in range(n):
        t1_home = rng.random() < 0.5
        hs, aws = rng.randint(0, 5), rng.randint(0, 5)
        if t1_home:
            out.append(
                {
                    "match_id": f"m{i}",
                    "home_team_id": t1,
                    "away_team_id": t2,
                    "home_score": hs,
                    "away_score": aws,
                    "match_date": f"2025-{i + 1:02d}-01",
                    "home_team": "A",
                    "away_team": "B",
                }
            )
        else:
            out.append(
                {
                    "match_id": f"m{i}",
                    "home_team_id": t2,
                    "away_team_id": t1,
                    "home_score": hs,
                    "away_score": aws,
                    "match_date": f"2025-{i + 1:02d}-01",
                    "home_team": "B",
                    "away_team": "A",
                }
            )
    # occasional duplicate
    if out and rng.random() < 0.3:
        out.append(dict(out[0]))
    return out


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    legacy = load_legacy(root)
    divergences: list[str] = []
    checked = 0

    for seed, min_sample in itertools.product(range(300), (3, 5)):
        rng = random.Random(seed)  # noqa: S311
        t1, t2 = 10, 20
        fixtures = random_fixtures(rng, t1, t2, rng.randint(0, 12))
        old = legacy.compute_h2h_stats(
            fixtures,
            team1_id=t1,
            team2_id=t2,
            team1_name="A",
            team2_name="B",
            min_sample=min_sample,
        )
        new = compute_h2h_stats(
            fixtures,
            team1_id=t1,
            team2_id=t2,
            team1_name="A",
            team2_name="B",
            min_sample=min_sample,
        )
        checked += 1
        pairs = [
            ("ok", old["ok"], new.ok),
            ("insufficient", old["insufficient"], new.insufficient),
            ("sample", old["sample"], new.sample),
            ("draws", old["draws"], new.draws),
            ("t1_wins", old["team1"]["wins"], new.team1.wins),
            ("t2_wins", old["team2"]["wins"], new.team2.wins),
            ("t1_goals", old["team1"]["goals_total"], new.team1.goals_total),
            ("t2_goals", old["team2"]["goals_total"], new.team2.goals_total),
            ("btts", old["btts"]["count"], new.btts.count),
            ("btts_pct", old["btts"]["pct"], new.btts.pct),
            ("over", old["over_2_5"]["count"], new.over_2_5.count),
            ("under", old["under_2_5"]["count"], new.under_2_5.count),
            ("home_cs", old["home_cs"]["count"], new.home_cs.count),
            ("away_cs", old["away_cs"]["count"], new.away_cs.count),
            ("avg", old["avg_goals"], new.avg_goals),
            ("attributed", old.get("attributed", new.attributed), new.attributed),
        ]
        for label, a, b in pairs:
            if a != b:
                divergences.append(f"{label}: 2.2={a!r} 3.0={b!r} seed={seed}")

    # Timing
    for seed in range(100):
        rng = random.Random(seed)  # noqa: S311
        enriched = []
        for _ in range(rng.randint(0, 8)):
            if rng.random() < 0.2:
                enriched.append({})
                continue
            n_ev = rng.randint(1, 4)
            events = [
                {"minute": rng.randint(1, 95), "team": rng.choice(["home", "away", ""])}
                for _ in range(n_ev)
            ]
            enriched.append({"goal_events": events})
        old_t = legacy._compute_timing_counts(enriched)
        new_t = compute_timing_counts(enriched)
        checked += 1
        if old_t is None and new_t is None:
            continue
        if (old_t is None) != (new_t is None):
            divergences.append(f"timing none mismatch seed={seed}")
            continue
        for key in (
            "sample",
            "late_goals",
            "final_15",
            "stoppage_time_goals",
            "early_goals_15",
            "fast_start_10",
            "first_half_goals",
            "btts_first_half",
            "first_goal_before_30",
        ):
            if key == "sample":
                if old_t[key] != new_t.sample:
                    divergences.append(f"timing.sample: {old_t[key]} vs {new_t.sample}")
            else:
                ov, nv = old_t[key], getattr(new_t, key)
                if ov["count"] != nv.count or ov["pct"] != nv.pct:
                    divergences.append(f"timing.{key}: {ov} vs {nv}")

    print(f"compared {checked} H2H / timing calculations")
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:30]:
            print(f"  {line}")
        return 1
    print("identical across the H2H and timing grids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
