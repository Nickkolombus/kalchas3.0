"""Admin parlay compose and thermal slip preview."""

from __future__ import annotations

import json
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


def test_compose_respects_leg_count(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [page(str(i), f"2026-11-07T{14 + i:02d}:00:00+03:00") for i in range(1, 7)]
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages)
    body = client.get("/api/admin/parlay?slot=today&style=balanced&legs=3").json()
    assert body["wanted"] == 3
    assert len(body["selected"]) == 3
    assert "explanation" in body and "balanced" in body["explanation"].lower()


def test_evaluate_calls_claude(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        page("1", "2026-11-07T14:00:00+03:00"),
        page("2", "2026-11-07T15:00:00+03:00"),
        page("3", "2026-11-07T16:00:00+03:00"),
    ]
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "kalchas_api.parlay_claude.evaluate",
        lambda **kw: {"ok": True, "advice": "Weakest: Home1 v Away1", "model": "test"},
    )
    res = client.post(
        "/api/admin/parlay/evaluate",
        json={"slot": "today", "style": "balanced", "match_ids": ["1", "2", "3"]},
    )
    assert res.status_code == 200
    assert "Weakest" in res.json()["advice"]


def test_post_fans_out(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        page("1", "2026-11-07T14:00:00+03:00"),
        page("2", "2026-11-07T15:00:00+03:00"),
        page("3", "2026-11-07T16:00:00+03:00"),
    ]
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages)
    monkeypatch.setattr(
        "kalchas_api.parlay_post.fanout",
        lambda image, **kw: {
            "x": {"ok": True, "ref": "1"},
            "telegram_free": {"ok": True, "ref": "2"},
        },
    )
    monkeypatch.setattr(
        "kalchas_db.discord_settings.get_discord_settings",
        lambda dsn: {
            "free_channel_id": "1",
            "paid_channel_id": "2",
            "free_enabled": True,
            "paid_enabled": True,
        },
    )
    res = client.post(
        "/api/admin/parlay/post",
        json={
            "slot": "today",
            "style": "balanced",
            "match_ids": ["1", "2", "3"],
            "channels": {"x": True, "telegram_free": True},
            "caption": "test",
            "autopost": True,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["post_log"]["x"]["ok"] is True


def test_claude_retries_with_available_model_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from kalchas_api import parlay_claude

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-retired")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, json={"data": [{"id": "claude-opus-x"}, {"id": "claude-sonnet-x"}]}
            )
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "claude-retired":
            return httpx.Response(404, json={"error": {"message": "model: claude-retired"}})
        return httpx.Response(
            200, json={"model": model, "content": [{"type": "text", "text": "Weakest: leg 2"}]}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        out = parlay_claude.evaluate(
            slot="today", style="balanced", day="2026-11-07", selected=[], unused=[], client=http
        )
    assert out["ok"] is True
    assert out["model"] == "claude-sonnet-x"
    assert seen == ["claude-retired", "claude-sonnet-x"]


def test_default_caption_explains_style_and_links_site() -> None:
    composed = {"slot": "today", "style": "bolder"}
    legs = [{"price": 1.5}, {"price": 1.6}, {"price": 1.7}]
    caption = admin_parlay._default_caption(composed, legs)
    assert "riskier slip" in caption
    assert "kalchas.live" in caption
    assert "kalchas.live/parlay" not in caption
    assert "For research & football enthusiast purposes only" in caption
