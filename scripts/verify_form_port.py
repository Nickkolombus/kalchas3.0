"""Differential: form metrics vs Strategy 9's `_calculate_team_form`.

uv run python scripts/verify_form_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from kalchas_core.form import calculate_team_form

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")


def load_legacy(root: Path):
    for name in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "psycopg2.extensions"):
        sys.modules.setdefault(name, MagicMock())
    sys.path.insert(0, str(root))
    with patch("builtins.open", side_effect=FileNotFoundError):
        from strategies.strategy_009_team_form_intelligence import formula as legacy  # type: ignore
    return legacy


def random_fixtures(rng: random.Random, team_id: int, n: int) -> list[dict]:
    out = []
    for i in range(n):
        is_home = rng.random() < 0.5
        hs, aws = rng.randint(0, 4), rng.randint(0, 4)
        if is_home:
            out.append(
                {
                    "match_hometeam_id": team_id,
                    "match_awayteam_id": team_id + 100 + i,
                    "match_hometeam_score": hs,
                    "match_awayteam_score": aws,
                    "match_date": f"2026-01-{i + 1:02d}",
                }
            )
        else:
            out.append(
                {
                    "match_hometeam_id": team_id + 200 + i,
                    "match_awayteam_id": team_id,
                    "match_hometeam_score": hs,
                    "match_awayteam_score": aws,
                    "match_date": f"2026-01-{i + 1:02d}",
                }
            )
    return out


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    legacy = load_legacy(root)
    strat = legacy.Strategy9TeamForm()
    divergences: list[str] = []
    checked = 0

    for seed, window in itertools.product(range(200), (3, 5, 8)):
        rng = random.Random(seed)  # noqa: S311
        team_id = 42
        fixtures = random_fixtures(rng, team_id, rng.randint(0, 12))
        old = strat._calculate_team_form(fixtures, team_id, window)
        new = calculate_team_form(fixtures, team_id, window)
        checked += 1
        pairs = [
            ("games_played", old["games_played"], new.games_played),
            ("wins", old["wins"], new.wins),
            ("draws", old["draws"], new.draws),
            ("losses", old["losses"], new.losses),
            ("goals_for", old["goals_for"], new.goals_for),
            ("goals_against", old["goals_against"], new.goals_against),
            ("goal_difference", old["goal_difference"], new.goal_difference),
            ("goals_per_game", old["goals_per_game"], new.goals_per_game),
            ("goals_against_per_game", old["goals_against_per_game"], new.goals_against_per_game),
            ("form_string", old["form_string"], new.form_string),
            ("results_last5", list(old["results_last5"]), list(new.results_last5)),
            ("streak_type", old["current_streak"]["type"], new.current_streak.type),
            ("streak_count", old["current_streak"]["count"], new.current_streak.count),
        ]
        for label, a, b in pairs:
            if a != b:
                divergences.append(f"{label}: 2.2={a!r} 3.0={b!r} seed={seed} w={window}")

    print(f"compared {checked} form calculations")
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:30]:
            print(f"  {line}")
        return 1
    print("identical across the form grid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
