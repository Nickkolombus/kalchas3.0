"""Parlay API: the day's legs from the match pages, cached for a minute."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kalchas_api import watchlist
from kalchas_api.app import app


def page(match_id: str, watch: str = "strong", key: str = "over_2_5") -> dict[str, Any]:
    return {
        "match_id": match_id,
        "kickoff": "2026-11-03T21:00:00+03:00",
        "league": {"id": 1, "name": "Eredivisie", "country": "Netherlands", "round": ""},
        "home": {"id": 1, "name": "Ajax", "badge": None, "position": 1},
        "away": {"id": 2, "name": "Twente", "badge": None, "position": 4},
        "watch": watch,
        "score": 0.6,
        "odds": {"home": 1.5, "draw": 4.2, "away": 6.0, "over_2_5": 1.45, "btts_yes": 1.6},
        "patterns": [
            {
                "key": key,
                "tag": "Over 2.5",
                "title": "Expect goals.",
                "detail": "",
                "brief": "Over 2.5 goals in 8 of 10 and 7 of 10 of their last games.",
                "score": 0.5,
                "outcome": "landed",
                "outcome_note": "4 goals.",
            }
        ],
        "pattern_table": [
            {"key": "over_2_5", "home": {"count": 8, "n": 10}, "away": {"count": 7, "n": 10}},
        ],
        "form": {"home": {"games": 10, "wins": 7}, "away": {"games": 10, "wins": 3}},
        "result": {
            "status": "finished",
            "label": "FT",
            "home": 3,
            "away": 1,
            "home_90": 3,
            "away_90": 1,
        },
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr("kalchas_db.watchlist.first_watchlist_day", lambda dsn: "2026-11-02")
    monkeypatch.setattr(watchlist, "board_today", lambda now=None: datetime(2026, 11, 3).date())
    watchlist._parlays.clear()
    return TestClient(app)


def test_parlay_serves_legs_and_orders(client: TestClient, monkeypatch) -> None:
    pages = [page("100"), page("101", watch="look"), page("102", key="late_goal")]
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages)
    body = client.get("/api/watchlist/parlay/today").json()
    assert body["status"] == "ready" and body["day"] == "2026-11-03"
    assert [leg["match_id"] for leg in body["legs"]] == ["100", "101"]
    leg = body["legs"][0]
    assert (leg["label"], leg["price"], leg["hit"], leg["n"]) == ("Over 2.5 goals", 1.45, 15, 20)
    assert (leg["outcome"], leg["result"]["home"]) == ("landed", 3)
    assert body["order"]["balanced"] == ["100", "101"]
    assert body["unpriced"] == [
        {"match_id": "102", "home": "Ajax", "away": "Twente", "tags": ["Over 2.5"]}
    ]


def test_parlay_is_built_once_a_minute_per_day(client: TestClient, monkeypatch) -> None:
    calls: list[str] = []

    def load(dsn: str, day: str) -> list[dict]:
        calls.append(day)
        return [page("100")]

    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", load)
    client.get("/api/watchlist/parlay/today")
    client.get("/api/watchlist/parlay/2026-11-03")
    assert calls == ["2026-11-03"]


def test_parlay_missing_days_and_bad_days(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda *a: [])
    assert client.get("/api/watchlist/parlay/tomorrow").json()["status"] == "preparing"
    assert client.get("/api/watchlist/parlay/2026-10-01").json()["status"] == "none"
    assert client.get("/api/watchlist/parlay/yesterday").status_code == 404
