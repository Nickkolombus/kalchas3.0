"""In-memory minute history store."""

from __future__ import annotations

from dataclasses import dataclass, field

from kalchas_core.match import MatchTimeline
from kalchas_core.stats import flattened_to_minute_block, parse_statistics_payload


@dataclass
class MinuteStore:
    """Per-match cumulative minute_by_minute history for one scanner process."""

    _histories: dict[str, dict[str, dict]] = field(default_factory=dict)

    def merge_snapshot(
        self,
        match_id: str,
        minute: int,
        statistics: object,
        *,
        home_possession: int = 50,
        away_possession: int = 50,
        home_goals: int = 0,
        away_goals: int = 0,
    ) -> MatchTimeline:
        flat = parse_statistics_payload(statistics, home_possession, away_possession)
        block = flattened_to_minute_block(flat)
        block["goals"] = {"home": home_goals, "away": away_goals}
        history = self._histories.setdefault(match_id, {})
        history[str(minute)] = block
        return MatchTimeline.from_raw(history, minute)

    def timeline(self, match_id: str, minute: int) -> MatchTimeline | None:
        history = self._histories.get(match_id)
        if not history:
            return None
        return MatchTimeline.from_raw(history, minute)
