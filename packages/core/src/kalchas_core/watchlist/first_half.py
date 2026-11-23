"""Chance of a goal before half-time, from the kick-off Over/Under 2.5 price.

    expected goals = the Poisson mean whose chance of 3+ goals matches the
                     Over 2.5 price, the bookmaker's margin removed
    chance         = 1 / (1 + exp(-(INTERCEPT + SLOPE x ln(expected goals))))

Fitted on 5,973 finished watchlist matches (2-23 Nov 2026), each frozen at
kick-off with its prices. Tested on 16-23 Nov after fitting on 2-15 Nov, the
price was the only signal that held up: the two teams' first-half record and
the league's added nothing once it was known (AUC 0.564 with or without them).

Matches it put in the top tenth (chance 80% or more, about 27 a day) had a
first-half goal 82-84% of the time, against 72% for every match. Nothing
reliably reaches 90%: the top 2% landed 84%. The old team-history version of
the pattern, when it led a pick, landed 63%.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

INTERCEPT: Final = -1.2048
SLOPE: Final = 2.045

BADGE_MIN: Final = 0.80
"""The live board marks matches at or above this: about the top tenth."""

_MIN_GOALS: Final = 0.3
_MAX_GOALS: Final = 8.0
_STEPS: Final = 50


def _price(value: object) -> float | None:
    try:
        price = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return price if price > 1.0 and math.isfinite(price) else None


def _three_plus(mean: float) -> float:
    return 1.0 - math.exp(-mean) * (1.0 + mean + mean * mean / 2.0)


def expected_goals(over_2_5: object, under_2_5: object) -> float | None:
    """Goals the Over/Under 2.5 line expects, or None without both prices."""
    over, under = _price(over_2_5), _price(under_2_5)
    if over is None or under is None:
        return None
    target = (1.0 / over) / (1.0 / over + 1.0 / under)
    low, high = _MIN_GOALS, _MAX_GOALS
    for _ in range(_STEPS):
        mid = (low + high) / 2.0
        if _three_plus(mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def first_half_chance(odds: Mapping[str, Any] | None) -> float | None:
    """0-1 chance of a goal before half-time, or None without an Over/Under 2.5 price."""
    if not odds:
        return None
    goals = expected_goals(odds.get("over_2_5"), odds.get("under_2_5"))
    if goals is None:
        return None
    return 1.0 / (1.0 + math.exp(-(INTERCEPT + SLOPE * math.log(goals))))
