"""K-Index (Strategy 7) -- the chance, in %, that a team scores soon.

    base       = the team's goal rate from the kickoff 1X2 prices
                 x share of a match's goals due in the next `horizon` minutes,
                   stopping at the end of the current half
                 x score tilt (teams behind score a little more)
    live boost = first-half multiplier (first half only)
                 x (1 + unrealised_boost x unrealised goals)
                 x (1 + shots in the last 10 minutes) ^ recent_shots_power
                 capped at max_live_boost
    K          = 100 x (1 - exp(-base_multiplier x base x live boost))

K reads as a plain chance: K 40 means about four in ten such moments saw the
team score inside the window. That is the same bet a K alert is settled on
(team-specific, 20-minute window, ends at half time).

Why this recipe (rebuilt 2026-11-22). The old K-Score blended the outputs of
Delta 5min, Pressure Index and Rule of 3 through a logit with ten hand-set
weights and an NPEI multiplier. On every minute of 686 finished matches in
`match_history` (104k team-minutes) its median reading was 3 and its highest
34: it never reached its threshold of 40, and three of its context weights
were never fed. Measured against those matches:

- Kickoff prices, the clock and the score do most of the work. With the window
  stopped at half time, as alerts are settled, the base on its own was close
  to calibrated (slope 0.97 on the log scale; the fitted level is 0.92).
- On top of that, unrealised goals and shots in the last ten minutes add a
  little (out-of-sample log-loss better on both halves of the matches), as
  does a first-half bump (goals in a first-half window come about 28% more
  often than the quarter-hour shares say). Delta 5min, Pressure Index, NPEI,
  corners, dangerous attacks and possession added nothing and are not used.
- Teams behind as underdogs, and readings after 60', looked weak against the
  old baseline; once the base is right neither needs its own term.

Calibration on those matches: K 30-40 scored 33% of the time, 40-50 42%,
50-60 66% (small). K 40+ is lit on about 3% of team-minutes. Readings are
live-price-blind: a high K is usually a favourite with time left, which the
live market also sees.

Without kickoff prices the base uses an average match (DEFAULT_RATES), so K
is less informed there; `priced` on the result says which.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from kalchas_core import chance
from kalchas_core.match import MatchTimeline, Side, WindowClamp, resolve_window
from kalchas_core.weights import WeightSet

STRATEGY_KEY = "kscore"

DEFAULT_THRESHOLD: Final = 40.0

RECENT_SHOTS_WINDOW: Final = 10
"""Minutes of play the recent-shots term looks back over."""

UNREALISED_CAP: Final = 4.0
"""Unrealised goals beyond this add nothing more; negative readings count as 0."""

DEFAULT_RATES: Final = (1.45, 1.15)
"""Full-match goal rates (home, away) for a match without kickoff prices:
`chance.DEFAULT_TOTAL_GOALS` split with an ordinary home advantage."""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class TeamKScore:
    """One team's K-Index and what went into it."""

    score: int
    """0-100: the chance, in %, that this team scores inside the window."""
    probability: float
    baseline: float
    """Chance from kickoff prices, clock and score alone (with the level)."""
    live_boost: float
    unrealised_goals: float
    recent_shots: int

    @property
    def value(self) -> int:
        return self.score


@dataclass(frozen=True, slots=True)
class KScoreResult:
    """Both teams' K-Index and the chance that either scores."""

    home: TeamKScore
    away: TeamKScore
    match_score: int
    """0-100: the chance that at least one team scores inside the window."""
    threshold: float
    horizon_minutes: float
    priced: bool
    """False when no kickoff prices were available and an average match was assumed."""

    def team(self, side: Side) -> TeamKScore:
        return self.home if side is Side.HOME else self.away

    @property
    def triggering_team(self) -> Side | None:
        """The team at or above the threshold with the higher score; ties go home."""
        home_ok = self.home.score >= self.threshold
        away_ok = self.away.score >= self.threshold
        if not home_ok and not away_ok:
            return None
        if home_ok and (not away_ok or self.home.score >= self.away.score):
            return Side.HOME
        return Side.AWAY

    @property
    def trigger_value(self) -> float:
        side = self.triggering_team
        return float(self.team(side).score) if side else 0.0


def recent_shots(timeline: MatchTimeline, side: Side) -> int:
    """Shots (on and off target) in the last ten minutes of play.

    Clamped to the start of the current period as Pressure Index is, with the
    same fallback to the nearest earlier minute when polling left a gap.
    """
    window = resolve_window(
        timeline,
        RECENT_SHOTS_WINDOW,
        clamp=WindowClamp.PERIOD_START,
        fallback_lookback=RECENT_SHOTS_WINDOW,
        require_full_span=False,
    )
    return int(window.deltas(side).shots) if window is not None else 0


def live_boost(
    *,
    unrealised_goals: float,
    shots_last_10: int,
    first_half: bool,
    weights: WeightSet,
) -> float:
    """Multiplier the live stats put on the base scoring rate."""
    unrealised = _clamp(float(unrealised_goals), 0.0, UNREALISED_CAP)
    boost = 1.0 + weights.get(STRATEGY_KEY, "unrealised_boost") * unrealised
    boost *= (1.0 + max(0, int(shots_last_10))) ** weights.get(STRATEGY_KEY, "recent_shots_power")
    if first_half:
        boost *= weights.get(STRATEGY_KEY, "first_half_multiplier")
    return _clamp(boost, 0.0, max(1.0, weights.get(STRATEGY_KEY, "max_live_boost")))


def evaluate_team(
    side: Side,
    *,
    minute: int,
    own_goals: int,
    opponent_goals: int,
    full_match_rate: float,
    first_half: bool,
    unrealised_goals: float,
    shots_last_10: int,
    weights: WeightSet,
) -> TeamKScore:
    """K-Index for one team."""
    horizon = weights.get(STRATEGY_KEY, "horizon_minutes")
    level = weights.get(STRATEGY_KEY, "base_multiplier")
    base = (
        full_match_rate
        * chance.window_goal_share(minute, horizon, first_half=first_half)
        * chance.score_tilt(int(own_goals) - int(opponent_goals))
        * level
    )
    boost = live_boost(
        unrealised_goals=unrealised_goals,
        shots_last_10=shots_last_10,
        first_half=first_half,
        weights=weights,
    )
    probability = 1.0 - math.exp(-base * boost)
    return TeamKScore(
        score=max(0, min(100, round(100.0 * probability))),
        probability=probability,
        baseline=1.0 - math.exp(-base),
        live_boost=boost,
        unrealised_goals=float(unrealised_goals),
        recent_shots=int(shots_last_10),
    )


def evaluate(
    timeline: MatchTimeline,
    *,
    home_goals: int = 0,
    away_goals: int = 0,
    home_unrealised: float = 0.0,
    away_unrealised: float = 0.0,
    home_odds: object = None,
    draw_odds: object = None,
    away_odds: object = None,
    first_half: bool | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    weights: WeightSet | None = None,
) -> KScoreResult:
    """K-Index for both teams at the timeline's current minute.

    `home_odds` / `draw_odds` / `away_odds` are the kickoff 1X2 prices;
    `*_unrealised` are Rule of 3's unrealised goals for each team.
    """
    w = weights or WeightSet.defaults()
    minute = timeline.current_minute
    in_first_half = minute <= 45 if first_half is None else bool(first_half)
    rates = chance.goal_rates(home_odds, draw_odds, away_odds)
    priced = rates is not None
    home_rate, away_rate = rates if rates is not None else DEFAULT_RATES

    def team(side: Side) -> TeamKScore:
        home = side is Side.HOME
        return evaluate_team(
            side,
            minute=minute,
            own_goals=home_goals if home else away_goals,
            opponent_goals=away_goals if home else home_goals,
            full_match_rate=home_rate if home else away_rate,
            first_half=in_first_half,
            unrealised_goals=home_unrealised if home else away_unrealised,
            shots_last_10=recent_shots(timeline, side),
            weights=w,
        )

    home_result = team(Side.HOME)
    away_result = team(Side.AWAY)
    either = 1.0 - (1.0 - home_result.probability) * (1.0 - away_result.probability)
    return KScoreResult(
        home=home_result,
        away=away_result,
        match_score=max(0, min(100, round(100.0 * either))),
        threshold=threshold,
        horizon_minutes=w.get(STRATEGY_KEY, "horizon_minutes"),
        priced=priced,
    )
