"""Pre-match team profiles and league norms for the watchlist (pure core).

Input is canonical fixture rows (``kalchas_football.parse_team_fixtures``):
scores, half-time scores and, when the provider timed them, ``goal_events``.
The provider times every goal of a match or none, so a scoring match with no
events is "untimed" and stays out of the timing counts rather than reading as
goalless.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from kalchas_core.form.metrics import PLAYED_STATUS_CODES

PROFILE_WINDOW: Final = 10
"""Games per team. Long enough for "8 of 10" to mean something, short enough
to still be this season's team."""

TIMING_LABELS: Final = ("0–15'", "16–30'", "31–45'", "46–60'", "61–75'", "76–90'")
LATE_FROM: Final = 76

MIN_LEAGUE_GAMES: Final = 40
"""Below this a competition (a cup round, a new season) has no norm of its own."""

LEAGUE_PRIOR_GAMES: Final = 20
"""A league's own rate counts as this many games of the global default, so a
cup round with eight games played reads close to football in general."""

DEFAULT_NORMS: Final = {
    "btts": 0.52,
    "over_2_5": 0.50,
    "first_half_goal": 0.72,
    "late_goal": 0.52,
    "clean_sheet": 0.28,
    "failed_to_score": 0.28,
    "over_3_5": 0.30,
    "scored_2plus": 0.38,
    "cards_5plus": 0.39,
    "red_card": 0.28,
}
"""Rates across a typical slate of league football, used where a league has
too few games of its own. Clean sheets and blanks are per team per game, and
league-wide they are the same number: every clean sheet is the other side's
blank. Card rates are over games the provider has card data for (about
four in ten, from a 5,300-match sample in Oct 2026)."""


@dataclass(frozen=True, slots=True)
class PlayedGame:
    """One played fixture seen from a single team's side."""

    match_id: str
    match_date: str
    opponent: str
    venue: str  # "H" | "A"
    goals_for: int
    goals_against: int
    first_half_goal: bool | None
    """Any goal before half-time; `None` when neither HT score nor goal times exist."""
    timed: bool
    for_by_bucket: tuple[int, ...]
    against_by_bucket: tuple[int, ...]
    cards: int | None = None
    """Cards in the 90 minutes; `None` when the provider has no card data."""
    red_card: bool | None = None

    @property
    def result(self) -> str:
        if self.goals_for > self.goals_against:
            return "W"
        if self.goals_for < self.goals_against:
            return "L"
        return "D"

    @property
    def total(self) -> int:
        return self.goals_for + self.goals_against

    @property
    def late_goal(self) -> bool:
        return bool(self.for_by_bucket[-1] or self.against_by_bucket[-1])


@dataclass(frozen=True, slots=True)
class TeamProfile:
    team_id: int
    name: str
    games: tuple[PlayedGame, ...]
    """Newest first, at most `PROFILE_WINDOW`."""
    home_scoring_run: int = 0
    """Consecutive home games with a goal, newest first, over all history held."""
    away_scoring_run: int = 0

    @property
    def n(self) -> int:
        return len(self.games)

    def count(self, attr: str) -> int:
        return sum(1 for game in self.games if game_flag(game, attr))

    @property
    def timed_games(self) -> tuple[PlayedGame, ...]:
        return tuple(game for game in self.games if game.timed)

    @property
    def card_games(self) -> tuple[PlayedGame, ...]:
        return tuple(game for game in self.games if game.cards is not None)

    @property
    def ht_games(self) -> tuple[PlayedGame, ...]:
        return tuple(game for game in self.games if game.first_half_goal is not None)

    @property
    def goals_for(self) -> int:
        return sum(game.goals_for for game in self.games)

    @property
    def goals_against(self) -> int:
        return sum(game.goals_against for game in self.games)

    def per_game(self, total: int) -> float:
        return round(total / self.n, 1) if self.n else 0.0


def game_flag(game: PlayedGame, attr: str) -> bool:
    if attr == "btts":
        return game.goals_for > 0 and game.goals_against > 0
    if attr == "over_2_5":
        return game.total >= 3
    if attr == "scored":
        return game.goals_for > 0
    if attr == "conceded":
        return game.goals_against > 0
    if attr == "clean_sheet":
        return game.goals_against == 0
    if attr == "failed_to_score":
        return game.goals_for == 0
    if attr == "win":
        return game.result == "W"
    if attr == "draw":
        return game.result == "D"
    if attr == "loss":
        return game.result == "L"
    if attr == "first_half_goal":
        return bool(game.first_half_goal)
    if attr == "over_3_5":
        return game.total >= 4
    if attr == "scored_2plus":
        return game.goals_for >= 2
    if attr == "conceded_2plus":
        return game.goals_against >= 2
    if attr == "cards_5plus":
        return game.cards is not None and game.cards >= 5
    if attr == "red_card":
        return bool(game.red_card)
    if attr == "late_goal":
        return game.timed and game.late_goal
    raise KeyError(attr)


def is_played(row: dict[str, Any]) -> bool:
    return (
        str(row.get("status_short") or "") in PLAYED_STATUS_CODES
        and row.get("home_score") is not None
        and row.get("away_score") is not None
    )


def timing_bucket(event: dict[str, Any]) -> int | None:
    """Index into `TIMING_LABELS`. First-half stoppage stays in 31–45' and
    second-half stoppage in 76–90'; extra time is left out."""
    try:
        minute = int(event.get("minute") or 0)
    except (TypeError, ValueError):
        return None
    if minute <= 0:
        return None
    half = str(event.get("half") or "")
    if half not in {"1H", "2H"}:
        if half:
            return None
        half = "1H" if minute <= 45 else "2H"
    if half == "1H":
        return 0 if minute <= 15 else 1 if minute <= 30 else 2
    if minute > 120:
        return None
    return 3 if minute <= 60 else 4 if minute <= 75 else 5


def played_game(row: dict[str, Any], team_id: int) -> PlayedGame | None:
    home_id = int(row.get("home_team_id") or 0)
    away_id = int(row.get("away_team_id") or 0)
    if team_id not in (home_id, away_id) or not is_played(row):
        return None
    side = "home" if team_id == home_id else "away"
    home_score, away_score = int(row["home_score"]), int(row["away_score"])
    goals_for, goals_against = (
        (home_score, away_score) if side == "home" else (away_score, home_score)
    )

    events = [ev for ev in row.get("goal_events") or [] if isinstance(ev, dict)]
    for_buckets = [0] * len(TIMING_LABELS)
    against_buckets = [0] * len(TIMING_LABELS)
    timed = len(events) == home_score + away_score
    if timed:
        for ev in events:
            idx = timing_bucket(ev)
            if idx is None:
                continue
            scorer = str(ev.get("side") or ev.get("team") or "")
            if scorer == side:
                for_buckets[idx] += 1
            elif scorer in {"home", "away"}:
                against_buckets[idx] += 1

    ht_home, ht_away = row.get("home_ht_score"), row.get("away_ht_score")
    first_half: bool | None
    if ht_home is not None and ht_away is not None:
        first_half = int(ht_home) + int(ht_away) > 0
    elif timed:
        first_half = sum(for_buckets[:3]) + sum(against_buckets[:3]) > 0
    else:
        first_half = None

    opponent = str((row.get("away_team") if side == "home" else row.get("home_team")) or "")
    return PlayedGame(
        match_id=str(row.get("match_id") or ""),
        match_date=str(row.get("match_date") or ""),
        opponent=opponent,
        venue="H" if side == "home" else "A",
        goals_for=goals_for,
        goals_against=goals_against,
        first_half_goal=first_half,
        timed=timed,
        for_by_bucket=tuple(for_buckets),
        against_by_bucket=tuple(against_buckets),
        cards=None if row.get("cards") is None else int(row["cards"]),
        red_card=None if row.get("cards") is None else bool(row.get("red_card")),
    )


def team_games(rows: Sequence[dict[str, Any]], team_id: int) -> list[PlayedGame]:
    """Every played game of `team_id` in `rows`, newest first, one per match."""
    seen: set[str] = set()
    games: list[PlayedGame] = []
    for row in sorted(rows, key=lambda r: str(r.get("match_date") or ""), reverse=True):
        game = played_game(row, team_id)
        if game is None or (game.match_id and game.match_id in seen):
            continue
        seen.add(game.match_id)
        games.append(game)
    return games


def _scoring_run(games: Sequence[PlayedGame], venue: str) -> int:
    run = 0
    for game in games:
        if game.venue != venue:
            continue
        if game.goals_for == 0:
            break
        run += 1
    return run


def build_team_profile(
    rows: Sequence[dict[str, Any]],
    team_id: int,
    *,
    name: str = "",
    window: int = PROFILE_WINDOW,
) -> TeamProfile:
    games = team_games(rows, int(team_id))
    return TeamProfile(
        team_id=int(team_id),
        name=name,
        games=tuple(games[:window]),
        home_scoring_run=_scoring_run(games, "H"),
        away_scoring_run=_scoring_run(games, "A"),
    )


@dataclass(frozen=True, slots=True)
class LeagueNorms:
    """How often each pattern happens across a whole league's played games,
    pulled towards `DEFAULT_NORMS` while the league has few games."""

    games: int
    rates: dict[str, float]
    card_games: int = 0
    """League games with card data. Too few and card patterns stay quiet."""

    def rate(self, key: str) -> float:
        return self.rates.get(key, DEFAULT_NORMS[key])

    def pct(self, key: str) -> int:
        return round(self.rate(key) * 100)


def _blend(count: int, n: int, prior: float, weight: int = LEAGUE_PRIOR_GAMES) -> float:
    return (count + prior * weight) / (n + weight)


def default_norms() -> LeagueNorms:
    return LeagueNorms(games=0, rates=dict(DEFAULT_NORMS))


def league_norms(rows: Sequence[dict[str, Any]]) -> LeagueNorms:
    played = [row for row in rows if is_played(row)]
    seen: set[str] = set()
    games: list[PlayedGame] = []
    for row in played:
        match_id = str(row.get("match_id") or "")
        if match_id and match_id in seen:
            continue
        seen.add(match_id)
        game = played_game(row, int(row.get("home_team_id") or 0))
        if game is not None:
            games.append(game)

    n = len(games)
    carded = [g for g in games if g.cards is not None]
    timed = [g for g in games if g.timed]
    halves = [g for g in games if g.first_half_goal is not None]
    sides = 2 * n
    counts = {
        "btts": (sum(1 for g in games if g.goals_for and g.goals_against), n),
        "over_2_5": (sum(1 for g in games if g.total >= 3), n),
        "first_half_goal": (sum(1 for g in halves if g.first_half_goal), len(halves)),
        "late_goal": (sum(1 for g in timed if g.late_goal), len(timed)),
        "clean_sheet": (
            sum((g.goals_against == 0) + (g.goals_for == 0) for g in games),
            sides,
        ),
        "failed_to_score": (
            sum((g.goals_for == 0) + (g.goals_against == 0) for g in games),
            sides,
        ),
        "over_3_5": (sum(1 for g in games if g.total >= 4), n),
        "scored_2plus": (sum((g.goals_for >= 2) + (g.goals_against >= 2) for g in games), sides),
        "cards_5plus": (sum(1 for g in carded if (g.cards or 0) >= 5), len(carded)),
        "red_card": (sum(1 for g in carded if g.red_card), len(carded)),
    }
    if n < MIN_LEAGUE_GAMES:
        return LeagueNorms(games=n, rates=dict(DEFAULT_NORMS), card_games=len(carded))
    rates = {key: _blend(c, total, DEFAULT_NORMS[key]) for key, (c, total) in counts.items()}
    return LeagueNorms(games=n, rates=rates, card_games=len(carded))
