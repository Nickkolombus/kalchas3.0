"""Typed view over a match's minute-by-minute statistics.

The scanner records a cumulative stat line for each team on each minute. Every
strategy reads that history, so this module is the shape the rest of the core
agrees on.

In Kalchas 2.2 this history was passed around as a raw
`dict[str, dict[str, dict[str, Any]]]` -- minute string, then stat name, then
team name -- and each consumer re-implemented its own coercion helper
(`_safe_team_int`, `get_safe_sot_data`, and others) to dig a number out of it.
Parsing happens once here instead, so a malformed feed is caught at the edge
rather than silently becoming a zero in the middle of a formula.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class Side(StrEnum):
    """Which team a value belongs to."""

    HOME = "home"
    AWAY = "away"

    @property
    def opponent(self) -> Side:
        return Side.AWAY if self is Side.HOME else Side.HOME


@dataclass(frozen=True, slots=True)
class TeamStats:
    """One team's cumulative counters at a single minute.

    Counters are match totals to date, not per-minute increments. Strategies
    difference two snapshots to get activity over a window.
    """

    attacks: int = 0
    dangerous_attacks: int = 0
    shots_on_target: int = 0
    shots_off_target: int = 0
    corners: int = 0
    fouls: int = 0
    possession: float = 0.0

    @property
    def total_shots(self) -> int:
        return self.shots_on_target + self.shots_off_target


@dataclass(frozen=True, slots=True)
class MinuteSnapshot:
    """Both teams' counters at one minute of the match."""

    minute: int
    home: TeamStats
    away: TeamStats

    def team(self, side: Side) -> TeamStats:
        return self.home if side is Side.HOME else self.away


def _coerce_count(value: Any) -> int:
    """Read a counter from the feed, treating anything unusable as zero.

    Feeds send counters as ints, as numeric strings, as floats, and sometimes
    as null for a stat the provider has not populated yet. None of those is
    exceptional, and a missing counter genuinely means zero events so far.
    """
    if value is None:
        return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _coerce_percentage(value: Any) -> float:
    """Read a possession percentage, clamped to 0-100."""
    if value is None:
        return 0.0
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _team_stats(raw_minute: Mapping[str, Any], side: Side) -> TeamStats:
    """Pull one team's counters out of a stat-keyed, then team-keyed minute blob."""

    def counter(stat: str) -> int:
        block = raw_minute.get(stat)
        if not isinstance(block, Mapping):
            return 0
        return _coerce_count(block.get(side.value))

    possession_block = raw_minute.get("possession")
    possession = (
        _coerce_percentage(possession_block.get(side.value))
        if isinstance(possession_block, Mapping)
        else 0.0
    )

    return TeamStats(
        attacks=counter("attacks"),
        dangerous_attacks=counter("dangerous_attacks"),
        shots_on_target=counter("shots_on_target"),
        shots_off_target=counter("shots_off_target"),
        corners=counter("corners"),
        fouls=counter("fouls"),
        possession=possession,
    )


@dataclass(frozen=True, slots=True)
class MatchTimeline:
    """Every recorded minute of one match, plus where the clock currently is."""

    minutes: Mapping[int, MinuteSnapshot]
    current_minute: int

    @classmethod
    def from_raw(
        cls,
        minute_by_minute: Mapping[str, Any] | None,
        current_minute: Any,
    ) -> MatchTimeline:
        """Build a timeline from the scanner's raw nested dictionaries.

        Minute keys that are not integers are skipped rather than raising: the
        feed occasionally carries sentinel keys such as `"HT"` alongside the
        numeric ones.
        """
        parsed: dict[int, MinuteSnapshot] = {}

        for key, raw_minute in (minute_by_minute or {}).items():
            if not isinstance(raw_minute, Mapping):
                continue
            try:
                minute = int(str(key))
            except (TypeError, ValueError):
                continue
            parsed[minute] = MinuteSnapshot(
                minute=minute,
                home=_team_stats(raw_minute, Side.HOME),
                away=_team_stats(raw_minute, Side.AWAY),
            )

        return cls(
            minutes=MappingProxyType(dict(sorted(parsed.items()))),
            current_minute=_coerce_count(current_minute),
        )

    @property
    def available_minutes(self) -> tuple[int, ...]:
        """Every recorded minute, ascending."""
        return tuple(self.minutes)

    def snapshot_at(self, minute: int) -> MinuteSnapshot | None:
        return self.minutes.get(minute)

    def snapshot_at_or_before(self, minute: int, *, lookback: int = 5) -> MinuteSnapshot | None:
        """The snapshot at `minute`, or the most recent one within `lookback`.

        The scanner polls on a cadence and drops frames, so an exact minute is
        often missing. Since counters are cumulative, a slightly stale snapshot
        is a usable stand-in. Used by Strategy 3, which reads both ends of its
        window by minute rather than resolving a window over recorded minutes.
        """
        for candidate in range(minute, max(0, minute - lookback) - 1, -1):
            found = self.minutes.get(candidate)
            if found is not None:
                return found
        return None

    @property
    def current(self) -> MinuteSnapshot | None:
        """The snapshot for the current minute, if the scanner recorded one."""
        return self.minutes.get(self.current_minute)

    def __bool__(self) -> bool:
        return bool(self.minutes)
