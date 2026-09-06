"""Match status / phase — finished vs live vs half-time.

Two related helpers from 2.2:

* ``is_match_finished`` / ``is_match_live`` from ``utils/match_status.py`` —
  used by the web live filter and background scanner.
* ``infer_phase`` — the pure decision tree from ``MatchStateService`` that
  correctly treats HT as a break, not finished (the critical HT +
  ``match_live='0'`` bug fix).

Pinned defect in ``is_match_finished``: ``FINISHED_TOKENS`` includes
``"half time"`` / ``"halftime"``, so a long-status of ``"Half Time"`` with an
empty short code reports finished. Prefer ``infer_phase`` when you need
HT-aware behaviour.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

FINISHED_STATUS_CODES = frozenset(
    {
        "FT",
        "AET",
        "PEN",
        "PST",
        "CANC",
        "ABD",
        "SUSP",
        "AWD",
        "WO",
        "W/O",
    }
)

LIVE_STATUS_CODES = frozenset({"1H", "2H", "HT", "ET", "BT", "LIVE", "INP"})

FINISHED_TOKENS = (
    "finished",
    "match finished",
    "full-time",
    "full time",
    "fulltime",
    "ended",
    "ft",
    "ft.",
    "pen",
    "pen.",
    "penalty",
    "penalties",
    "after penalties",
    "aet",
    "after extra time",
    "postponed",
    "abandoned",
    "suspended",
    "cancelled",
    "canceled",
    "award",
    "walkover",
    "w/o",
    "break time",
    "half time",
    "halftime",
)


class MatchPhase(Enum):
    NOT_STARTED = "not_started"
    FIRST_HALF = "1h"
    HALF_TIME = "ht"
    SECOND_HALF = "2h"
    EXTRA_TIME_FIRST = "et1"
    EXTRA_TIME_BREAK = "et_break"
    EXTRA_TIME_SECOND = "et2"
    PENALTIES = "pen"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"


SHORT_STATUS_TO_PHASE = {
    "NS": MatchPhase.NOT_STARTED,
    "TBD": MatchPhase.NOT_STARTED,
    "1H": MatchPhase.FIRST_HALF,
    "HT": MatchPhase.HALF_TIME,
    "2H": MatchPhase.SECOND_HALF,
    "ET": MatchPhase.EXTRA_TIME_FIRST,
    "BT": MatchPhase.EXTRA_TIME_BREAK,
    "P": MatchPhase.PENALTIES,
    "PEN": MatchPhase.FINISHED,
    "FT": MatchPhase.FINISHED,
    "AET": MatchPhase.FINISHED,
    "PST": MatchPhase.POSTPONED,
    "CANC": MatchPhase.CANCELLED,
    "ABD": MatchPhase.CANCELLED,
    "AWD": MatchPhase.FINISHED,
    "WO": MatchPhase.FINISHED,
    "LIVE": MatchPhase.FIRST_HALF,
    "INP": MatchPhase.FIRST_HALF,
}

LONG_STATUS_TO_PHASE = {
    "half time": MatchPhase.HALF_TIME,
    "halftime": MatchPhase.HALF_TIME,
    "ht": MatchPhase.HALF_TIME,
    "finished": MatchPhase.FINISHED,
    "match finished": MatchPhase.FINISHED,
    "full time": MatchPhase.FINISHED,
    "after et": MatchPhase.FINISHED,
    "after pen": MatchPhase.FINISHED,
    "after pen.": MatchPhase.FINISHED,
}

_FINISHED_PHASES = frozenset({MatchPhase.FINISHED, MatchPhase.CANCELLED, MatchPhase.POSTPONED})
_LIVE_PHASES = frozenset(
    {
        MatchPhase.FIRST_HALF,
        MatchPhase.HALF_TIME,
        MatchPhase.SECOND_HALF,
        MatchPhase.EXTRA_TIME_FIRST,
        MatchPhase.EXTRA_TIME_BREAK,
        MatchPhase.EXTRA_TIME_SECOND,
        MatchPhase.PENALTIES,
    }
)


def is_match_finished(
    status_short: str = "",
    status_long: str = "",
    status: str = "",
    minute: int | None = None,
) -> bool:
    """Return True if the match is considered finished (2.2 live-filter SSOT).

    Stoppage-time rule: FT/AET/PEN with ``minute < 100`` returns False so
    late goals still land. See module docstring for the HT-token defect.
    """
    norm_short = (status_short or "").strip().upper()
    if norm_short and norm_short in FINISHED_STATUS_CODES:
        if minute is not None and norm_short in ("FT", "AET", "PEN") and minute < 100:
            return False
        return True
    norm_long = (status_long or "").strip().lower()
    norm_status = (status or "").strip().lower()
    for token in FINISHED_TOKENS:
        if token in norm_long or token in norm_status:
            return True
    return False


def is_match_finished_from_dict(match: dict[str, Any]) -> bool:
    status_short = (match.get("match_status_short") or match.get("status_short") or "").strip()
    status_long = (match.get("match_status") or match.get("status") or "").strip()
    minute = match.get("current_minute") or match.get("elapsed")
    if minute is not None:
        try:
            minute = int(minute)
        except (TypeError, ValueError):
            minute = None
    return is_match_finished(
        status_short=status_short,
        status_long=status_long,
        status=status_long,
        minute=minute,
    )


def is_match_live(status_short: str = "") -> bool:
    norm = (status_short or "").strip().upper()
    return bool(norm and norm in LIVE_STATUS_CODES)


def normalize_score(raw_score: Any) -> str:
    """Normalize a score value to ``'H-A'`` string format."""
    if raw_score is None:
        return ""
    if isinstance(raw_score, dict):
        return f"{raw_score.get('home', 0)}-{raw_score.get('away', 0)}"
    return str(raw_score)


def phase_from_minute(minute: int | None) -> MatchPhase:
    if minute is None or minute <= 0:
        return MatchPhase.NOT_STARTED
    if minute <= 50:
        return MatchPhase.FIRST_HALF
    if minute <= 95:
        return MatchPhase.SECOND_HALF
    if minute <= 105:
        return MatchPhase.EXTRA_TIME_FIRST
    if minute <= 130:
        return MatchPhase.EXTRA_TIME_SECOND
    return MatchPhase.FINISHED


def infer_phase(
    *,
    status_short: str = "",
    status_long: str = "",
    minute: int | None = None,
    match_live: str | None = None,
) -> MatchPhase:
    """Pure phase inference from MatchStateService (HT ≠ finished)."""
    short = (status_short or "").strip().upper()
    if short in SHORT_STATUS_TO_PHASE:
        return SHORT_STATUS_TO_PHASE[short]

    if status_long:
        status_lower = status_long.lower().strip()
        for key, phase in LONG_STATUS_TO_PHASE.items():
            if key in status_lower:
                return phase
        cleaned = status_lower.replace("+", "").replace(" ", "")
        if cleaned.isdigit() or "+" in status_lower:
            return phase_from_minute(minute)

    if minute is not None and minute > 0:
        return phase_from_minute(minute)

    if match_live == "0" and not status_short and not status_long:
        return MatchPhase.NOT_STARTED

    return MatchPhase.NOT_STARTED


def is_truly_finished_phase(phase: MatchPhase) -> bool:
    return phase in _FINISHED_PHASES


def is_live_phase(phase: MatchPhase) -> bool:
    return phase in _LIVE_PHASES
