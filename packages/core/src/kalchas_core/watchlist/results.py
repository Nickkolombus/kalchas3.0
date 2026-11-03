"""After full time: the score, and whether each watchlist pattern landed.

Patterns are judged on the 90 minutes, like the markets they mirror. Extra
time and shootouts change the score shown, not whether both teams scored.
A pattern that cannot be judged (an untimed late goal, a 90-minute score the
provider left out) stays unsettled rather than guessed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from kalchas_core.watchlist.profile import LATE_FROM

FINISHED: Final = frozenset({"FT", "AET", "PEN"})
CALLED_OFF: Final = {
    "PST": "Postponed",
    "CANC": "Cancelled",
    "AWD": "Awarded",
    "Abandoned": "Abandoned",
    "Aban.": "Abandoned",
    "Interrupted": "Interrupted",
    "Suspended": "Suspended",
}
NO_RESULT: Final = {"status": "off", "label": "No result"}
"""For a match the provider still has no result for two days on."""
LABEL: Final = {"FT": "FT", "AET": "AET", "PEN": "Pens"}

LANDED: Final = "landed"
MISSED: Final = "missed"


def match_result(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """A ``kalchas_football.parse_results`` row as the result the watchlist
    stores, or `None` while the match is still to finish."""
    status = str(row.get("status_short") or "")
    if status in CALLED_OFF:
        return {"status": "off", "label": CALLED_OFF[status]}
    if status not in FINISHED:
        return None
    home, away = row.get("home_final"), row.get("away_final")
    if home is None or away is None:
        return None
    h90, a90 = row.get("home_90"), row.get("away_90")
    events = [g for g in row.get("goals") or [] if isinstance(g, Mapping)]
    regular = [g for g in events if g.get("half") in {"1H", "2H"}]
    timed = h90 is not None and a90 is not None and len(regular) == int(h90) + int(a90)
    ht_home, ht_away = row.get("home_ht"), row.get("away_ht")
    pens_home, pens_away = row.get("home_pens"), row.get("away_pens")
    return {
        "status": "finished",
        "label": LABEL[status],
        "home": int(home),
        "away": int(away),
        "home_90": None if h90 is None else int(h90),
        "away_90": None if a90 is None else int(a90),
        "ht": [int(ht_home), int(ht_away)] if ht_home is not None and ht_away is not None else None,
        "pens": [int(pens_home), int(pens_away)]
        if pens_home is not None and pens_away is not None
        else None,
        "timed": timed,
        "cards": None if row.get("cards") is None else int(row["cards"]),
        "red_card": None if row.get("cards") is None else bool(row.get("red_card")),
        "corners": None if row.get("corners") is None else int(row["corners"]),
        "goals": [
            {
                "time": str(g.get("display") or g.get("minute") or ""),
                "minute": int(g.get("minute") or 0),
                "half": str(g.get("half") or ""),
                "side": str(g.get("side") or ""),
                "penalty": bool(g.get("penalty")),
            }
            for g in events
        ]
        if len(events) == int(home) + int(away)
        else [],
    }


def _goals(total: int) -> str:
    if total == 0:
        return "No goals."
    return "1 goal." if total == 1 else f"{total} goals."


def _times(goals: Sequence[Mapping[str, Any]]) -> str:
    stamps = [f"{g['time']}'" for g in goals]
    if len(stamps) == 1:
        return stamps[0]
    return ", ".join(stamps[:-1]) + f" and {stamps[-1]}"


def settle(
    key: str, result: Mapping[str, Any] | None, *, home: str, away: str
) -> tuple[str | None, str]:
    """(``landed`` | ``missed`` | `None`, a short note on what happened)."""
    if not result or result.get("status") != "finished":
        return None, ""
    h, a = result.get("home_90"), result.get("away_90")
    if h is None or a is None:
        return None, ""
    total = h + a

    def outcome(hit: bool, note: str) -> tuple[str, str]:
        return (LANDED if hit else MISSED), note

    if key in {"btts_yes", "btts_no"}:
        both = h > 0 and a > 0
        note = (
            "Both teams scored."
            if both
            else "Neither side scored."
            if total == 0
            else f"Only {home if h else away} scored."
        )
        return outcome(both if key == "btts_yes" else not both, note)
    if key == "over_2_5":
        return outcome(total >= 3, _goals(total))
    if key == "under_2_5":
        return outcome(total <= 2, _goals(total))
    if key == "over_3_5":
        return outcome(total >= 4, _goals(total))
    if key == "penalty_h2h":
        if total == 0:
            return outcome(False, "No goals.")
        if not result.get("timed"):
            return None, ""
        pens = [
            g
            for g in result.get("goals") or []
            if g.get("penalty") and g.get("half") in {"1H", "2H"}
        ]
        return outcome(
            bool(pens), f"Penalty scored at {_times(pens)}." if pens else "No penalty scored."
        )
    if key.startswith("corners_over_"):
        corners = result.get("corners")
        if corners is None:
            return None, ""  # no statistics for this match
        line = float(key.removeprefix("corners_over_").replace("_", "."))
        return outcome(corners > line, f"{corners} corners.")
    if key in {"cards_over_4_5", "red_card"}:
        cards = result.get("cards")
        if cards is None:
            return None, ""  # the provider has no card data for this match
        if key == "red_card":
            red = bool(result.get("red_card"))
            return outcome(red, "A red card was shown." if red else "No red card.")
        return outcome(cards >= 5, "1 card." if cards == 1 else f"{cards} cards.")
    if key == "late_goal":
        if total == 0:
            return outcome(False, "No goals.")
        if not result.get("timed"):
            return None, ""
        late = [
            g
            for g in result.get("goals") or []
            if g.get("half") == "2H" and int(g.get("minute") or 0) >= LATE_FROM
        ]
        if late:
            return outcome(True, f"{'Goal' if len(late) == 1 else 'Goals'} at {_times(late)}.")
        return outcome(False, "No goal after 75'.")
    if key == "first_half_goal":
        ht = result.get("ht")
        if ht:
            return outcome(sum(ht) > 0, f"{ht[0]}–{ht[1]} at half-time.")
        if total == 0:
            return outcome(False, "No goals.")
        if not result.get("timed"):
            return None, ""
        early = [g for g in result.get("goals") or [] if g.get("half") == "1H"]
        return outcome(bool(early), "A first-half goal." if early else "No first-half goal.")

    # One-team patterns: home_scoring_run, leaky_away, blanks_home, favourite_away,
    # team_over_1_5_home.
    if key.endswith("_scoring_run"):
        kind, side = "scoring_run", key.removesuffix("_scoring_run")
    else:
        kind, _, side = key.rpartition("_")
    if side not in {"home", "away"}:
        return None, ""
    name, gf, ga = (home, h, a) if side == "home" else (away, a, h)
    if kind == "scoring_run":
        return outcome(gf > 0, f"{name} scored." if gf else f"{name} didn't score.")
    if kind == "leaky":
        return outcome(ga > 0, f"{name} conceded." if ga else f"{name} kept a clean sheet.")
    if kind == "blanks":
        return outcome(gf == 0, f"{name} scored." if gf else f"{name} failed to score.")
    if kind == "team_over_1_5":
        return outcome(gf >= 2, f"{name} scored {gf}.")
    if kind == "favourite":
        note = f"{name} won." if gf > ga else f"{name} drew." if gf == ga else f"{name} lost."
        return outcome(gf > ga, note)
    return None, ""


def settle_page(page: Mapping[str, Any], result: Mapping[str, Any] | None) -> dict[str, Any]:
    """The research page with its result and every pattern's outcome."""
    out = dict(page)
    out["result"] = dict(result) if result else None
    home = str((page.get("home") or {}).get("name") or "")
    away = str((page.get("away") or {}).get("name") or "")
    for field in ("points", "patterns"):
        judged = []
        for pattern in page.get(field) or []:
            verdict, note = settle(str(pattern.get("key")), result, home=home, away=away)
            judged.append({**pattern, "outcome": verdict, "outcome_note": note})
        out[field] = judged
    return out


def is_settled(page: Mapping[str, Any]) -> bool:
    result = page.get("result") or {}
    return result.get("status") in {"finished", "off"}


def _tally(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    judged = [r for r in rows if r.get("outcome") in {LANDED, MISSED}]
    return {"landed": sum(1 for r in judged if r["outcome"] == LANDED), "settled": len(judged)}


def day_summary(rows: Sequence[Mapping[str, Any]], top: Sequence[str]) -> dict[str, Any]:
    """Counts for the calendar and the day header. A match "landed" when its
    lead pattern (the list's headline) did."""
    top_ids = set(top)
    strong = [r for r in rows if r.get("watch") == "strong"]
    look = [r for r in rows if r.get("watch") == "look"]
    status = [str((r.get("result") or {}).get("status") or "") for r in rows]
    return {
        "matches": len(rows),
        "strong": len(strong),
        "look": len(look),
        "finished": status.count("finished"),
        "called_off": status.count("off"),
        "top": _tally([r for r in rows if r.get("match_id") in top_ids]),
        "strong_tally": _tally(strong),
        "look_tally": _tally(look),
    }
