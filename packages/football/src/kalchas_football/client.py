"""API-Football client (RapidAPI)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class RateLimiter:
    requests_per_minute: int = 450
    _times: list[float] = field(default_factory=list)

    def wait(self) -> None:
        now = time.monotonic()
        self._times = [t for t in self._times if now - t < 60]
        if len(self._times) >= self.requests_per_minute:
            sleep_for = 60 - (now - min(self._times))
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._times.append(time.monotonic())


@dataclass
class LiveMatch:
    match_id: str
    home_team: str
    away_team: str
    home_team_id: int
    away_team_id: int
    minute: int
    home_score: int
    away_score: int
    status_short: str
    league_name: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class FootballAPIClient:
    """Thin httpx client for API-Football via RapidAPI."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        host: str = "api-football-v1.p.rapidapi.com",
        base_url: str | None = None,
        requests_per_minute: int = 450,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = (
            api_key or os.environ.get("API_FOOTBALL_KEY") or os.environ.get("FOOTBALL_API_KEY", "")
        )
        if not self.api_key:
            raise ValueError("API_FOOTBALL_KEY (or FOOTBALL_API_KEY) is required")
        self.base_url = base_url or f"https://{host}"
        self.host = host
        self.limiter = RateLimiter(requests_per_minute)
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "x-rapidapi-key": self.api_key,
                "x-rapidapi-host": host,
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FootballAPIClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.limiter.wait()
        response = self._client.get(path, params=params or {})
        response.raise_for_status()
        return response.json()

    def get_live_fixtures(self) -> list[LiveMatch]:
        """Live fixtures (status=live)."""
        data = self._get("/v3/fixtures", params={"live": "all"})
        out: list[LiveMatch] = []
        for row in data.get("response") or []:
            fixture = row.get("fixture") or {}
            teams = row.get("teams") or {}
            goals = row.get("goals") or {}
            league = row.get("league") or {}
            status = fixture.get("status") or {}
            home = teams.get("home") or {}
            away = teams.get("away") or {}
            out.append(
                LiveMatch(
                    match_id=str(fixture.get("id") or ""),
                    home_team=str(home.get("name") or ""),
                    away_team=str(away.get("name") or ""),
                    home_team_id=int(home.get("id") or 0),
                    away_team_id=int(away.get("id") or 0),
                    minute=int(status.get("elapsed") or 0),
                    home_score=int(goals.get("home") or 0),
                    away_score=int(goals.get("away") or 0),
                    status_short=str(status.get("short") or ""),
                    league_name=str(league.get("name") or ""),
                    raw=row,
                )
            )
        return out

    def get_fixture_statistics(self, match_id: str | int) -> list[dict[str, Any]]:
        data = self._get("/v3/fixtures/statistics", params={"fixture": match_id})
        return list(data.get("response") or [])

    def get_fixture_events(self, match_id: str | int) -> list[dict[str, Any]]:
        data = self._get("/v3/fixtures/events", params={"fixture": match_id})
        return list(data.get("response") or [])
