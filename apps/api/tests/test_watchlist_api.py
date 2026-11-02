"""Watchlist API: reads the archive the scanner writes, never the provider."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
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
            "tags": [{"label": "Both score", "outcome": "landed"}],
            "result": {"status": "finished", "label": "FT", "home": 2, "away": 1, "pens": None},
            "outcome": "landed",
            "outcome_note": "Both teams scored.",
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
    "summary": {
        "matches": 1,
        "strong": 1,
        "look": 0,
        "finished": 1,
        "called_off": 0,
        "top": {"landed": 1, "settled": 1},
        "strong_tally": {"landed": 1, "settled": 1},
        "look_tally": {"landed": 0, "settled": 0},
    },
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr("kalchas_db.watchlist.first_watchlist_day", lambda dsn: "2026-11-02")
    monkeypatch.setattr(watchlist, "board_today", lambda now=None: datetime(2026, 11, 3).date())
    return TestClient(app)


def test_resolve_day_uses_the_board_time_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOOTBALL_TIMEZONE", "+03:00")
    late = datetime(2026, 11, 2, 22, 30, tzinfo=UTC)  # already 3 Nov in +03:00
    assert watchlist.resolve_day("today", late) == "2026-11-03"
    assert watchlist.resolve_day("tomorrow", late) == "2026-11-04"
    assert watchlist.resolve_day("2026-10-20", late) == "2026-10-20"
    for bad in ("2026-11-05", "yesterday", "2026-13-01"):
        with pytest.raises(HTTPException):
            watchlist.resolve_day(bad, late)


def test_day_list_is_served_from_the_archive(client: TestClient, monkeypatch) -> None:
    seen: list[str] = []

    def load(dsn: str, day: str) -> dict | None:
        seen.append(day)
        return DAY

    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_day", load)
    body = client.get("/api/watchlist/day/2026-11-03").json()
    assert seen == ["2026-11-03"]
    assert body["status"] == "ready"
    assert body["today"] == "2026-11-03" and body["first_day"] == "2026-11-02"
    row = body["matches"][0]
    assert row["result"]["home"] == 2 and row["outcome"] == "landed"
    assert body["summary"]["top"] == {"landed": 1, "settled": 1}


def test_our_hit_rates_are_never_served(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_day", lambda *a: DAY)
    body = client.get("/api/watchlist/day/tomorrow").json()
    assert "overall_record" not in body
    assert "record" not in body["leagues"][0]


def test_missing_days_say_preparing_or_none(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_day", lambda *a: None)
    assert client.get("/api/watchlist/day/today").json()["status"] == "preparing"
    assert client.get("/api/watchlist/day/2026-10-01").json()["status"] == "none"


def test_month_lists_each_day_with_its_tally(client: TestClient, monkeypatch) -> None:
    captured: list[tuple] = []

    def month(dsn: str, start, end) -> list[dict]:
        captured.append((start.isoformat(), end.isoformat()))
        return [{"day": "2026-11-03", "summary": DAY["summary"]}]

    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_month", month)
    body = client.get("/api/watchlist/month/2026-12").json()
    assert captured == [("2026-12-01", "2027-01-01")]
    assert body["days"][0]["summary"]["strong"] == 1
    assert client.get("/api/watchlist/month/2026-13").status_code == 404


def test_unknown_day_and_match(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_match", lambda *a: None)
    assert client.get("/api/watchlist/day/yesterday").status_code == 404
    assert client.get("/api/watchlist/match/100").status_code == 404
    assert client.get("/api/watchlist/match/abc").status_code == 404


def test_picks_lists_strong_watches_and_the_next_to_kick_off(
    client: TestClient, monkeypatch
) -> None:
    later = {
        **DAY["matches"][0],
        "match_id": "101",
        "kickoff": "2099-01-01T20:00:00+03:00",
        "result": None,
    }
    sooner = {**later, "match_id": "102", "kickoff": "2098-01-01T20:00:00+03:00"}
    quiet = {**later, "match_id": "103", "watch": "quiet"}
    played = {**DAY["matches"][0], "kickoff": "2020-01-01T20:00:00+03:00"}
    today = {**DAY, "matches": [played, later, sooner, quiet]}
    monkeypatch.setattr(
        "kalchas_db.watchlist.load_watchlist_day",
        lambda dsn, day: today if day == "2026-11-03" else None,
    )
    body = client.get("/api/watchlist/picks").json()
    assert [p["match_id"] for p in body["picks"]] == ["100", "101", "102"]
    assert body["next"]["match_id"] == "102"
    assert body["picks"][0]["tag"] == "Both score"
    assert body["picks"][0]["outcome"] == "landed"
