"""APIFootball.com client (apiv3.apifootball.com).

Kalchas has always used this provider — not RapidAPI API-Football.
Auth is ``APIkey`` query param; endpoints are ``action=get_events`` /
``action=get_statistics``. Free tier is ~180 calls/hour/endpoint
(England Championship + France Ligue 2 on the current free plan).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("kalchas.football")

DEFAULT_BASE_URL = "https://apiv3.apifootball.com/"
# Free plan advertises 180 calls/hour/endpoint; stay under that by default.
DEFAULT_REQUESTS_PER_HOUR = 180


@dataclass
class RateLimiter:
    """Sliding-window limiter (requests per hour)."""

    requests_per_hour: int = DEFAULT_REQUESTS_PER_HOUR
    _times: list[float] = field(default_factory=list)

    def wait(self) -> None:
        now = time.monotonic()
        self._times = [t for t in self._times if now - t < 3600]
        if len(self._times) >= self.requests_per_hour:
            sleep_for = 3600 - (now - min(self._times)) + 0.05
            if sleep_for > 0:
                logger.warning("rate limit: sleeping %.1fs", sleep_for)
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


def _coerce_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip().replace("%", "")
    if not text or text.lower() in {"none", "null", "-"}:
        return default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _parse_elapsed(match_status: Any) -> tuple[int, str]:
    """Return (elapsed_minute, status_short) from apifootball match_status."""
    status = str(match_status or "").strip()
    mapping = {
        "Finished": "FT",
        "After ET": "AET",
        "After Pen.": "PEN",
        "Half Time": "HT",
        "Postponed": "PST",
        "Cancelled": "CANC",
        "Awarded": "AWD",
    }
    if status in mapping:
        return 0, mapping[status]
    if status.isdigit():
        elapsed = int(status)
        return elapsed, "1H" if elapsed <= 45 else "2H" if elapsed <= 90 else "ET"
    if "'" in status:
        try:
            elapsed = int(status.split("'")[0])
            return elapsed, "1H" if elapsed <= 45 else "2H" if elapsed <= 90 else "ET"
        except ValueError:
            return 0, status or "UNK"
    if "+" in status:
        try:
            parts = status.split("+")
            base = int(parts[0].strip())
            added = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 0
            elapsed = base + added
            short = "1H" if base <= 45 else "2H" if base <= 90 else "ET"
            return elapsed, short
        except ValueError:
            return 0, status or "UNK"
    return 0, status or "UNK"


def live_match_from_event(row: dict[str, Any]) -> LiveMatch | None:
    match_id = str(row.get("match_id") or "")
    if not match_id:
        return None
    elapsed, status_short = _parse_elapsed(row.get("match_status"))
    return LiveMatch(
        match_id=match_id,
        home_team=str(row.get("match_hometeam_name") or ""),
        away_team=str(row.get("match_awayteam_name") or ""),
        home_team_id=_coerce_int(row.get("match_hometeam_id")),
        away_team_id=_coerce_int(row.get("match_awayteam_id")),
        minute=elapsed,
        home_score=_coerce_int(row.get("match_hometeam_score")),
        away_score=_coerce_int(row.get("match_awayteam_score")),
        status_short=status_short,
        league_name=str(row.get("league_name") or ""),
        raw=row,
    )


def statistics_to_team_dict(raw_stats: list[dict[str, Any]]) -> dict[str, Any]:
    """Map apifootball statistics[] into the home_team/away_team shape core parses."""
    home: dict[str, Any] = {}
    away: dict[str, Any] = {}
    aliases = {
        "on_target": "on_target",
        "shots_on_goal": "on_target",
        "shots_on_target": "on_target",
        "off_target": "off_target",
        "shots_off_goal": "off_target",
        "shots_off_target": "off_target",
        "corner_kicks": "corners",
        "corners": "corners",
        "attacks": "attacks",
        "dangerous_attacks": "dangerous_attacks",
        "ball_possession": "ball_possession",
    }
    for stat in raw_stats or []:
        key = str(stat.get("type") or "").lower().replace(" ", "_")
        mapped = aliases.get(key)
        if not mapped:
            continue
        home[mapped] = _coerce_int(stat.get("home"))
        away[mapped] = _coerce_int(stat.get("away"))
    return {"home_team": home, "away_team": away}


class FootballAPIClient:
    """Thin httpx client for apiv3.apifootball.com."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        requests_per_hour: int | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = (
            api_key or os.environ.get("API_FOOTBALL_KEY") or os.environ.get("FOOTBALL_API_KEY", "")
        )
        if not self.api_key:
            raise ValueError("API_FOOTBALL_KEY (or FOOTBALL_API_KEY) is required")
        self.base_url = (base_url or os.environ.get("FOOTBALL_API_BASE") or DEFAULT_BASE_URL).rstrip(
            "/"
        ) + "/"
        per_hour = requests_per_hour
        if per_hour is None:
            per_hour = int(os.environ.get("FOOTBALL_REQUESTS_PER_HOUR") or DEFAULT_REQUESTS_PER_HOUR)
        self.limiter = RateLimiter(requests_per_hour=per_hour)
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "User-Agent": "Kalchas-3.0",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FootballAPIClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get(self, action: str, params: dict[str, Any] | None = None) -> Any:
        self.limiter.wait()
        query = {"action": action, "APIkey": self.api_key}
        if params:
            query.update(params)
        response = self._client.get("", params=query)
        if response.status_code == 403:
            raise PermissionError("apifootball.com returned 403 — check API_FOOTBALL_KEY")
        response.raise_for_status()
        data = response.json()
        # Error payloads are objects with an error field, not a match list.
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"apifootball.com error: {data.get('message') or data}")
        return data

    def get_live_fixtures(self) -> list[LiveMatch]:
        """Live matches via ``action=get_events&match_live=1``.

        apifootball sometimes still returns freshly finished rows under
        ``match_live=1``; drop terminal statuses so the scanner does not
        treat them as in-play.
        """
        data = self._get("get_events", {"match_live": "1"})
        rows = data if isinstance(data, list) else []
        finished = {"FT", "AET", "PEN", "CANC", "PST", "AWD"}
        out: list[LiveMatch] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            match = live_match_from_event(row)
            if match is None:
                continue
            if match.status_short in finished:
                continue
            status_long = str(row.get("match_status") or "").strip().lower()
            if status_long in {"finished", "after et", "after pen.", "postponed", "cancelled"}:
                continue
            out.append(match)
        return out

    def get_fixture_statistics(self, match_id: str | int) -> dict[str, Any]:
        """``action=get_statistics`` → ``{home_team, away_team}`` for core parse."""
        mid = str(match_id)
        data = self._get("get_statistics", {"match_id": mid})
        block: Any = {}
        if isinstance(data, dict):
            block = data.get(mid) or data.get(int(mid) if mid.isdigit() else mid) or {}
            if not block and "statistics" in data:
                block = data
        elif isinstance(data, list) and data:
            # Some responses wrap oddly; tolerate a single-element list of dicts.
            first = data[0]
            if isinstance(first, dict):
                block = first.get(mid) or first
        stats = block.get("statistics") if isinstance(block, dict) else None
        if not isinstance(stats, list):
            return {"home_team": {}, "away_team": {}, "match_id": mid}
        processed = statistics_to_team_dict(stats)
        processed["match_id"] = mid
        return processed

    def get_fixture_events(self, match_id: str | int) -> dict[str, Any]:
        """``action=get_events&match_id=`` — raw match row (goalscorer + cards)."""
        data = self._get("get_events", {"match_id": str(match_id)})
        if isinstance(data, list) and data:
            first = data[0]
            return first if isinstance(first, dict) else {}
        if isinstance(data, dict) and "match_id" in data:
            return data
        return {}
