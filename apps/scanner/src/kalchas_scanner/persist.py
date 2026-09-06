"""Match timeline writers — scanner persists, API reads."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

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
        status_short: str | None,
        home_score: int,
        away_score: int,
        minute: int,
        minute_block: dict[str, Any],
    ) -> None: ...

    def load_history(self, match_id: str) -> dict[str, dict[str, Any]]: ...


@dataclass
class NullMatchPersist:
    """No-op when DATABASE_URL is unset."""

    def save_minute(self, **kwargs: Any) -> None:
        return None

    def load_history(self, match_id: str) -> dict[str, dict[str, Any]]:
        return {}


@dataclass
class MemoryMatchPersist:
    """In-process store for tests."""

    matches: dict[str, dict[str, Any]] = field(default_factory=dict)
    histories: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    def save_minute(
        self,
        *,
        match_id: str,
        home_team: str,
        away_team: str,
        home_team_id: int | None,
        away_team_id: int | None,
        league_name: str | None,
        status_short: str | None,
        home_score: int,
        away_score: int,
        minute: int,
        minute_block: dict[str, Any],
    ) -> None:
        self.matches[match_id] = {
            "match_id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "league_name": league_name,
            "status_short": status_short,
            "home_score": home_score,
            "away_score": away_score,
            "minute": minute,
        }
        self.histories.setdefault(match_id, {})[str(minute)] = dict(minute_block)

    def load_history(self, match_id: str) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self.histories.get(match_id, {}).items()}


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
        status_short: str | None,
        home_score: int,
        away_score: int,
        minute: int,
        minute_block: dict[str, Any],
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
            status_short=status_short,
            home_score=home_score,
            away_score=away_score,
            minute=minute,
            minute_block=minute_block,
        )

    def load_history(self, match_id: str) -> dict[str, dict[str, Any]]:
        from kalchas_db.matches import load_match_history_sync

        return load_match_history_sync(self.dsn, match_id)


def default_persist() -> MatchPersist:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if dsn:
        logger.info("match persist: postgres")
        return PostgresMatchPersist(dsn=dsn)
    logger.info("match persist: null (set DATABASE_URL to persist minutes)")
    return NullMatchPersist()
