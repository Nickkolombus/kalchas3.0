"""Match timeline writers — scanner persists, API reads."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from kalchas_football import merge_odds_records

logger = logging.getLogger("kalchas.scanner.persist")


class MatchPersist(Protocol):
    def save_minute(
        self,
        *,
        match_id: str,
        home_team: str,
        away_team: str,
        home_team_id: int | None,
        away_team_id: int | None,
        league_name: str | None,
        league_id: int | None = None,
        status_short: str | None,
        home_score: int,
        away_score: int,
        minute: int,
        minute_block: dict[str, Any],
        lineup: dict[str, Any] | None = None,
        substitutions: dict[str, Any] | None = None,
        country_name: str | None = None,
        country_logo: str | None = None,
        home_team_logo: str | None = None,
        away_team_logo: str | None = None,
        odds: dict[str, Any] | None = None,
        minute_display: str | None = None,
    ) -> None: ...

    def load_history(self, match_id: str) -> dict[str, dict[str, Any]]: ...

    def load_header(self, match_id: str) -> dict[str, Any] | None: ...

    def save_events(self, match_id: str, events: list[dict[str, Any]]) -> None: ...


@dataclass
class NullMatchPersist:
    """No-op when DATABASE_URL is unset."""

    def save_minute(self, **kwargs: Any) -> None:
        return None

    def load_history(self, match_id: str) -> dict[str, dict[str, Any]]:
        return {}

    def load_header(self, match_id: str) -> dict[str, Any] | None:
        return None

    def save_events(self, match_id: str, events: list[dict[str, Any]]) -> None:
        return None


@dataclass
class MemoryMatchPersist:
    """In-process store for tests."""

    matches: dict[str, dict[str, Any]] = field(default_factory=dict)
    histories: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def save_minute(
        self,
        *,
        match_id: str,
        home_team: str,
        away_team: str,
        home_team_id: int | None,
        away_team_id: int | None,
        league_name: str | None,
        league_id: int | None = None,
        status_short: str | None,
        home_score: int,
        away_score: int,
        minute: int,
        minute_block: dict[str, Any],
        lineup: dict[str, Any] | None = None,
        substitutions: dict[str, Any] | None = None,
        country_name: str | None = None,
        country_logo: str | None = None,
        home_team_logo: str | None = None,
        away_team_logo: str | None = None,
        odds: dict[str, Any] | None = None,
        minute_display: str | None = None,
    ) -> None:
        previous = self.matches.get(match_id) or {}
        self.matches[match_id] = {
            "match_id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "league_name": league_name,
            "league_id": league_id if league_id else previous.get("league_id"),
            "status_short": status_short,
            "home_score": home_score,
            "away_score": away_score,
            "minute": minute,
            "minute_display": (minute_display or "").strip() or None,
            "country_name": country_name or previous.get("country_name"),
            "country_logo": country_logo or previous.get("country_logo"),
            "home_team_logo": home_team_logo or previous.get("home_team_logo"),
            "away_team_logo": away_team_logo or previous.get("away_team_logo"),
            "odds": merge_odds_records(previous.get("odds"), odds),
            "lineup": dict(lineup) if lineup else dict(previous.get("lineup") or {}),
            "substitutions": (
                dict(substitutions) if substitutions else dict(previous.get("substitutions") or {})
            ),
        }
        if minute_block:
            self.histories.setdefault(match_id, {})[str(minute)] = dict(minute_block)

    def load_history(self, match_id: str) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self.histories.get(match_id, {}).items()}

    def load_header(self, match_id: str) -> dict[str, Any] | None:
        row = self.matches.get(match_id)
        return dict(row) if row else None

    def save_events(self, match_id: str, events: list[dict[str, Any]]) -> None:
        self.events[match_id] = [dict(event) for event in events]


@dataclass
class PostgresMatchPersist:
    """Write match headers + minute rows for the live API and restart hydrate."""

    dsn: str

    def save_minute(
        self,
        *,
        match_id: str,
        home_team: str,
        away_team: str,
        home_team_id: int | None,
        away_team_id: int | None,
        league_name: str | None,
        league_id: int | None = None,
        status_short: str | None,
        home_score: int,
        away_score: int,
        minute: int,
        minute_block: dict[str, Any],
        lineup: dict[str, Any] | None = None,
        substitutions: dict[str, Any] | None = None,
        country_name: str | None = None,
        country_logo: str | None = None,
        home_team_logo: str | None = None,
        away_team_logo: str | None = None,
        odds: dict[str, Any] | None = None,
        minute_display: str | None = None,
    ) -> None:
        from kalchas_db.matches import upsert_match_minute_sync

        upsert_match_minute_sync(
            self.dsn,
            match_id=match_id,
            home_team=home_team,
            away_team=away_team,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            league_name=league_name,
            league_id=league_id,
            status_short=status_short,
            home_score=home_score,
            away_score=away_score,
            minute=minute,
            minute_block=minute_block,
            lineup=lineup,
            substitutions=substitutions,
            country_name=country_name,
            country_logo=country_logo,
            home_team_logo=home_team_logo,
            away_team_logo=away_team_logo,
            odds=odds,
            minute_display=minute_display,
        )

    def load_history(self, match_id: str) -> dict[str, dict[str, Any]]:
        from kalchas_db.matches import load_match_history_sync

        return load_match_history_sync(self.dsn, match_id)

    def load_header(self, match_id: str) -> dict[str, Any] | None:
        from kalchas_db.matches import get_match_sync

        return get_match_sync(self.dsn, match_id)

    def save_events(self, match_id: str, events: list[dict[str, Any]]) -> None:
        from kalchas_db.matches import upsert_match_events_sync

        upsert_match_events_sync(self.dsn, match_id, events)


def default_persist() -> MatchPersist:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if dsn:
        logger.info("match persist: postgres")
        return PostgresMatchPersist(dsn=dsn)
    logger.info("match persist: null (set DATABASE_URL to persist minutes)")
    return NullMatchPersist()
