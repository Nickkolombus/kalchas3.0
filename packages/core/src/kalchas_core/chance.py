"""Scoring chance -- how likely a team is to score before full time.

Every strategy fires on a value in its own units (unrealised goals, pressure
points, goals behind pace), and none of those says how likely the goal is. A
Rule of 3 reading of 2.1 at 35' and the same reading at 86' are very different
bets. This module puts one number on a common scale next to each alert:

    full-match rate = the team's expected goals, from the kickoff 1X2 prices
    expected goals  = full-match rate
                      x share of a match's goals still to come at this minute
                      x score tilt (trailing teams score a little more)
                      x alert uplift
    chance          = 1 - exp(-expected goals)

Why these inputs: on settled alerts from 1-12 November 2026 the strategy's own
value could not tell hits from misses (0.51-0.52 on a scale where 0.5 is a
coin flip), while kickoff prices, the clock and the score together reached
0.71. Without the uplift the same arithmetic matched ordinary, non-alert
matches (actual / predicted 0.97 on 32 finished matches).

The alert uplift is the one fitted number. Teams a strategy alerts on score
more often than their kickoff price says, and `ALERT_UPLIFT` is the size of
that, measured on Rule of 3 and Form Bar alerts. `baseline` on the result is
the chance without it, i.e. what the price and the clock say on their own.

No kickoff prices means no chance: there is nothing to anchor the rate to.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final

from kalchas_core.match import Side

ALERT_UPLIFT: Final = 1.5
"""Scoring-rate multiplier for a team a strategy has just alerted on.

Fitted so predicted and actual hits match on 555 settled Rule of 3 and Form
Bar alerts (1-12 November 2026, alerted team to score before full time): 1.53,
with a 95% range of 1.28-1.81. The two weeks on their own give 1.44 and 1.56,
and October's Rule of 3 alerts 1.49, so it is "about one and a half", not a
precise constant. Re-fit it when thresholds or conditions change materially.

How well it holds: in November predicted and actual agree within a few points
across price, clock and score (71-80': 42% predicted, 42% actual; 81'+: 28%
and 28%). Outsiders priced above 4.0 were over-predicted (29% against 14% on
22 alerts). On October's alerts, fired under different conditions, the average
was right but readings of 60% and over were not: 73% predicted, 42% actual on
24 alerts.
"""

GOAL_SHARE_BY_QUARTER_HOUR: Final = (0.115, 0.135, 0.175, 0.155, 0.165, 0.255)
"""Share of a match's goals scored in each 15 minutes. Stoppage time belongs
to the third and sixth, which is why they are the largest."""

FIRST_HALF_STOPPAGE_MINUTES: Final = 3.0
SECOND_HALF_STOPPAGE_MINUTES: Final = 6.0

MIN_MINUTES_LEFT: Final = 0.5
"""Deep in stoppage the clock runs past what was assumed; there is still a
little time left for as long as the match is live."""

DEFAULT_TOTAL_GOALS: Final = 2.6
"""Match goals assumed when there is no draw price to read the total from."""

MIN_TOTAL_GOALS: Final = 0.8
MAX_TOTAL_GOALS: Final = 5.5

_MAX_GOALS: Final = 12
_BISECTION_STEPS: Final = 22
_HALF_TIME_MINUTE: Final = 45
_FIRST_HALF_STATUSES: Final = frozenset({"1H", "HT"})


@dataclass(frozen=True, slots=True)
class ScoringChance:
    """One team's chance to score before full time, as fractions of 1."""

    chance: float
    """With the alert uplift: the number to show next to an alert."""
    baseline: float
    """Kickoff prices, clock and score only."""
    expected_goals: float
    """Goals this team is expected to add before full time, with the uplift."""

    @property
    def percent(self) -> int:
        return round(self.chance * 100)

    @property
    def baseline_percent(self) -> int:
        return round(self.baseline * 100)


def _decimal_odds(value: object) -> float | None:
    try:
        price = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if price != price or price <= 1.0:
        return None
    return price


def _poisson(rate: float) -> list[float]:
    out = [math.exp(-rate)]
    for goals in range(1, _MAX_GOALS + 1):
        out.append(out[-1] * rate / goals)
    return out


def _wins_when_ahead(own: list[float], other: list[float]) -> float:
    """Probability that `own` scores strictly more than `other`."""
    total = 0.0
    other_at_most = 0.0
    for goals in range(1, len(own)):
        other_at_most += other[goals - 1]
        total += own[goals] * other_at_most
    return total


def _result_probabilities(home_rate: float, away_rate: float) -> tuple[float, float, float]:
    home = _poisson(home_rate)
    away = _poisson(away_rate)
    draw = sum(h * a for h, a in zip(home, away, strict=True))
    return _wins_when_ahead(home, away), draw, _wins_when_ahead(away, home)


@lru_cache(maxsize=4096)
def _solve_goal_rates(
    home_odds: float, draw_odds: float | None, away_odds: float
) -> tuple[float, float]:
    home_implied = 1.0 / home_odds
    away_implied = 1.0 / away_odds
    home_share_of_wins = home_implied / (home_implied + away_implied)

    def home_goal_share(total: float) -> float:
        """Split of `total` goals that reproduces the home/away win balance."""
        low, high = 0.02, 0.98
        for _ in range(_BISECTION_STEPS):
            mid = (low + high) / 2
            home_win, _draw, away_win = _result_probabilities(total * mid, total * (1 - mid))
            if home_win < home_share_of_wins * (home_win + away_win):
                low = mid
            else:
                high = mid
        return (low + high) / 2

    total = DEFAULT_TOTAL_GOALS
    if draw_odds is not None:
        draw_implied = 1.0 / draw_odds
        draw_target = draw_implied / (home_implied + draw_implied + away_implied)
        low, high = MIN_TOTAL_GOALS, MAX_TOTAL_GOALS
        # The more goals expected, the less likely a draw.
        for _ in range(_BISECTION_STEPS):
            mid = (low + high) / 2
            share = home_goal_share(mid)
            _home_win, draw, _away_win = _result_probabilities(mid * share, mid * (1 - share))
            if draw > draw_target:
                low = mid
            else:
                high = mid
        total = (low + high) / 2

    share = home_goal_share(total)
    return total * share, total * (1 - share)


def goal_rates(
    home_odds: object, draw_odds: object, away_odds: object
) -> tuple[float, float] | None:
    """Expected goals over a full match for (home, away), from kickoff 1X2.

    The bookmaker's margin is removed by scaling the three implied
    probabilities to sum to 1, then two Poisson scoring rates are found that
    reproduce them: the split between the teams from the home/away balance,
    the total from the draw price. With no draw price the total is
    `DEFAULT_TOTAL_GOALS`. None when the home or away price is unusable.
    """
    home = _decimal_odds(home_odds)
    away = _decimal_odds(away_odds)
    if home is None or away is None:
        return None
    return _solve_goal_rates(home, _decimal_odds(draw_odds), away)


def remaining_goal_share(minute: int, *, first_half: bool | None = None) -> float:
    """Share of a full match's goals still to come at this minute.

    `first_half` is the match period. Without it the minute decides, which is
    only wrong in first-half stoppage (45+2 arrives as 47), where the two
    readings are about three points apart.
    """
    quarters = GOAL_SHARE_BY_QUARTER_HOUR
    second_half_share = sum(quarters[3:])
    in_first_half = minute <= _HALF_TIME_MINUTE if first_half is None else first_half

    if in_first_half:
        clock = max(0.0, float(minute))
        if clock <= 30:
            index = min(1, int(clock // 15))
            played = (clock - 15 * index) / 15
            return (1 - played) * quarters[index] + sum(quarters[index + 1 :])
        length = 15 + FIRST_HALF_STOPPAGE_MINUTES
        played = min(1.0, (min(clock, 30 + length) - 30) / length)
        return (1 - played) * quarters[2] + second_half_share

    clock = max(float(_HALF_TIME_MINUTE), float(minute))
    if clock <= 75:
        index = min(4, int(clock // 15))
        played = (clock - 15 * index) / 15
        return (1 - played) * quarters[index] + sum(quarters[index + 1 :])
    length = 15 + SECOND_HALF_STOPPAGE_MINUTES
    played = (min(clock, 75 + length - MIN_MINUTES_LEFT) - 75) / length
    return (1 - played) * quarters[5]


def score_tilt(goal_difference: int) -> float:
    """Scoring-rate adjustment for the scoreline, from the team's own side.

    Teams behind push and score a little more often; teams ahead ease off.
    """
    if goal_difference == 0:
        return 1.0
    if goal_difference < 0:
        return 1.10
    if goal_difference == 1:
        return 0.93
    return 0.90


def scoring_chance(
    side: Side,
    *,
    minute: int,
    home_goals: int,
    away_goals: int,
    home_odds: object,
    draw_odds: object,
    away_odds: object,
    first_half: bool | None = None,
    uplift: float = ALERT_UPLIFT,
) -> ScoringChance | None:
    """Chance that `side` scores at least once more before full time.

    None without usable kickoff home and away prices.
    """
    rates = goal_rates(home_odds, draw_odds, away_odds)
    if rates is None:
        return None
    full_match_rate = rates[0] if side is Side.HOME else rates[1]
    own, other = (home_goals, away_goals) if side is Side.HOME else (away_goals, home_goals)
    expected = (
        full_match_rate
        * remaining_goal_share(minute, first_half=first_half)
        * score_tilt(int(own) - int(other))
    )
    return ScoringChance(
        chance=1.0 - math.exp(-expected * uplift),
        baseline=1.0 - math.exp(-expected),
        expected_goals=expected * uplift,
    )


def chance_record(chance: ScoringChance | None) -> dict[str, float] | None:
    """The shape stamped on an alert payload under ``chance``."""
    if chance is None:
        return None
    return {"chance": round(chance.chance, 3), "baseline": round(chance.baseline, 3)}


def _fraction(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number != number or not 0.0 <= number < 1.0:
        return None
    return number


def _kickoff_prices(odds: object) -> tuple[object, object, object]:
    if not isinstance(odds, Mapping):
        return None, None, None
    nested = odds.get("kickoff")
    source = nested if isinstance(nested, Mapping) else odds
    return source.get("home"), source.get("draw"), source.get("away")


def chance_for_alert(
    payload: Mapping[str, Any] | None,
    *,
    team: str | None = None,
    minute: int | None = None,
    score: str | None = None,
) -> ScoringChance | None:
    """The scoring chance of the team an alert is for.

    Reads the reading stamped on the payload when the alert fired. Alerts from
    before the stamp existed get it worked out from what they did store
    (kickoff prices, minute, score, match period), so old and new alerts can
    be grouped on the same scale. None for an alert with no single team or no
    kickoff prices.
    """
    raw = payload if isinstance(payload, Mapping) else {}
    stamped = raw.get("chance")
    if isinstance(stamped, Mapping):
        value = _fraction(stamped.get("chance"))
        baseline = _fraction(stamped.get("baseline"))
        if value is not None and baseline is not None:
            return ScoringChance(
                chance=value, baseline=baseline, expected_goals=-math.log(1.0 - value)
            )

    side_name = str(team or raw.get("team") or "").lower()
    if side_name not in (Side.HOME.value, Side.AWAY.value):
        return None
    clock = minute if minute is not None else raw.get("minute")
    goals = str(score or raw.get("score") or "").replace("–", "-").split("-")
    try:
        clock_minute = int(clock)  # type: ignore[arg-type]
        home_goals, away_goals = int(goals[0]), int(goals[1])
    except (TypeError, ValueError, IndexError):
        return None
    status = str(raw.get("status_short") or "").strip().upper()
    first_half = status in _FIRST_HALF_STATUSES if status else None
    home_odds, draw_odds, away_odds = _kickoff_prices(raw.get("odds"))
    return scoring_chance(
        Side(side_name),
        minute=clock_minute,
        home_goals=home_goals,
        away_goals=away_goals,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        first_half=first_half,
    )
