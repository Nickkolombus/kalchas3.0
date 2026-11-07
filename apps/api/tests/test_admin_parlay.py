"""Admin parlay compose and thermal slip preview."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kalchas_api import admin_parlay, watchlist
from kalchas_api.app import app


def page(match_id: str, kickoff: str, watch: str = "strong") -> dict[str, Any]:
    return {
        "match_id": match_id,
        "kickoff": kickoff,
        "league": {"id": 1, "name": "Liga", "country": "AR", "round": ""},
        "home": {"id": 1, "name": f"Home{match_id}", "badge": None, "position": 1},
        "away": {"id": 2, "name": f"Away{match_id}", "badge": None, "position": 4},
        "watch": watch,
        "score": 0.6,
        "odds": {"home": 1.5, "draw": 4.2, "away": 6.0, "over_2_5": 1.45, "btts_yes": 1.6},
        "patterns": [
            {
                "key": "over_2_5",
                "tag": "Over 2.5",
                "title": "Expect goals.",
                "detail": "",
                "brief": "Over 2.5 in recent games.",
                "score": 0.5,
            }
        ],
        "pattern_table": [
            {"key": "over_2_5", "home": {"count": 8, "n": 10}, "away": {"count": 7, "n": 10}},
        ],
        "form": {"home": {"games": 10, "wins": 7}, "away": {"games": 10, "wins": 3}},
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(watchlist, "board_today", lambda now=None: datetime(2026, 11, 7).date())
    watchlist._parlays.clear()
    c = TestClient(app)
    c.post("/api/admin/login", json={"password": "s3cret"})
    return c


def test_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    assert TestClient(app).get("/api/admin/parlay").status_code == 401


def test_compose_today_and_exclude(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        page("1", "2026-11-07T14:00:00+03:00"),
        page("2", "2026-11-07T15:00:00+03:00"),
        page("3", "2026-11-07T16:00:00+03:00"),
        page("4", "2026-11-07T17:00:00+03:00"),
    ]
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages)
    body = client.get("/api/admin/parlay?slot=today&style=balanced").json()
    assert body["status"] == "ready"
    assert body["day"] == "2026-11-07"
    assert body["stake"] == 10
    assert body["window_label"] is None
    assert len(body["selected"]) >= 3

    trimmed = client.get("/api/admin/parlay?slot=today&style=balanced&exclude=2").json()
    assert "2" not in [leg["match_id"] for leg in trimmed["selected"]]


def test_nightly_filters_early_kickoffs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date, timedelta

    pages = [
        page("n1", "2026-11-08T02:00:00+03:00"),
        page("n2", "2026-11-08T03:30:00+03:00"),
        page("n3", "2026-11-08T04:00:00+03:00"),
        page("day", "2026-11-08T15:00:00+03:00"),
    ]
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages)

    def fake_slot(slot: str, today: date, now=None) -> date:
        if slot == "nightly":
            return date(2026, 11, 8)
        if slot == "tomorrow":
            return today + timedelta(days=1)
        return today

    monkeypatch.setattr(admin_parlay, "slot_day", fake_slot)
    body = client.get("/api/admin/parlay?slot=nightly&style=balanced").json()
    assert body["window_label"] == "00:00–07:00 GMT+3"
    ids = [leg["match_id"] for leg in body["legs"]]
    assert ids == ["n1", "n2", "n3"]
    assert "day" not in ids


def test_preview_returns_png(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        page("1", "2026-11-07T14:00:00+03:00"),
        page("2", "2026-11-07T15:00:00+03:00"),
        page("3", "2026-11-07T16:00:00+03:00"),
    ]
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages)
    res = client.post(
        "/api/admin/parlay/preview",
        json={"slot": "today", "style": "balanced", "match_ids": ["1", "2", "3"]},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_rejects_too_few_legs(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [page("1", "2026-11-07T14:00:00+03:00"), page("2", "2026-11-07T15:00:00+03:00")]
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages)
    res = client.post(
        "/api/admin/parlay/preview",
        json={"slot": "today", "style": "balanced", "match_ids": ["1", "2"]},
    )
    assert res.status_code == 422
