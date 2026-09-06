"""Kickoff favourite detection from decimal odds.

Ported from the pure decision in ``utils/odds_analyzer`` /
``utils/odds_formatter._determine_favourite``. Threshold 1.78 matches 2.2.
Storage / API fetching stays in adapters.
"""

from __future__ import annotations

from typing import Any

FAVOURITE_ODDS_THRESHOLD = 1.78


def detect_favourite_side(
    home_odds: float | None,
    away_odds: float | None,
    *,
    threshold: float = FAVOURITE_ODDS_THRESHOLD,
) -> str | None:
    """Return ``'home'``, ``'away'``, or ``None`` from decimal kickoff odds."""
    if home_odds is not None and home_odds < threshold:
        return "home"
    if away_odds is not None and away_odds < threshold:
        return "away"
    return None


def extract_1x2_odds(payload: Any) -> dict[str, float | None] | None:
    """Pull home/draw/away decimals from common API-Football odds shapes.

    Accepts either a list of bookmaker blocks or a list of wrapped responses
    containing ``bookmakers``. First complete home+away pair wins.
    """
    if not payload:
        return None
    blocks = payload if isinstance(payload, list) else [payload]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        bookmakers = block.get("bookmakers")
        if isinstance(bookmakers, list):
            for book in bookmakers:
                odds = _from_bookmaker(book)
                if odds and odds.get("home") is not None and odds.get("away") is not None:
                    return odds
        odds = _from_bookmaker(block)
        if odds and odds.get("home") is not None and odds.get("away") is not None:
            return odds
    return None


def detect_favourite_from_payload(
    payload: Any,
    *,
    threshold: float = FAVOURITE_ODDS_THRESHOLD,
) -> str | None:
    """Extract 1X2 odds then classify the favourite."""
    odds = extract_1x2_odds(payload)
    if not odds:
        return None
    return detect_favourite_side(odds.get("home"), odds.get("away"), threshold=threshold)


def _from_bookmaker(book: Any) -> dict[str, float | None] | None:
    if not isinstance(book, dict):
        return None
    bets = book.get("bets")
    if not isinstance(bets, list):
        return None
    home = draw = away = None
    for bet in bets:
        if not isinstance(bet, dict):
            continue
        name = str(bet.get("name") or "").lower()
        if name not in ("match winner", "1x2", "full time result", "match result"):
            # Still try values that look like Home/Draw/Away
            pass
        values = bet.get("values")
        if not isinstance(values, list):
            continue
        for entry in values:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("value") or "").strip().lower()
            odd = _safe_float(entry.get("odd"))
            if odd is None:
                continue
            if label in ("home", "1"):
                home = odd
            elif label in ("draw", "x"):
                draw = odd
            elif label in ("away", "2"):
                away = odd
        if home is not None and away is not None:
            return {"home": home, "draw": draw, "away": away}
    if home is not None and away is not None:
        return {"home": home, "draw": draw, "away": away}
    return None


def _safe_float(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
