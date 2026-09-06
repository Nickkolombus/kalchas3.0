"""Shared fixtures for building match timelines in tests."""

from __future__ import annotations

from typing import Any

from kalchas_core.match import MatchTimeline


def raw_minute(
    *,
    home: dict[str, Any] | None = None,
    away: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One minute of feed data, in the scanner's stat-keyed then team-keyed shape."""
    h = home or {}
    a = away or {}
    stats = (
        "attacks",
        "dangerous_attacks",
        "shots_on_target",
        "shots_off_target",
        "corners",
        "fouls",
        "possession",
    )
    return {stat: {"home": h.get(stat, 0), "away": a.get(stat, 0)} for stat in stats}


def timeline_from(
    minutes: dict[int, dict[str, Any]],
    current_minute: int | None = None,
) -> MatchTimeline:
    """Build a timeline from `{minute: {"home": {...}, "away": {...}}}`.

    Mirrors how the scanner stores history: string minute keys over nested
    stat blocks.
    """
    raw = {
        str(minute): raw_minute(home=teams.get("home"), away=teams.get("away"))
        for minute, teams in minutes.items()
    }
    return MatchTimeline.from_raw(
        raw,
        current_minute if current_minute is not None else max(minutes),
    )
