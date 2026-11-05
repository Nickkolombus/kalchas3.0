"""Player shot runs on the watchlist page."""

from __future__ import annotations

from typing import Any

from kalchas_core.watchlist.shots import MIN_GAMES, has_covered_games, team_shots

TEAM = 10


def game(day: int, lines: list[list[Any]], *, covered: bool = True) -> dict[str, Any]:
    row: dict[str, Any] = {
        "match_id": f"m{day}",
        "match_date": f"2026-10-{day:02d}",
        "status_short": "FT",
        "home_team_id": TEAM,
        "away_team_id": 99,
        "home_score": 1,
        "away_score": 0,
    }
    if covered:
        row["players"] = {"home": lines, "away": [["x", "Other", 90, 9, 9]]}
    return row


def test_runs_count_appearances_newest_first_and_skip_uncovered_games() -> None:
    shots = [6, 1, 2, 2, 0, 5]
    rows = [game(10 + i, [["s", "Striker", 90, n, 1 if n else 0]]) for i, n in enumerate(shots)]
    rows.append(game(30, [], covered=False))  # no data: must not read as a 0
    out = team_shots(rows, TEAM)
    assert out is not None
    [p] = out["players"]
    assert out["games"] == 6
    assert p["shots"] == list(reversed(shots))
    assert p["per_90"] == round(sum(shots) / 6, 1)
    hits = {(x["stat"], x["at_least"]): x["hits"] for x in p["lines"]}
    assert hits == {("shots", 1): 5, ("shots", 2): 4, ("shots", 3): 2, ("on_target", 1): 5}


def test_only_the_opponents_side_never_counts() -> None:
    rows = [game(10 + i, [["s", "Striker", 90, 1, 0]]) for i in range(6)]
    names = [p["name"] for p in (team_shots(rows, TEAM) or {})["players"]]
    assert names == ["Striker"]


def test_players_gone_from_the_side_or_rarely_used_drop_out() -> None:
    rows = []
    for i in range(8):
        lines = [["s", "Striker", 90, 2, 1]]
        if i < 5:  # five oldest games only: left the club
            lines.append(["g", "Gone", 90, 5, 3])
        if i == 7:  # one cameo
            lines.append(["c", "Cameo", 20, 3, 1])
        rows.append(game(10 + i, lines))
    names = [p["name"] for p in (team_shots(rows, TEAM) or {})["players"]]
    assert names == ["Striker"]


def test_too_few_covered_games_gives_nothing() -> None:
    rows = [game(10 + i, [["s", "Striker", 90, 2, 1]]) for i in range(MIN_GAMES - 1)]
    assert team_shots(rows, TEAM) is None
    assert has_covered_games(rows)
    assert not has_covered_games([game(1, [], covered=False)])


def test_a_super_sub_with_a_high_per_90_ranks_below_a_regular_shooter() -> None:
    rows = []
    for i in range(10):
        lines = [["r", "Regular", 90, 2, 1]]
        lines.append(["s", "Supersub", 10, 1 if i % 3 == 0 else 0, 0])
        rows.append(game(10 + i, lines))
    names = [p["name"] for p in (team_shots(rows, TEAM) or {})["players"]]
    assert names == ["Regular"]  # 100 minutes in all: under the floor
    for row in rows:
        row["players"]["home"][1][2] = 25
    names = [p["name"] for p in (team_shots(rows, TEAM) or {})["players"]]
    assert names == ["Regular", "Supersub"]
