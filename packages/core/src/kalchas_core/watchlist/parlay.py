"""The day's parlay: one priced leg per strong match, in three orders.

Each Strong watch (then Worth a look) match offers at most one leg: its
strongest pattern that a bookmaker prices and we store a price for, which is
goals over or under 2.5, both teams to score yes or no, or a clear favourite
to win. Patterns without a stored price (cards, late goals, a team over 1.5,
...) stay on the watchlist only, so the combined odds are always real prices.

The page picks the first N legs of one order, so the slider costs no request:

* ``safer``: shortest prices first, only legs that came in at least 7 of 10
  times in the two teams' recent games;
* ``balanced``: the strongest patterns, the order the watchlist itself uses;
* ``bolder``: legs whose recent record beats the price by the most, from
  those that came in at least 55% of the time.

Strong watch legs always come before Worth a look ones, in every order.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

MAX_LEGS = 18
MIN_LEGS = 3
# A pattern weaker than this isn't worth a leg, even on a strong match.
MIN_PATTERN_SCORE = 0.15
SAFER_RATE = 0.7
BOLDER_RATE = 0.55
STYLES = ("safer", "balanced", "bolder")

# pattern key -> (odds field, pattern table row, flip the table's count)
_PRICED: dict[str, tuple[str, str | None, bool]] = {
    "over_2_5": ("over_2_5", "over_2_5", False),
    "under_2_5": ("under_2_5", "over_2_5", True),
    "btts_yes": ("btts_yes", "btts", False),
    "btts_no": ("btts_no", "btts", True),
    "favourite_home": ("home", None, False),
    "favourite_away": ("away", None, False),
}

_LABELS = {
    "over_2_5": "Over 2.5 goals",
    "under_2_5": "Under 2.5 goals",
    "btts_yes": "Both teams score",
    "btts_no": "Both teams score: No",
}

_WATCH_RANK = {"strong": 0, "look": 1}


def _record(key: str, page: Mapping[str, Any]) -> tuple[int, int] | None:
    """How often it happened in the two teams' recent games: (hits, games)."""
    _, row_key, flip = _PRICED[key]
    if row_key is None:
        side = "home" if key.endswith("_home") else "away"
        form = (page.get("form") or {}).get(side) or {}
        games = int(form.get("games") or 0)
        return (int(form.get("wins") or 0), games) if games else None
    for row in page.get("pattern_table") or []:
        if row.get("key") != row_key:
            continue
        hits = games = 0
        for side in ("home", "away"):
            count = row.get(side) or {}
            n = int(count.get("n") or 0)
            c = int(count.get("count") or 0)
            hits += n - c if flip else c
            games += n
        return (hits, games) if games else None
    return None


def _label(key: str, page: Mapping[str, Any]) -> str:
    if key in _LABELS:
        return _LABELS[key]
    side = "home" if key.endswith("_home") else "away"
    return f"{(page.get(side) or {}).get('name') or 'Favourite'} to win"


def leg_for(page: Mapping[str, Any]) -> dict[str, Any] | None:
    """The match's leg: its strongest priced pattern, or None."""
    if page.get("watch") not in _WATCH_RANK:
        return None
    odds = page.get("odds") or {}
    best: dict[str, Any] | None = None
    for pattern in page.get("patterns") or []:
        key = str(pattern.get("key") or "")
        score = float(pattern.get("score") or 0)
        if key not in _PRICED or score < MIN_PATTERN_SCORE:
            continue
        price = odds.get(_PRICED[key][0])
        if not price or float(price) <= 1:
            continue
        record = _record(key, page)
        if record is None:
            continue
        if best is not None and score <= best["score"]:
            continue
        best = {
            "market": key,
            "label": _label(key, page),
            "price": round(float(price), 2),
            "hit": record[0],
            "n": record[1],
            "brief": str(pattern.get("brief") or ""),
            "score": round(score, 3),
            "outcome": pattern.get("outcome"),
            "outcome_note": str(pattern.get("outcome_note") or ""),
        }
    if best is None:
        return None
    return {**_match(page), **best}


def _match(page: Mapping[str, Any]) -> dict[str, Any]:
    """The match a leg is on, as every leg carries it."""
    league = page.get("league") or {}

    def team(side: str) -> dict[str, Any]:
        t = page.get(side) or {}
        return {"name": t.get("name") or "", "badge": t.get("badge"), "position": t.get("position")}

    return {
        "match_id": str(page.get("match_id")),
        "kickoff": str(page.get("kickoff") or ""),
        "league": str(league.get("name") or ""),
        "country": str(league.get("country") or ""),
        "home": team("home"),
        "away": team("away"),
        "watch": page["watch"],
        "match_score": round(float(page.get("score") or 0), 3),
        "result": page.get("result"),
    }


# ------------------------------------------------------ picks of any market
#
# The admin's second slip takes each match's strongest pattern whatever the
# market. We hold a price for only some of them, so ``price`` may be None: the
# admin types the odds before the slip is posted.

# pattern key -> (pattern table row, flip the count), counted over both teams
_BOTH_ROWS: dict[str, tuple[str, bool]] = {
    "over_3_5": ("over_3_5", False),
    "late_goal": ("late_goal", False),
    "first_half_goal": ("first_half_goal", False),
    "cards_over_4_5": ("cards_5plus", False),
    "red_card": ("red_card", False),
}
# one-team pattern -> (pattern table row, flip the count), that team's games only
_TEAM_ROWS: dict[str, tuple[str, bool]] = {
    "scoring_run": ("failed_to_score", True),
    "leaky": ("clean_sheet", True),
    "blanks": ("failed_to_score", False),
    "team_over_1_5": ("scored_2plus", False),
}

_PICK_LABELS = {
    **_LABELS,
    "over_3_5": "Over 3.5 goals",
    "late_goal": "Goal after 75'",
    "first_half_goal": "First-half goal",
    "cards_over_4_5": "Over 4.5 cards",
    "red_card": "A red card",
    "penalty_h2h": "A penalty scored",
}


def _team_pattern(key: str) -> tuple[str, str]:
    """("leaky", "home") for ``leaky_home``; the side is "" for a whole-match key."""
    if key.endswith("_scoring_run"):
        return "scoring_run", key.removesuffix("_scoring_run")
    kind, _, side = key.rpartition("_")
    return (kind, side) if side in {"home", "away"} else (key, "")


def _counted(
    page: Mapping[str, Any], row_key: str, flip: bool, sides: Sequence[str]
) -> tuple[int, int] | None:
    for row in page.get("pattern_table") or []:
        if row.get("key") != row_key:
            continue
        hits = games = 0
        for side in sides:
            count = row.get(side) or {}
            n = int(count.get("n") or 0)
            c = int(count.get("count") or 0)
            hits += n - c if flip else c
            games += n
        return (hits, games) if games else None
    return None


def pick_record(key: str, page: Mapping[str, Any]) -> tuple[int, int] | None:
    """(hits, games) for any pattern, or None where the page has no count for
    it (corners and penalties come from the two teams' meetings only)."""
    if key in _PRICED:
        return _record(key, page)
    if key in _BOTH_ROWS:
        row_key, flip = _BOTH_ROWS[key]
        return _counted(page, row_key, flip, ("home", "away"))
    kind, side = _team_pattern(key)
    if side and kind in _TEAM_ROWS:
        row_key, flip = _TEAM_ROWS[kind]
        return _counted(page, row_key, flip, (side,))
    return None


def pick_label(key: str, page: Mapping[str, Any], *, tag: str = "") -> str:
    """The pick as a bet reads on a slip: "Away 3 to score", "Over 9.5 corners"."""
    if key in _PICK_LABELS:
        return _PICK_LABELS[key]
    if key.startswith("corners_over_"):
        return f"Over {key.removeprefix('corners_over_').replace('_', '.')} corners"
    kind, side = _team_pattern(key)
    if side:
        other = "away" if side == "home" else "home"
        name = (page.get(side) or {}).get("name") or side.title()
        rival = (page.get(other) or {}).get("name") or other.title()
        if kind == "scoring_run":
            return f"{name} to score"
        if kind == "leaky":
            return f"{rival} to score"
        if kind == "blanks":
            return f"{name} not to score"
        if kind == "team_over_1_5":
            return f"{name} over 1.5 goals"
        if kind == "favourite":
            return f"{name} to win"
    return tag or key.replace("_", " ")


def pick_for(page: Mapping[str, Any]) -> dict[str, Any] | None:
    """The match's strongest pattern of any market, priced where we hold one."""
    if page.get("watch") not in _WATCH_RANK:
        return None
    top: Mapping[str, Any] | None = None
    for pattern in page.get("patterns") or []:
        if top is None or float(pattern.get("score") or 0) > float(top.get("score") or 0):
            top = pattern
    if top is None or float(top.get("score") or 0) < MIN_PATTERN_SCORE:
        return None
    key = str(top.get("key") or "")
    price: float | None = None
    if key in _PRICED:
        held = (page.get("odds") or {}).get(_PRICED[key][0])
        if held and float(held) > 1:
            price = round(float(held), 2)
    hit, n = pick_record(key, page) or (0, 0)
    return {
        **_match(page),
        "market": key,
        "label": pick_label(key, page, tag=str(top.get("tag") or "")),
        "price": price,
        "hit": hit,
        "n": n,
        "brief": str(top.get("brief") or ""),
        "score": round(float(top.get("score") or 0), 3),
        "outcome": top.get("outcome"),
        "outcome_note": str(top.get("outcome_note") or ""),
    }


def picks_order(picks: Sequence[Mapping[str, Any]]) -> list[str]:
    """Strong matches first, then the strongest patterns: the watchlist's order."""
    pool = sorted(picks, key=lambda p: (_WATCH_RANK[p["watch"]], -p["score"], p["match_id"]))
    return [str(p["match_id"]) for p in pool[:MAX_LEGS]]


def _rate(leg: Mapping[str, Any]) -> float:
    return leg["hit"] / leg["n"] if leg["n"] else 0.0


def _chance(leg: Mapping[str, Any]) -> float:
    return 1 / leg["price"]


_KEYS: dict[str, Callable[[Mapping[str, Any]], float]] = {
    "safer": lambda leg: _chance(leg) * 2 + leg["score"],
    "balanced": lambda leg: leg["score"],
    "bolder": lambda leg: _rate(leg) - _chance(leg) + leg["score"] * 0.3,
}
_FLOORS = {"safer": SAFER_RATE, "balanced": 0.0, "bolder": BOLDER_RATE}


def order(legs: Sequence[Mapping[str, Any]], style: str) -> list[str]:
    """Match ids in the order a parlay of this style takes them, at most 18."""
    key = _KEYS[style]
    pool = [leg for leg in legs if _rate(leg) >= _FLOORS[style]]
    pool.sort(key=lambda leg: (_WATCH_RANK[leg["watch"]], -key(leg), leg["match_id"]))
    return [str(leg["match_id"]) for leg in pool[:MAX_LEGS]]


def build(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Every leg on offer, each style's order, the strong matches left out
    because none of their patterns has a price, and the any-market picks."""
    legs: list[dict[str, Any]] = []
    unpriced: list[dict[str, Any]] = []
    for page in pages:
        leg = leg_for(page)
        if leg:
            legs.append(leg)
        elif page.get("watch") == "strong":
            unpriced.append(
                {
                    "match_id": str(page.get("match_id")),
                    "home": (page.get("home") or {}).get("name") or "",
                    "away": (page.get("away") or {}).get("name") or "",
                    "tags": [str(p.get("tag") or "") for p in (page.get("patterns") or [])[:3]],
                }
            )
    legs.sort(key=lambda leg: (leg["kickoff"], leg["match_id"]))
    unpriced.sort(key=lambda m: m["match_id"])
    picks = [pick for pick in (pick_for(page) for page in pages) if pick]
    picks.sort(key=lambda pick: (pick["kickoff"], pick["match_id"]))
    return {
        "legs": legs,
        "order": {s: order(legs, s) for s in STYLES},
        "unpriced": unpriced,
        # Admin only: every match's strongest pattern, whatever the market.
        "picks": picks,
        "picks_order": picks_order(picks),
    }
