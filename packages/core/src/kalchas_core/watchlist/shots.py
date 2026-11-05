"""Player shots for a match page: each team's regular shooters, their shots
game by game and how often they reached each line (1+, 2+, 3+ shots, 1+ on
target).

Reads the ``players`` block `kalchas_football.client.player_shot_lines` adds
to a fixture row. Only games the provider covered count: in the others no
player has minutes, and a "0" there would be a missing number, not a game
without a shot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from kalchas_core.watchlist.profile import is_played

SHOT_WINDOW: Final = 40
"""Covered games looked at per team, newest first."""
MIN_GAMES: Final = 5
"""Fewer covered games than this and a team gets no shots section."""
MIN_APPS: Final = 5
"""A player needs this many appearances in those games to be listed."""
RECENT: Final = 3
"""...and to have played in at least one of the team's last this-many, so a
player who left or is long injured drops out."""
MIN_MINUTES: Final = 180
PLAYERS_SHOWN: Final = 4
LINES: Final = (("shots", 1), ("shots", 2), ("shots", 3), ("on_target", 1))


def covered_games(rows: Sequence[Mapping[str, Any]], team_id: int) -> list[list[list[Any]]]:
    """The team's own player lines in each covered, played game, newest first."""
    seen: set[str] = set()
    out: list[list[list[Any]]] = []
    for row in sorted(rows, key=lambda r: str(r.get("match_date") or ""), reverse=True):
        players = row.get("players")
        if not isinstance(players, Mapping) or not is_played(dict(row)):
            continue
        if int(row.get("home_team_id") or 0) == team_id:
            side = "home"
        elif int(row.get("away_team_id") or 0) == team_id:
            side = "away"
        else:
            continue
        match_id = str(row.get("match_id") or "")
        if match_id and match_id in seen:
            continue
        seen.add(match_id)
        lines = players.get(side) or []
        if lines:
            out.append(list(lines))
        if len(out) >= SHOT_WINDOW:
            break
    return out


def team_shots(
    rows: Sequence[Mapping[str, Any]], team_id: int, *, source: str = "competition"
) -> dict[str, Any] | None:
    """The team's shots section, or `None` without enough covered games."""
    games = covered_games(rows, int(team_id))
    if len(games) < MIN_GAMES:
        return None
    by_player: dict[str, dict[str, Any]] = {}
    for index, lines in enumerate(games):
        for key, name, minutes, shots, on_target in lines:
            player = by_player.setdefault(
                str(key), {"name": str(name), "first": index, "games": []}
            )
            player["games"].append((int(minutes), int(shots), int(on_target)))
    players: list[dict[str, Any]] = []
    for p in by_player.values():
        apps = p["games"]
        minutes = sum(g[0] for g in apps)
        if len(apps) < MIN_APPS or p["first"] >= RECENT or minutes < MIN_MINUTES:
            continue
        shots = [g[1] for g in apps]
        on_target = [g[2] for g in apps]
        players.append(
            {
                "name": p["name"],
                "apps": len(apps),
                "minutes": minutes,
                "shots": shots,
                "per_90": round(sum(shots) * 90 / minutes, 1),
                "on_target_per_90": round(sum(on_target) * 90 / minutes, 1),
                "lines": [
                    {
                        "stat": stat,
                        "at_least": at_least,
                        "hits": sum(
                            1 for s in (shots if stat == "shots" else on_target) if s >= at_least
                        ),
                    }
                    for stat, at_least in LINES
                ],
            }
        )
    # Shots per appearance, not per 90: the bets pay per game played, and per
    # 90 puts a super-sub with a few shots in a few minutes on top.
    players.sort(key=lambda p: (-sum(p["shots"]) / p["apps"], -p["apps"], p["name"]))
    if not players:
        return None
    return {"games": len(games), "source": source, "players": players[:PLAYERS_SHOWN]}


def has_covered_games(rows: Sequence[Mapping[str, Any]]) -> bool:
    """Whether the provider has player data for this competition at all."""
    return any(isinstance(row.get("players"), Mapping) for row in rows)
