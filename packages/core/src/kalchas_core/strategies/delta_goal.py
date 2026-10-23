"""Form Bar (Strategy 3, key ``delta_goal``) -- goals scored vs goals expected by now.

Display name: **Form Bar**. Internal key stays ``delta_goal`` for stability.

How many goals should this team have by now, given recent form on both sides?

1. Expected goals for the match: the average of this team's median goals
   scored and the opponent's median goals conceded, each over their last
   ``FORM_WINDOW`` played games. Medians, so one 6-0 does not drag the number.
2. Expected by now: that, spread evenly over 90 minutes, up to the current
   minute (stoppage and extra time count as minute 90).
3. Reading (``gap``) = expected by now − goals scored. Positive is behind its
   own pace, negative ahead of it (the board shows ``AHEAD_LABEL``).
4. Once the team has scored at least its full-match expectation (and at least
   one goal), it has **delivered**: the board shows ``DELIVERED_LABEL``
   instead of a number, and Form Bar does not alert for it.

Purely form against the scoreline: no live match stats. Pressure is what
Δ5′/Δ10′/UrG/Omega read, and an admin attaches those to Form Bar as extra
conditions rather than this strategy blending them in.

A team with fewer than ``FORM_BAR_MIN_GAMES`` played games in the window has
no reading. If only the opponent is short of games, expected goals fall back
to this team's own median scored (``opponent_used`` is then ``False``).

Replaced, in two steps, a 2.2 port that turned live attacking pressure into a
goal probability and compared it to a league-wide (later team-form) prior;
see git history for that model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from kalchas_core.form import TeamForm
from kalchas_core.match import Side

STRATEGY_KEY = "delta_goal"

FORM_WINDOW: Final = 10
"""Played games per team that the medians are taken over."""

FORM_BAR_MIN_GAMES: Final = 5
"""Below this a median is too jumpy to mean anything; the side reads N/A."""

MATCH_MINUTES: Final = 90

DEFAULT_ALERT_THRESHOLD: Final = 1.0
"""Alert when a team is at least this many goals behind its expected pace."""

DELIVERED_LABEL: Final = "Done"
"""Board word for a team that already has its expected goals. Short: the
board cell is ~5 characters wide. The web board uses the same word."""

AHEAD_LABEL: Final = "Ahead"
"""Board word for a negative gap: more goals than the pace so far, but not
yet the full expectation, so the team can still fall behind later."""


@dataclass(frozen=True, slots=True)
class TeamPace:
    """One team's goals against what its form says it should have by now."""

    scored: int
    expected_goals: float | None
    """Full-match expectation. `None` when this team has too little form."""
    expected_by_now: float = 0.0
    opponent_used: bool = False
    """Whether the opponent's goals conceded went into `expected_goals`."""
    threshold: float = DEFAULT_ALERT_THRESHOLD

    @property
    def has_form(self) -> bool:
        return self.expected_goals is not None

    @property
    def gap(self) -> float | None:
        """Expected by now minus scored. Positive is behind pace; `None` is N/A."""
        if self.expected_goals is None:
            return None
        return round(self.expected_by_now - self.scored, 2)

    @property
    def delivered(self) -> bool:
        """Already scored its full-match expectation (and at least one goal)."""
        return (
            self.expected_goals is not None
            and self.scored > 0
            and self.scored >= self.expected_goals
        )

    @property
    def qualifies(self) -> bool:
        gap = self.gap
        return gap is not None and not self.delivered and gap >= self.threshold

    def note(self, minute: int) -> str:
        """Short human reading for the board, panel and Telegram."""
        if self.expected_goals is None:
            return "Not enough recent games"
        expected = _goals(self.expected_goals)
        if self.delivered:
            return f"{DELIVERED_LABEL} · {self.scored} of {expected} expected"
        clock = min(max(minute, 0), MATCH_MINUTES)
        reading = f"{self.scored} of {expected} expected · {self.expected_by_now:.1f} by {clock}′"
        gap = self.gap
        if gap is not None and gap < 0:
            return f"{reading} · {-gap:.1f} ahead"
        return reading

    def detail(self, minute: int) -> dict[str, Any]:
        """Alert payload fields, for the Telegram text."""
        return {
            "gap": self.gap,
            "scored": self.scored,
            "expected_goals": self.expected_goals,
            "expected_by_now": round(self.expected_by_now, 2),
            "opponent_used": self.opponent_used,
            "note": self.note(minute),
        }


@dataclass(frozen=True, slots=True)
class DeltaGoalResult:
    """Both teams' pace, and which one alerts."""

    home: TeamPace
    away: TeamPace
    minute: int
    threshold: float

    def team(self, side: Side) -> TeamPace:
        return self.home if side is Side.HOME else self.away

    @property
    def triggering_team(self) -> Side | None:
        """The qualifying team furthest behind its pace. Ties go to home."""
        best: Side | None = None
        best_gap = 0.0
        for side in (Side.HOME, Side.AWAY):
            team = self.team(side)
            gap = team.gap
            if not team.qualifies or gap is None:
                continue
            if best is None or gap > best_gap:
                best, best_gap = side, gap
        return best

    @property
    def trigger_value(self) -> float:
        """Goals behind pace for the triggering team (0 if none)."""
        side = self.triggering_team
        gap = self.team(side).gap if side else None
        return gap if gap is not None else 0.0


def _goals(value: float) -> str:
    """1.25 -> "1.25", 1.5 -> "1.5", 2.0 -> "2". Medians move in quarter steps."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _usable(form: TeamForm | None) -> TeamForm | None:
    if form is None or form.games_played < FORM_BAR_MIN_GAMES:
        return None
    return form


def expected_goals(team: TeamForm | None, opponent: TeamForm | None) -> tuple[float | None, bool]:
    """Full-match expected goals for `team` against `opponent`, and whether the
    opponent's form was used. `(None, False)` when `team` has too little form."""
    own = _usable(team)
    if own is None:
        return None, False
    opp = _usable(opponent)
    if opp is None:
        return own.median_scored, False
    return (own.median_scored + opp.median_conceded) / 2.0, True


def _pace(
    scored: int,
    team: TeamForm | None,
    opponent: TeamForm | None,
    minute: int,
    threshold: float,
) -> TeamPace:
    expected, opponent_used = expected_goals(team, opponent)
    if expected is None:
        return TeamPace(scored=scored, expected_goals=None, threshold=threshold)
    share = min(max(minute, 0), MATCH_MINUTES) / MATCH_MINUTES
    return TeamPace(
        scored=scored,
        expected_goals=expected,
        expected_by_now=expected * share,
        opponent_used=opponent_used,
        threshold=threshold,
    )


def evaluate(
    minute: int,
    *,
    home_score: int = 0,
    away_score: int = 0,
    home_recent_form: TeamForm | None = None,
    away_recent_form: TeamForm | None = None,
    threshold: float = DEFAULT_ALERT_THRESHOLD,
) -> DeltaGoalResult:
    """Both teams' pace against their form. Always returns a result; callers
    alert on `triggering_team`, not on getting one."""
    return DeltaGoalResult(
        home=_pace(home_score, home_recent_form, away_recent_form, minute, threshold),
        away=_pace(away_score, away_recent_form, home_recent_form, minute, threshold),
        minute=minute,
        threshold=threshold,
    )
