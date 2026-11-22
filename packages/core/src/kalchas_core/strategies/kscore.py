"""K-Index (Strategy 7) -- how likely a team is to score soon, built on its play.

    priced chance = team goal rate from the kickoff 1X2 prices
                    x share of a match's goals due in the next `horizon` minutes,
                      stopping at the end of the current half
                    x score tilt (teams behind score a little more)
    shot pace     = (shots + recent_shots_extra x shots in the last 10')
                    / (minute + settling_minutes)
    expected pace = team goal rate / 90 x SHOTS_PER_GOAL
    evidence      = (shot pace / expected pace) ^ evidence_power, capped
    early brake   = (minute / early_brake_minutes) ^ 2 until that minute, then 1
    K             = 100 x (1 - exp(-level x priced chance x evidence
                                   x [first-half multiplier] x early brake))

K rises only with play. A team that has not shot reads 0 whatever its price;
the price decides how much each shot is worth, so a favourite climbs faster
than an outsider on the same shooting. In the first minutes the brake and the
settling minutes mean only an extraordinary burst moves it: in 705 saved
matches K reached 40 before 10' five times.

Above about 10 the number reads as a chance of scoring inside the window, the
bet K alerts are settled on (team-specific, 20 minutes, ends at half time). A
low K means "not enough play to say", not "no chance": team-minutes reading 0
still scored 22% of the time, against 22% overall.

History. The original K-Score blended Delta 5min, Pressure Index and Rule of 3
through a logit with ten hand-set weights and never reached its threshold of
40 (highest 34 over 104k team-minutes). On 2026-11-22 it became the priced
chance with a small live nudge; that read 30+ at kickoff for short-priced
favourites with no play behind it, so the same day it was rebuilt again as
this play-driven version.

Fitted on 705 finished matches in `match_history` (118k team-minutes from 1'),
evidence power and settling minutes chosen, the rest fitted:

- K 20-30 scored 24%, 30-40 30%, 40-50 43%, 50-60 54%.
- K 40+ on 2-3% of team-minutes, hit 42-45% on the half of the matches the
  fit had not seen (an ordinary team-minute: 22%).
- Ranking is a little weaker than the price on its own (AUC 0.58 against
  0.64), because quiet favourites still score; the alerts at 40+ hit as often.

Without kickoff prices the rates use an average match (DEFAULT_RATES), so K
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

SHOTS_PER_GOAL: Final = 10.0
"""Shots (on and off target) a team takes per goal, roughly. Turns the price's
goal rate into the shooting pace the price expects."""

DEFAULT_RATES: Final = (1.45, 1.15)
"""Full-match goal rates (home, away) for a match without kickoff prices:
`chance.DEFAULT_TOTAL_GOALS` split with an ordinary home advantage."""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class TeamKScore:
    """One team's K-Index and what went into it."""

    score: int
    """0-100."""
    probability: float
    priced_chance: float
    """Chance from kickoff prices, clock and score alone, before any play counts."""
    evidence: float
    """Multiplier from the shooting: 0 with no shots, 1 at the pace the price expects."""
    shots: int
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
    """0-100: combined reading for either team scoring inside the window."""
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


def evidence(
    *,
    minute: int,
    shots: int,
    shots_last_10: int,
    full_match_rate: float,
    weights: WeightSet,
) -> float:
    """How the team's shooting compares with what its price expects, as a multiplier."""
    settling = max(0.0, weights.get(STRATEGY_KEY, "settling_minutes"))
    extra = weights.get(STRATEGY_KEY, "recent_shots_extra")
    weighted_shots = max(0, int(shots)) + extra * max(0, int(shots_last_10))
    pace = weighted_shots / max(1.0, float(minute) + settling)
    expected_pace = max(1e-6, full_match_rate) / 90.0 * SHOTS_PER_GOAL
    power = _clamp(weights.get(STRATEGY_KEY, "evidence_power"), 0.0, 1.0)
    value = (pace / expected_pace) ** power if pace > 0 else (0.0 if power > 0 else 1.0)
    return _clamp(value, 0.0, max(0.0, weights.get(STRATEGY_KEY, "max_evidence")))


def early_brake(minute: int, weights: WeightSet) -> float:
    """1 from `early_brake_minutes` on; before it (minute / that)^2."""
    span = weights.get(STRATEGY_KEY, "early_brake_minutes")
    if span <= 0 or minute >= span:
        return 1.0
    return max(0.0, float(minute) / span) ** 2


def evaluate_team(
    *,
    minute: int,
    own_goals: int,
    opponent_goals: int,
    full_match_rate: float,
    first_half: bool,
    shots: int,
    shots_last_10: int,
    weights: WeightSet,
) -> TeamKScore:
    """K-Index for one team."""
    horizon = weights.get(STRATEGY_KEY, "horizon_minutes")
    priced = (
        full_match_rate
        * chance.window_goal_share(minute, horizon, first_half=first_half)
        * chance.score_tilt(int(own_goals) - int(opponent_goals))
    )
    shown = evidence(
        minute=minute,
        shots=shots,
        shots_last_10=shots_last_10,
        full_match_rate=full_match_rate,
        weights=weights,
    )
    expected = (
        weights.get(STRATEGY_KEY, "level")
        * priced
        * shown
        * (weights.get(STRATEGY_KEY, "first_half_multiplier") if first_half else 1.0)
        * early_brake(minute, weights)
    )
    probability = 1.0 - math.exp(-expected)
    return TeamKScore(
        score=max(0, min(100, round(100.0 * probability))),
        probability=probability,
        priced_chance=1.0 - math.exp(-priced),
        evidence=shown,
        shots=int(shots),
        recent_shots=int(shots_last_10),
    )


def evaluate(
    timeline: MatchTimeline,
    *,
    home_goals: int = 0,
    away_goals: int = 0,
    home_odds: object = None,
    draw_odds: object = None,
    away_odds: object = None,
    first_half: bool | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    weights: WeightSet | None = None,
) -> KScoreResult:
    """K-Index for both teams at the timeline's current minute.

    `home_odds` / `draw_odds` / `away_odds` are the kickoff 1X2 prices.
    """
    w = weights or WeightSet.defaults()
    minute = timeline.current_minute
    in_first_half = minute <= 45 if first_half is None else bool(first_half)
    rates = chance.goal_rates(home_odds, draw_odds, away_odds)
    home_rate, away_rate = rates if rates is not None else DEFAULT_RATES
    current = timeline.current

    def team(side: Side) -> TeamKScore:
        home = side is Side.HOME
        stats = current.team(side) if current is not None else None
        return evaluate_team(
            minute=minute,
            own_goals=home_goals if home else away_goals,
            opponent_goals=away_goals if home else home_goals,
            full_match_rate=home_rate if home else away_rate,
            first_half=in_first_half,
            shots=stats.total_shots if stats is not None else 0,
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
        priced=rates is not None,
    )
