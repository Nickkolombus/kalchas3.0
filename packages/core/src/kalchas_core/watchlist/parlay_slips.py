"""A posted parlay slip, from snapshot to verdict.

The admin posts a slip; this keeps the legs exactly as posted and later
judges each one from the match result the watchlist stores. The result reply
waits until every match is played. A leg that was called off (postponed,
abandoned...) or that the result can't settle is never guessed: the admin
decides it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from kalchas_core.watchlist.parlay_share import STAKE
from kalchas_core.watchlist.results import settle

Outcome = Literal["landed", "missed", "void"]
LegState = Literal["pending", "landed", "missed", "off", "unjudged"]

OUTCOMES: tuple[Outcome, ...] = ("landed", "missed", "void")

# What the admin may answer for a leg the result can't settle by itself.
CHOICES: dict[str, tuple[Outcome, ...]] = {
    "off": ("void", "missed"),
    "unjudged": ("landed", "missed"),
}

_SNAPSHOT_KEYS = (
    "match_id",
    "kickoff",
    "league",
    "country",
    "watch",
    "market",
    "label",
    "price",
    "hit",
    "n",
)


def snapshot(leg: Mapping[str, Any]) -> dict[str, Any]:
    """The leg as posted: enough to draw the slip and judge it later."""
    out = {key: leg.get(key) for key in _SNAPSHOT_KEYS}
    out["match_id"] = str(leg.get("match_id"))
    out["price"] = round(float(leg.get("price") or 0), 2)
    for side in ("home", "away"):
        raw = leg.get(side)
        team: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
        out[side] = {"name": str(team.get("name") or ""), "badge": team.get("badge")}
    return out


def judge(leg: Mapping[str, Any], page: Mapping[str, Any] | None) -> dict[str, Any]:
    """Where one leg stands, from its match page (``None`` while not found)."""
    result = page.get("result") if page else None
    if not result:
        return {"state": "pending", "note": ""}
    if result.get("status") == "off":
        return {"state": "off", "note": str(result.get("label") or "Called off")}
    home = str((leg.get("home") or {}).get("name") or "")
    away = str((leg.get("away") or {}).get("name") or "")
    outcome, note = settle(str(leg.get("market") or ""), result, home=home, away=away)
    score = _score(result)
    if outcome is None:
        return {"state": "unjudged", "note": "The result doesn't say.", "score": score}
    return {"state": outcome, "note": note, "score": score}


def verdict(legs: Sequence[Mapping[str, Any]], outcomes: Mapping[str, Any]) -> dict[str, Any]:
    """The slip's standing from each leg's final outcome.

    ``done`` only once every leg has one. Void legs pay at evens, so they drop
    out of the combined odds; a slip with every leg void is ``void``.
    """
    final = {mid: _outcome(entry) for mid, entry in outcomes.items()}
    ids = [str(leg["match_id"]) for leg in legs]
    landed = [mid for mid in ids if final.get(mid) == "landed"]
    missed = [mid for mid in ids if final.get(mid) == "missed"]
    void = [mid for mid in ids if final.get(mid) == "void"]
    done = len(landed) + len(missed) + len(void) == len(ids)
    product = 1.0
    for leg in legs:
        if final.get(str(leg["match_id"])) != "void":
            product *= float(leg["price"])
    result: str | None = None
    if done:
        result = "lost" if missed else "came_in" if landed else "void"
    return {
        "done": done,
        "result": result,
        "landed": len(landed),
        "missed": len(missed),
        "void": len(void),
        "legs": len(ids),
        "missed_legs": [ids.index(mid) + 1 for mid in missed],
        "combined": round(product, 2),
        "returns": round(STAKE * product, 2) if result == "came_in" else 0.0,
    }


def marks(outcomes: Mapping[str, Any]) -> dict[str, str]:
    """match_id -> landed | missed | void, for the hand-marked slip."""
    return {
        mid: out for mid, out in ((m, _outcome(e)) for m, e in outcomes.items()) if out is not None
    }


def result_caption(slip: Mapping[str, Any], v: Mapping[str, Any]) -> str:
    """The short text under the marked slip in the reply."""
    n = int(v["legs"])
    if v["result"] == "came_in":
        head = f"Came in ✅ {v['landed']} of {n} legs landed"
        if v["void"]:
            head += f", {v['void']} void"
        head += f". Odds {v['combined']:.2f}: a {STAKE:.0f} stake returned {v['returns']:.2f}."
    elif v["result"] == "lost":
        which = ", ".join(str(i) for i in v["missed_legs"])
        word = "leg" if v["missed"] == 1 else "legs"
        head = f"Lost ❌ {v['landed']} of {n} landed; missed on {word} {which}."
    else:
        head = "Every leg was called off: the slip is void."
    return "\n".join([head, "", "kalchas.live", "For research & football enthusiast purposes only"])


def _outcome(entry: Any) -> str | None:
    value = entry.get("outcome") if isinstance(entry, Mapping) else entry
    return value if value in OUTCOMES else None


def _score(result: Mapping[str, Any]) -> str:
    h, a = result.get("home"), result.get("away")
    return f"{h}–{a}" if h is not None and a is not None else ""
