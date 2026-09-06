"""In-memory minute history store, optionally hydrated from Postgres."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kalchas_core.match import MatchTimeline
from kalchas_core.stats import flattened_to_minute_block, parse_statistics_payload


@dataclass
class MinuteStore:
    """Per-match cumulative minute_by_minute history for one scanner process."""

    _histories: dict[str, dict[str, dict]] = field(default_factory=dict)

    def has(self, match_id: str) -> bool:
        return match_id in self._histories

    def seed_history(self, match_id: str, history: dict[str, dict[str, Any]]) -> None:
        """Load prior minutes (e.g. after a Railway restart) before the next merge."""
        if not history:
            return
        self._histories[match_id] = {str(k): dict(v) for k, v in history.items()}

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

    def latest_block(self, match_id: str, minute: int) -> dict[str, Any] | None:
        history = self._histories.get(match_id)
        if not history:
            return None
        block = history.get(str(minute))
        return dict(block) if block is not None else None

    def timeline(self, match_id: str, minute: int) -> MatchTimeline | None:
        history = self._histories.get(match_id)
        if not history:
            return None
        return MatchTimeline.from_raw(history, minute)
