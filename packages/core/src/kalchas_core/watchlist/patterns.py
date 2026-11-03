"""Pre-match patterns: every check runs on every match, strongest first.

Each pattern compares the two teams' recent games with their own league's
norm and turns the gap into a 0–1 score: 0 is "normal for this league", 1 is
"as strong as it gets". Nothing is hand-picked per match, so a both-teams-to-
score game cannot be passed over for a late-goals story: whichever stands out
more ranks first.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final

from kalchas_core.watchlist.profile import (
    MIN_LEAGUE_GAMES,
    LeagueNorms,
    PlayedGame,
    TeamProfile,
    game_flag,
)

MIN_GAMES: Final = 5
SHRINK_GAMES: Final = 4
"""A team's rate counts as this many games of its league norm, so 5 of 5
does not read as a certainty."""

H2H_MIN: Final = 3
H2H_WEIGHT: Final = 0.25
"""At most a quarter of the estimate comes from head-to-head meetings: they
are few and often seasons old."""

TEAM_WEIGHT: Final = 0.5
"""One team's habit says half as much about a match as both teams' games
agreeing, so single-team patterns are scored at half strength."""

STRONG: Final = 0.55
NOTABLE: Final = 0.39
"""`watch_score` cut-offs for "Strong watch" and "Worth a look". Re-set when
over 3.5, team over 1.5 and the card patterns came in, on the real 3 and
4 Nov 2026 slates (196 priced matches): roughly one in eight reads strong
and three in ten worth a look. Revisit once weeks of results exist."""

TEAM_GOALS_WEIGHT: Final = 0.8
"""A team scoring twice is a one-team market that mostly repeats what the
match's goal patterns say, so it ranks a little below them."""

FOLLOW_ON: Final = 0.9
"""Over 3.5 only comes up as a follow-on to over 2.5 and never outranks it:
it is the same story at a line that lands far less often."""

FAMILY: Final = {
    "over_2_5": "goals",
    "over_3_5": "goals",
    "btts_yes": "goals",
    "team_over_1_5_home": "goals",
    "team_over_1_5_away": "goals",
    "leaky_home": "goals",
    "leaky_away": "goals",
    "under_2_5": "tight",
    "btts_no": "tight",
    "blanks_home": "tight",
    "blanks_away": "tight",
    "cards_over_4_5": "cards",
    "red_card": "cards",
    "penalty_h2h": "penalty",
}
"""Patterns that tell the same story. A second one from the same family adds
nothing to a match's watch score."""

FLAG_ROW: Final = 0.25
"""A pattern this strong highlights its row in the pattern table."""


@dataclass(frozen=True, slots=True)
class Pattern:
    key: str
    tag: str
    """Two or three words for a chip: "Both score"."""
    title: str
    """The headline sentence: "Both teams to score looks likely."."""
    detail: str
    """The evidence, in plain sentences."""
    brief: str
    """One line for the list row."""
    score: float


def _shrunk(count: int, n: int, norm: float) -> float:
    return (count + norm * SHRINK_GAMES) / (n + SHRINK_GAMES)


LIFT_SCALE: Final = 1.25


def _lift(estimate: float, norm: float) -> float:
    """How far above its norm an estimate sits, 0–1.

    Measured in the norm's own spread (``sqrt(p(1-p))``), so 85% against a
    72% norm counts for less than 70% against 52%: the first is a common
    thing happening a bit more often, the second a coin flip leaning hard.
    """
    if not 0 < norm < 1:
        return 0.0
    gap = (estimate - norm) / (norm * (1 - norm)) ** 0.5
    return max(0.0, min(1.0, gap * LIFT_SCALE))


def _poss(name: str) -> str:
    """Possessive: "Hull's", "Spartans'"."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _avg(league: str, norm: float) -> str:
    """ "the League Two average of 58%", or "a typical 52%" without a league."""
    return f"the {league} average of {_pct(norm)}" if league else f"a typical {_pct(norm)}"


def _of(count: int, n: int) -> str:
    return f"all {n}" if count == n and n > 1 else f"{count} of {n}"


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _h2h_count(h2h: Mapping[str, Any] | None, key: str) -> tuple[int, int] | None:
    if not h2h:
        return None
    sample = int(h2h.get("sample") or 0)
    if sample < H2H_MIN:
        return None
    block = h2h.get(key) or {}
    return int(block.get("count") or 0), sample


def _with_h2h(estimate: float, h2h: tuple[int, int] | None, *, invert: bool = False) -> float:
    if h2h is None:
        return estimate
    count, sample = h2h
    rate = count / sample
    if invert:
        rate = 1 - rate
    weight = H2H_WEIGHT * min(sample, 5) / 5
    return estimate * (1 - weight) + rate * weight


def _pair(
    home: TeamProfile,
    away: TeamProfile,
    attr: str,
    norm: float,
    *,
    games: str = "all",
) -> tuple[float, tuple[int, int], tuple[int, int]] | None:
    """Mean shrunk rate of `attr` over both teams' games, with each side's raw
    count. `None` when either side has too few games to say anything."""

    def pool(profile: TeamProfile) -> Sequence[Any]:
        if games == "timed":
            return profile.timed_games
        if games == "ht":
            return profile.ht_games
        if games == "cards":
            return profile.card_games
        return profile.games

    home_games, away_games = pool(home), pool(away)
    if len(home_games) < MIN_GAMES or len(away_games) < MIN_GAMES:
        return None
    hc = sum(1 for g in home_games if game_flag(g, attr))
    ac = sum(1 for g in away_games if game_flag(g, attr))
    estimate = (_shrunk(hc, len(home_games), norm) + _shrunk(ac, len(away_games), norm)) / 2
    return estimate, (hc, len(home_games)), (ac, len(away_games))


def _btts(
    home: TeamProfile, away: TeamProfile, norms: LeagueNorms, league: str, h2h: Any
) -> list[Pattern]:
    norm = norms.rate("btts")
    pair = _pair(home, away, "btts", norm)
    if pair is None:
        return []
    estimate, (hc, hn), (ac, an) = pair
    meetings = _h2h_count(h2h, "btts")
    out: list[Pattern] = []

    yes = _with_h2h(estimate, meetings)
    yes_score = _lift(yes, norm)
    if yes_score > 0:
        detail = (
            f"Both teams scored in {_of(hc, hn)} of {_poss(home.name)} last games and "
            f"{_of(ac, an)} of {_poss(away.name)}, against {_avg(league, norm)}."
        )
        if meetings:
            detail += f" They both scored in {_of(*meetings)} of their last meetings."
        out.append(
            Pattern(
                key="btts_yes",
                tag="Both score: Yes",
                title="Both teams to score looks likely.",
                detail=detail,
                brief=f"Both teams scored in {_of(hc, hn)} and {_of(ac, an)} of their last games.",
                score=yes_score,
            )
        )

    no = _with_h2h(1 - estimate, meetings, invert=True)
    no_score = _lift(no, 1 - norm)
    if no_score > 0:
        home_blank = home.count("failed_to_score") + away.count("clean_sheet")
        away_blank = away.count("failed_to_score") + home.count("clean_sheet")
        quiet = home if home_blank >= away_blank else away
        blanks = quiet.count("failed_to_score")
        detail = (
            f"Both teams scored in {_of(hc, hn)} of {_poss(home.name)} last games and "
            f"{_of(ac, an)} of {_poss(away.name)}, below {_avg(league, norm)}."
        )
        if blanks:
            detail += f" {quiet.name} failed to score in {_of(blanks, quiet.n)}."
        out.append(
            Pattern(
                key="btts_no",
                tag="Both score: No",
                title="Both teams to score looks unlikely.",
                detail=detail,
                brief=f"Both teams scored in just {_of(hc + ac, hn + an)} of their last games.",
                score=no_score,
            )
        )
    return out


def _goals_line(
    home: TeamProfile, away: TeamProfile, norms: LeagueNorms, league: str, h2h: Any
) -> list[Pattern]:
    norm = norms.rate("over_2_5")
    pair = _pair(home, away, "over_2_5", norm)
    if pair is None:
        return []
    estimate, (hc, hn), (ac, an) = pair
    meetings = _h2h_count(h2h, "over_2_5")
    home_avg = home.per_game(home.goals_for + home.goals_against)
    away_avg = away.per_game(away.goals_for + away.goals_against)
    out: list[Pattern] = []

    over = _with_h2h(estimate, meetings)
    over_score = _lift(over, norm)
    if over_score > 0:
        detail = (
            f"{_poss(home.name)} last games averaged {home_avg} goals and {_poss(away.name)} {away_avg}. "
            f"Three or more goals came in {_of(hc, hn)} and {_of(ac, an)}, against "
            f"{_avg(league, norm)}."
        )
        if meetings:
            detail += f" Their last meetings went over in {_of(*meetings)}."
        out.append(
            Pattern(
                key="over_2_5",
                tag="Over 2.5",
                title="Expect goals.",
                detail=detail,
                brief=f"Over 2.5 goals in {_of(hc, hn)} and {_of(ac, an)} of their last games.",
                score=over_score,
            )
        )

    big = _pair(home, away, "over_3_5", norms.rate("over_3_5")) if over_score > 0 else None
    if big is not None:
        big_est, (bc, bn), (ac4, an4) = big
        big_score = min(_lift(big_est, norms.rate("over_3_5")), over_score * FOLLOW_ON)
        if big_score > 0:
            out.append(
                Pattern(
                    key="over_3_5",
                    tag="Over 3.5",
                    title="Four or more goals is a real chance.",
                    detail=(
                        f"Four or more goals came in {_of(bc, bn)} of {_poss(home.name)} last games "
                        f"and {_of(ac4, an4)} of {_poss(away.name)}, against "
                        f"{_avg(league, norms.rate('over_3_5'))}."
                    ),
                    brief=f"Over 3.5 goals in {_of(bc, bn)} and {_of(ac4, an4)} of their last games.",
                    score=big_score,
                )
            )

    under = _with_h2h(1 - estimate, meetings, invert=True)
    under_score = _lift(under, 1 - norm)
    if under_score > 0:
        hu, au = hn - hc, an - ac
        detail = (
            f"Two goals or fewer in {_of(hu, hn)} of {_poss(home.name)} last games and "
            f"{_of(au, an)} of {_poss(away.name)}. They average {home_avg} and {away_avg} "
            f"goals a game."
        )
        out.append(
            Pattern(
                key="under_2_5",
                tag="Under 2.5",
                title="Likely a tight, low-scoring game.",
                detail=detail,
                brief=f"Under 2.5 goals in {_of(hu, hn)} and {_of(au, an)} of their last games.",
                score=under_score,
            )
        )
    return out


def _late(home: TeamProfile, away: TeamProfile, norms: LeagueNorms, league: str) -> list[Pattern]:
    norm = norms.rate("late_goal")
    pair = _pair(home, away, "late_goal", norm, games="timed")
    if pair is None:
        return []
    estimate, (hc, hn), (ac, an) = pair
    score = _lift(estimate, norm)
    if score <= 0:
        return []
    games = home.timed_games + away.timed_games
    late = sum(g.for_by_bucket[-1] + g.against_by_bucket[-1] for g in games)
    total = sum(sum(g.for_by_bucket) + sum(g.against_by_bucket) for g in games)
    detail = (
        f"There was a goal after 75' in {_of(hc, hn)} of {_poss(home.name)} last games and "
        f"{_of(ac, an)} of {_poss(away.name)}, against {_avg(league, norm)}."
    )
    if total:
        detail += f" {_of(late, total)} goals in those games came that late."
    return [
        Pattern(
            key="late_goal",
            tag="Late goals",
            title="Leave it open after 75'.",
            detail=detail,
            brief=f"A goal after 75' in {_of(hc, hn)} and {_of(ac, an)} of their last games.",
            score=score,
        )
    ]


def _early(home: TeamProfile, away: TeamProfile, norms: LeagueNorms, league: str) -> list[Pattern]:
    norm = norms.rate("first_half_goal")
    pair = _pair(home, away, "first_half_goal", norm, games="ht")
    if pair is None:
        return []
    estimate, (hc, hn), (ac, an) = pair
    score = _lift(estimate, norm)
    if score <= 0:
        return []
    return [
        Pattern(
            key="first_half_goal",
            tag="First-half goals",
            title="Goals tend to come before half-time.",
            detail=(
                f"{_of(hc, hn)} of {_poss(home.name)} last games and {_of(ac, an)} of "
                f"{_poss(away.name)} had a first-half goal, against {_avg(league, norm)}."
            ),
            brief=f"A first-half goal in {_of(hc, hn)} and {_of(ac, an)} of their last games.",
            score=score,
        )
    ]


def _runs(home: TeamProfile, away: TeamProfile) -> list[Pattern]:
    out: list[Pattern] = []
    for team, run, where in (
        (home, home.home_scoring_run, "home"),
        (away, away.away_scoring_run, "away"),
    ):
        if run < 7:
            continue
        place = "at home" if where == "home" else "away from home"
        out.append(
            Pattern(
                key=f"{where}_scoring_run",
                tag="Scoring streak",
                title=f"{team.name} keep scoring {place}.",
                detail=f"They've scored in each of their last {run} {where} games.",
                brief=f"{team.name} have scored in their last {run} {where} games.",
                score=TEAM_WEIGHT * min(1.0, 0.5 + 0.05 * (run - 7)),
            )
        )
    return out


def _defence_and_attack(home: TeamProfile, away: TeamProfile, norms: LeagueNorms) -> list[Pattern]:
    out: list[Pattern] = []
    cs_norm = norms.rate("clean_sheet")
    fts_norm = norms.rate("failed_to_score")
    for team in (home, away):
        if team.n < MIN_GAMES + 3:
            continue
        clean = team.count("clean_sheet")
        cs_score = _lift(1 - _shrunk(clean, team.n, cs_norm), 1 - cs_norm)
        if clean <= 1 and cs_score > 0:
            sheets = "No clean sheets" if clean == 0 else "One clean sheet"
            out.append(
                Pattern(
                    key=f"leaky_{'home' if team is home else 'away'}",
                    tag="No clean sheet",
                    title=f"{team.name} rarely keep a clean sheet.",
                    detail=(
                        f"{sheets} in their last {team.n}, conceding "
                        f"{team.per_game(team.goals_against)} a game."
                    ),
                    brief=f"{team.name}: {sheets} in their last {team.n}.",
                    score=TEAM_WEIGHT * cs_score,
                )
            )
        blanks = team.count("failed_to_score")
        fts_score = _lift(_shrunk(blanks, team.n, fts_norm), fts_norm)
        if blanks * 2 >= team.n and fts_score > 0:
            out.append(
                Pattern(
                    key=f"blanks_{'home' if team is home else 'away'}",
                    tag="Struggles to score",
                    title=f"{team.name} struggle to score.",
                    detail=(
                        f"They failed to score in {_of(blanks, team.n)} of their last games, "
                        f"scoring {team.per_game(team.goals_for)} a game."
                    ),
                    brief=f"{team.name} failed to score in {_of(blanks, team.n)}.",
                    score=TEAM_WEIGHT * fts_score,
                )
            )
    return out


def _favourite(
    home: TeamProfile, away: TeamProfile, odds: Mapping[str, Any] | None
) -> list[Pattern]:
    if not odds:
        return []
    out: list[Pattern] = []
    for team, key in ((home, "home"), (away, "away")):
        try:
            price = float(odds.get(key) or 0)
        except (TypeError, ValueError):
            continue
        wins = team.count("win")
        if not (1 < price <= 1.6) or team.n < MIN_GAMES or wins * 10 < team.n * 6:
            continue
        out.append(
            Pattern(
                key=f"favourite_{key}",
                tag="Strong favourite",
                title=f"{team.name} are clear favourites, and in form.",
                detail=f"Priced {price:.2f} with {_of(wins, team.n)} wins in their last games.",
                brief=f"{team.name} at {price:.2f}, {_of(wins, team.n)} wins lately.",
                score=TEAM_WEIGHT * min(1.0, 0.5 + (wins / team.n - 0.6)),
            )
        )
    return out


def _team_goals(
    home: TeamProfile, away: TeamProfile, norms: LeagueNorms, league: str
) -> list[Pattern]:
    """A team scoring twice or more: its own 2+ games and the opponent's
    games conceding 2+, against the league's rate for one team."""
    norm = norms.rate("scored_2plus")
    out: list[Pattern] = []
    for team, other, side in ((home, away, "home"), (away, home, "away")):
        if team.n < MIN_GAMES or other.n < MIN_GAMES:
            continue
        scored = team.count("scored_2plus")
        leaked = other.count("conceded_2plus")
        estimate = (_shrunk(scored, team.n, norm) + _shrunk(leaked, other.n, norm)) / 2
        score = TEAM_GOALS_WEIGHT * _lift(estimate, norm)
        if score <= 0:
            continue
        out.append(
            Pattern(
                key=f"team_over_1_5_{side}",
                tag=f"{side.title()} over 1.5",
                title=f"{team.name} to score twice or more.",
                detail=(
                    f"{team.name} scored 2 or more in {_of(scored, team.n)} of their last games and "
                    f"{other.name} conceded 2 or more in {_of(leaked, other.n)}, against "
                    f"{_avg(league, norm)} for one team."
                ),
                brief=f"{team.name} scored 2+ in {_of(scored, team.n)}; {other.name} let in 2+ in {_of(leaked, other.n)}.",
                score=score,
            )
        )
    return out


def _cards(home: TeamProfile, away: TeamProfile, norms: LeagueNorms, league: str) -> list[Pattern]:
    """Bookings and red cards, from the games the provider has card data for.
    Quiet where the league has too little card data to know its norm."""
    if norms.games and norms.card_games < MIN_LEAGUE_GAMES:
        return []
    out: list[Pattern] = []
    many = _pair(home, away, "cards_5plus", norms.rate("cards_5plus"), games="cards")
    if many is not None:
        estimate, (hc, hn), (ac, an) = many
        score = _lift(estimate, norms.rate("cards_5plus"))
        if score > 0:
            per_game = [
                round(sum(g.cards or 0 for g in t.card_games) / len(t.card_games), 1)
                for t in (home, away)
            ]
            out.append(
                Pattern(
                    key="cards_over_4_5",
                    tag="Over 4.5 cards",
                    title="Expect plenty of cards.",
                    detail=(
                        f"Five or more cards were shown in {_of(hc, hn)} of {_poss(home.name)} last games "
                        f"and {_of(ac, an)} of {_poss(away.name)}, against {_avg(league, norms.rate('cards_5plus'))}. "
                        f"They average {per_game[0]} and {per_game[1]} cards a game."
                    ),
                    brief=f"5+ cards in {_of(hc, hn)} and {_of(ac, an)} of their last games.",
                    score=score,
                )
            )
    red = _pair(home, away, "red_card", norms.rate("red_card"), games="cards")
    if red is not None:
        estimate, (hc, hn), (ac, an) = red
        score = _lift(estimate, norms.rate("red_card"))
        if score > 0:
            out.append(
                Pattern(
                    key="red_card",
                    tag="Red card risk",
                    title="A red card is a real chance.",
                    detail=(
                        f"There was a red card in {_of(hc, hn)} of {_poss(home.name)} last games and "
                        f"{_of(ac, an)} of {_poss(away.name)}, against {_avg(league, norms.rate('red_card'))}."
                    ),
                    brief=f"A red card in {_of(hc, hn)} and {_of(ac, an)} of their last games.",
                    score=score,
                )
            )
    return out


MEETINGS_MIN: Final = 5
"""Meetings with the detail known before their penalties or corners say anything."""

PENALTY_SHARE: Final = 0.4
PENALTY_MIN: Final = 3
"""A penalty scored in at least this share (and count) of the meetings: a
fixture with history, "4 of their last 10"."""

CORNER_SHARE: Final = 0.6
CORNER_LINES: Final = (13.5, 12.5, 11.5, 10.5, 9.5)
CORNER_NORM: Final = 0.35
"""Share of games over a high corner line, where the league's own is unknown."""

MEETINGS_WEIGHT: Final = 0.6
"""These come from a handful of meetings, often seasons apart, so they back up
a match rather than make it."""


def corner_key(line: float) -> str:
    return "corners_over_" + str(line).replace(".", "_")


def _fixture_history(
    home: TeamProfile, away: TeamProfile, meetings: Sequence[PlayedGame], norms: LeagueNorms
) -> list[Pattern]:
    """Penalties and corners in the two teams' past meetings. Only said when
    the meetings show a clear habit; otherwise silent."""
    out: list[Pattern] = []
    pens = [g for g in meetings if g.penalty_goal is not None]
    hits = sum(1 for g in pens if g.penalty_goal)
    if len(pens) >= MEETINGS_MIN and hits >= max(PENALTY_MIN, PENALTY_SHARE * len(pens)):
        norm = norms.rate("penalty_goal")
        score = MEETINGS_WEIGHT * _lift(_shrunk(hits, len(pens), norm), norm)
        if score > 0:
            out.append(
                Pattern(
                    key="penalty_h2h",
                    tag="Penalty history",
                    title="Penalties keep coming when these two meet.",
                    detail=(
                        f"A penalty was scored in {_of(hits, len(pens))} of their last meetings, "
                        f"against {_pct(norm)} of games in general."
                    ),
                    brief=f"A penalty scored in {_of(hits, len(pens))} of their last meetings.",
                    score=score,
                )
            )

    corners = [g.corners for g in meetings if g.corners is not None]
    if len(corners) >= MEETINGS_MIN:
        ordered = sorted(corners)
        median = ordered[len(ordered) // 2]
        for line in CORNER_LINES:
            over = sum(1 for c in corners if c > line)
            if over < CORNER_SHARE * len(corners):
                continue
            league = norms.corners_over(line)
            norm = max(0.05, league) if league is not None else CORNER_NORM
            if league is None and line < 10.5:
                break  # an ordinary line, and nothing to say it's unusual here
            score = MEETINGS_WEIGHT * _lift(_shrunk(over, len(corners), norm), norm)
            if score > 0:
                out.append(
                    Pattern(
                        key=corner_key(line),
                        tag=f"Over {line} corners",
                        title="Corners pile up when these two meet.",
                        detail=(
                            f"Over {line} corners in {_of(over, len(corners))} of their last meetings "
                            f"(a typical meeting had {median}), against "
                            + (
                                f"{_pct(league)} of games in this league."
                                if league is not None
                                else "few games in general."
                            )
                        ),
                        brief=f"Over {line} corners in {_of(over, len(corners))} of their last meetings.",
                        score=score,
                    )
                )
            break
    return out


MEETING_ALONE_MAX: Final = 0.3
"""Meeting patterns with nothing else behind them stay under "worth a look"."""


def _is_meeting(key: str) -> bool:
    return key == "penalty_h2h" or key.startswith("corners_over_")


def _behind_the_match(found: Sequence[Pattern]) -> list[Pattern]:
    """Penalty and corner history back a match up; they never lead it. Each
    is held just under the match's best other pattern, or under
    `MEETING_ALONE_MAX` when there is none."""
    best = max((p.score for p in found if not _is_meeting(p.key)), default=0.0)
    cap = best * FOLLOW_ON if best else MEETING_ALONE_MAX
    return [replace(p, score=min(p.score, cap)) if _is_meeting(p.key) else p for p in found]


def match_patterns(
    home: TeamProfile,
    away: TeamProfile,
    norms: LeagueNorms,
    *,
    league: str,
    h2h: Mapping[str, Any] | None = None,
    odds: Mapping[str, Any] | None = None,
    meetings: Sequence[PlayedGame] = (),
) -> list[Pattern]:
    """All patterns that sit above their league norm, strongest first.

    `league` is the competition's short name, or "" when the norms are the
    general ones (cup ties, competitions with too few games).
    """
    found = [
        *_btts(home, away, norms, league, h2h),
        *_goals_line(home, away, norms, league, h2h),
        *_late(home, away, norms, league),
        *_early(home, away, norms, league),
        *_team_goals(home, away, norms, league),
        *_cards(home, away, norms, league),
        *_runs(home, away),
        *_defence_and_attack(home, away, norms),
        *_favourite(home, away, odds),
        *_fixture_history(home, away, meetings, norms),
    ]
    found = _behind_the_match(found)
    found = [p for p in found if p.score >= 0.05]
    found.sort(key=lambda p: p.score, reverse=True)
    return found


def _family(key: str) -> str:
    return FAMILY.get(key, key)


def watch_score(patterns: Sequence[Pattern]) -> float:
    """One number to rank a day's matches: the best pattern, plus a little
    for the best one that says something different (over 2.5 and over 3.5
    are one story, not two)."""
    if not patterns:
        return 0.0
    top = patterns[0]
    second = next((p.score for p in patterns[1:] if _family(p.key) != _family(top.key)), 0.0)
    return round(min(1.0, top.score + 0.3 * second), 3)


def watch_level(patterns: Sequence[Pattern]) -> str:
    """``strong`` | ``look`` | ``quiet``, from the same score the list sorts by."""
    score = watch_score(patterns)
    if score >= STRONG:
        return "strong"
    if score >= NOTABLE:
        return "look"
    return "quiet"


PATTERN_ROWS: Final = (
    ("btts", "Both teams scored"),
    ("over_2_5", "Over 2.5 goals"),
    ("over_3_5", "Over 3.5 goals"),
    ("scored_2plus", "Scored 2 or more"),
    ("first_half_goal", "Goal before half-time"),
    ("late_goal", "Goal after 75'"),
    ("clean_sheet", "Kept a clean sheet"),
    ("failed_to_score", "Failed to score"),
    ("cards_5plus", "5 or more cards"),
    ("red_card", "A red card"),
)
CARD_ROWS: Final = frozenset({"cards_5plus", "red_card"})

_ROW_HIGHLIGHT = {
    "btts": {"btts_yes", "btts_no"},
    "over_2_5": {"over_2_5", "under_2_5"},
    "over_3_5": {"over_3_5"},
    "scored_2plus": {"team_over_1_5_home", "team_over_1_5_away"},
    "first_half_goal": {"first_half_goal"},
    "late_goal": {"late_goal"},
    "clean_sheet": {"leaky_home", "leaky_away"},
    "failed_to_score": {"blanks_home", "blanks_away"},
    "cards_5plus": {"cards_over_4_5"},
    "red_card": {"red_card"},
}


def pattern_table(
    home: TeamProfile,
    away: TeamProfile,
    norms: LeagueNorms,
    *,
    h2h: Mapping[str, Any] | None,
    patterns: Sequence[Pattern],
) -> list[dict[str, Any]]:
    """Every pattern's raw numbers side by side, so a reader can check the
    ones Kalchas did not lead with. Rows a top pattern came from are flagged."""
    flagged = {p.key for p in patterns if p.score >= FLAG_ROW}
    rows: list[dict[str, Any]] = []
    for key, label in PATTERN_ROWS:
        if key in CARD_ROWS and not (home.card_games and away.card_games):
            continue  # no card data for these teams: leave the rows out
        pool = (
            "timed"
            if key == "late_goal"
            else "ht"
            if key == "first_half_goal"
            else "cards"
            if key in CARD_ROWS
            else "all"
        )

        def side(profile: TeamProfile, key: str = key, pool: str = pool) -> dict[str, int]:
            games = (
                profile.timed_games
                if pool == "timed"
                else profile.ht_games
                if pool == "ht"
                else profile.card_games
                if pool == "cards"
                else profile.games
            )
            return {"count": sum(1 for g in games if game_flag(g, key)), "n": len(games)}

        meetings = _h2h_count(h2h, key) if key in {"btts", "over_2_5"} else None
        rows.append(
            {
                "key": key,
                "label": label,
                "home": side(home),
                "away": side(away),
                "league_pct": norms.pct(key),
                "h2h": {"count": meetings[0], "n": meetings[1]} if meetings else None,
                "flagged": bool(_ROW_HIGHLIGHT[key] & flagged),
            }
        )
    return rows
