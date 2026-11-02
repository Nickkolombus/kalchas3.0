"""Watchlist API: reads what the scanner built, never the provider."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from kalchas_api import watchlist
from kalchas_api.app import app

DAY = {
    "day": "2026-11-03",
    "built_at": "2026-11-02T20:00:00+00:00",
    "timezone": "+03:00",
    "partial": False,
    "matches": [
        {
            "match_id": "100",
            "kickoff": "2026-11-03T22:45:00+03:00",
            "league_key": "153:Championship",
            "home": {"name": "Norwich", "badge": None, "position": 4},
            "away": {"name": "Hull", "badge": None, "position": 17},
            "odds": {"home": 1.95, "draw": 3.6, "away": 3.9},
            "watch": "strong",
            "score": 0.6,
            "headline": "Both teams to score looks likely.",
            "reason": "Both teams scored in 8 of 10 and 7 of 10 of their last games.",
            "tags": ["Both score"],
        }
    ],
    "leagues": [
        {
            "key": "153:Championship",
            "name": "Championship",
            "country": "England",
            "logo": None,
            "record": {"confirmed": 38, "settled": 57},
            "match_ids": ["100"],
        }
    ],
    "shortlist": ["100"],
    "overall_record": {"confirmed": 500, "settled": 860},
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    return TestClient(app)


def test_resolve_day_uses_the_board_time_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOOTBALL_TIMEZONE", "+03:00")
    late = datetime(2026, 11, 2, 22, 30, tzinfo=UTC)  # already 3 Nov in +03:00
    assert watchlist.resolve_day("today", late) == "2026-11-03"
    assert watchlist.resolve_day("tomorrow", late) == "2026-11-04"


def test_day_list_is_served_from_the_cache(client: TestClient, monkeypatch) -> None:
    seen: list[str] = []

    def load(dsn: str, key: str, **_: object) -> dict | None:
        seen.append(key)
        return DAY

    monkeypatch.setattr("kalchas_db.panel_cache.load_panel_cache", load)
    monkeypatch.setattr(watchlist, "resolve_day", lambda day: "2026-11-03")
    body = client.get("/api/watchlist/day/tomorrow").json()
    assert seen == ["watchlist_day_2026-11-03"]
    assert body["status"] == "ready"
    assert body["matches"][0]["headline"].startswith("Both teams")


def test_our_hit_rates_are_never_served(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("kalchas_db.panel_cache.load_panel_cache", lambda *a, **k: DAY)
    body = client.get("/api/watchlist/day/tomorrow").json()
    assert "overall_record" not in body
    assert "record" not in body["leagues"][0]


def test_day_not_built_yet_says_preparing(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("kalchas_db.panel_cache.load_panel_cache", lambda *a, **k: None)
    body = client.get("/api/watchlist/day/today").json()
    assert body["status"] == "preparing"
    assert body["matches"] == []


def test_unknown_day_and_match(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("kalchas_db.panel_cache.load_panel_cache", lambda *a, **k: None)
    assert client.get("/api/watchlist/day/yesterday").status_code == 404
    assert client.get("/api/watchlist/match/100").status_code == 404
    assert client.get("/api/watchlist/match/abc").status_code == 404
