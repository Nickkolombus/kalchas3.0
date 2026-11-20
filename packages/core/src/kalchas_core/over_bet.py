"""The Over-goals bet each alert stands for, and how it is graded.

Most of the audience bets Over goals, not which team scores, so every alert
is also read as an Over bet at the live price when it fired:

- second-half alerts: Over (goals so far + 0.5) to full time;
- first-half alerts: one of two, picked in admin (``first_half_mode``):
  Over (goals + 1.5) to full time (default) or Over (goals + 0.5) by half-time.
  Both are priced and graded on every first-half alert, so the other choice
  can be judged before switching.

BFbot's tips.csv keeps its own rule (Over + 0.5, first-half line before HT).
Prices are the bookmaker lines stored in ``payload["live_goal_odds"]``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

FT_O05: Final = "ft_o05"
"""Over (goals + 0.5) to full time: second-half alerts."""
FT_O15: Final = "ft_o15"
"""Over (goals + 1.5) to full time: first-half alerts (default)."""
HT_O05: Final = "ht_o05"
"""Over (goals + 0.5) by half-time: first-half alerts (tracked, or chosen in admin)."""

FIRST_HALF_MODES: Final = (FT_O15, HT_O05)
DEFAULT_FIRST_HALF_MODE: Final = FT_O15

_SPEC: Final[dict[str, tuple[str, float]]] = {
    FT_O05: ("ft", 0.5),
    FT_O15: ("ft", 1.5),
    HT_O05: ("h1", 0.5),
}
"""variant -> (period, goals over the score at fire)."""

VARIANT_LABELS: Final = {
    FT_O05: "FT Over +0.5",
    FT_O15: "FT Over +1.5",
    HT_O05: "HT Over +0.5",
}


def normalize_first_half_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in FIRST_HALF_MODES else DEFAULT_FIRST_HALF_MODE


def score_total(score: Any) -> int | None:
    """Goals in a "h-a" score, or None when it does not parse."""
    text = str(score or "").replace("–", "-").replace("—", "-")
    parts = [p.strip() for p in text.split("-")]
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]) + int(parts[1])


def _price(goal_odds: Any, period: str, line: float) -> float | None:
    if not isinstance(goal_odds, Mapping):
        return None
    block = goal_odds.get(period)
    if not isinstance(block, Mapping):
        return None
    leg = block.get(f"{line:.1f}")
    if not isinstance(leg, Mapping):
        return None
    try:
        price = float(leg.get("over"))
    except (TypeError, ValueError):
        return None
    return price if price > 1.0 else None


def bet_label(period: str, line: float) -> str:
    """ "Over 1.5 FT" / "Over 0.5 HT"."""
    return f"Over {line:.1f} {'HT' if period == 'h1' else 'FT'}"


def over_bets_for_alert(
    *,
    score: Any,
    first_half: bool,
    goal_odds: Any,
    first_half_mode: Any = DEFAULT_FIRST_HALF_MODE,
) -> dict[str, Any] | None:
    """The bet(s) an alert stands for, priced from ``live_goal_odds``.

    ``{"primary": variant, "bets": {variant: {"period", "line", "label", "price"}}}``;
    ``price`` is None when the feed had no fresh line. None when the score
    does not parse.
    """
    total = score_total(score)
    if total is None:
        return None
    variants = FIRST_HALF_MODES if first_half else (FT_O05,)
    primary = normalize_first_half_mode(first_half_mode) if first_half else FT_O05
    bets: dict[str, dict[str, Any]] = {}
    for variant in variants:
        period, extra = _SPEC[variant]
        line = total + extra
        bets[variant] = {
            "period": period,
            "line": line,
            "label": bet_label(period, line),
            "price": _price(goal_odds, period, line),
        }
    return {"primary": primary, "bets": bets}


def primary_bet(over_bet: Any) -> dict[str, Any] | None:
    """The chosen bet from an ``over_bet`` record, or None."""
    if not isinstance(over_bet, Mapping):
        return None
    bets = over_bet.get("bets")
    if not isinstance(bets, Mapping):
        return None
    bet = bets.get(over_bet.get("primary"))
    return dict(bet) if isinstance(bet, Mapping) else None


def grade_over_bets(
    over_bet: Any,
    *,
    ht_total: int | None,
    ft_total: int | None,
) -> dict[str, Any] | None:
    """Each bet with ``won`` set from the half-time and 90-minute totals.

    A bet whose period total is unknown keeps ``won`` None. Extra time never
    counts: ``ft_total`` is the 90-minute score.
    """
    if not isinstance(over_bet, Mapping) or not isinstance(over_bet.get("bets"), Mapping):
        return None
    graded: dict[str, dict[str, Any]] = {}
    for variant, bet in over_bet["bets"].items():
        if not isinstance(bet, Mapping):
            continue
        end = ht_total if bet.get("period") == "h1" else ft_total
        row = dict(bet)
        row["won"] = None if end is None else end > float(bet.get("line") or 0)
        graded[str(variant)] = row
    return {"primary": over_bet.get("primary"), "bets": graded}


def bet_return(price: Any, won: Any) -> float | None:
    """Profit of a 1-unit stake at ``price`` (no commission); None when unpriced or ungraded."""
    if won is None:
        return None
    try:
        odds = float(price)
    except (TypeError, ValueError):
        return None
    if odds <= 1.0:
        return None
    return odds - 1.0 if won else -1.0
