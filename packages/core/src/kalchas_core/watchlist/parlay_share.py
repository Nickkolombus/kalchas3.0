"""Admin parlay share: slots, nightly window, and a selected slip.

The public page keeps Today/Tomorrow. Admin adds Nightly — kick-offs from
00:00 up to (not including) 07:00 GMT+3. Nightly is admin-only; this module
only filters and selects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Literal

from kalchas_core.watchlist.parlay import MAX_LEGS, MIN_LEGS, STYLES, order

Slot = Literal["today", "tomorrow", "nightly"]
Style = Literal["safer", "balanced", "bolder"]

STAKE = 10.0
NIGHTLY_START_HOUR = 0
NIGHTLY_END_HOUR = 7  # exclusive
# Fixed GMT+3 — matches the board's FOOTBALL_TIMEZONE default and the UI label.
# (A named city zone would drift an hour under DST and mis-filter +03:00 kick-offs.)
NIGHTLY_TZ = timezone(timedelta(hours=3))
NIGHTLY_LABEL = "GMT+3"
WINDOW_LABEL = f"00:00–07:00 {NIGHTLY_LABEL}"


def nightly_zone() -> timezone:
    """Fixed GMT+3 clock for the Nightly window. UI label is always GMT+3."""
    return NIGHTLY_TZ


def nightly_day(now: datetime | None = None) -> date:
    """Calendar day whose 00:00–07:00 GMT+3 window is the next (or current) Nightly.

    Before 07:00 local, that window is still today. From 07:00 onward, Nightly
    means tomorrow morning's early kick-offs.
    """
    local = (now or datetime.now(UTC)).astimezone(nightly_zone())
    if local.hour < NIGHTLY_END_HOUR:
        return local.date()
    return local.date() + timedelta(days=1)


def slot_day(slot: Slot, *, today: date, now: datetime | None = None) -> date:
    if slot == "today":
        return today
    if slot == "tomorrow":
        return today + timedelta(days=1)
    return nightly_day(now)


def _kickoff_local(kickoff: str) -> datetime | None:
    raw = (kickoff or "").strip()
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(nightly_zone())


def is_nightly_kickoff(kickoff: str) -> bool:
    """True when the kick-off falls in 00:00–07:00 on the Nightly clock."""
    when = _kickoff_local(kickoff)
    if when is None:
        return False
    return NIGHTLY_START_HOUR <= when.hour < NIGHTLY_END_HOUR


def filter_nightly(legs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(leg) for leg in legs if is_nightly_kickoff(str(leg.get("kickoff") or ""))]


def rebuild_orders(legs: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    return {style: order(legs, style) for style in STYLES}


def select_legs(
    legs: Sequence[Mapping[str, Any]],
    style_order: Sequence[str],
    *,
    exclude: Sequence[str] = (),
    wanted: int | None = None,
    include: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Legs in kick-off order for the slip: pinned legs first, then style order
    minus removals, capped at ``wanted``."""
    by_id = {str(leg["match_id"]): dict(leg) for leg in legs}
    dropped = {str(mid) for mid in exclude}
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    pinned = [str(mid) for mid in include if str(mid) in by_id and str(mid) not in dropped]
    for mid in [*dict.fromkeys(pinned), *style_order]:
        if mid in dropped or mid not in by_id or mid in seen:
            continue
        seen.add(mid)
        picked.append(by_id[mid])
        if wanted is not None and len(picked) >= wanted:
            break
    if wanted is None and len(picked) > MAX_LEGS:
        picked = picked[:MAX_LEGS]
    picked.sort(key=lambda leg: (str(leg.get("kickoff") or ""), str(leg["match_id"])))
    return picked


def combined_odds(legs: Sequence[Mapping[str, Any]]) -> float:
    total = 1.0
    for leg in legs:
        total *= float(leg["price"])
    return round(total, 2)


def returns_for(legs: Sequence[Mapping[str, Any]], stake: float = STAKE) -> float:
    return round(stake * combined_odds(legs), 2)


def can_post(legs: Sequence[Mapping[str, Any]]) -> bool:
    return len(legs) >= MIN_LEGS
