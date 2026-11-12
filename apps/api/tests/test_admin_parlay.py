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


def pages(n: int = 7) -> list[dict[str, Any]]:
    return [page(str(i), f"2026-11-07T1{i}:00:00+03:00") for i in range(1, n + 1)]


def refs(day: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    by = {leg["match_id"]: leg for leg in day["legs"]}
    return [{"match_id": i, "market": by[i]["market"], "price": by[i]["price"]} for i in ids]


def test_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    assert TestClient(app).get("/api/admin/parlay/day").status_code == 401


def test_day_is_the_public_payload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages())
    from kalchas_core.watchlist.parlay import build

    body = client.get("/api/admin/parlay/day?slot=today").json()
    public = build(pages())  # what GET /api/watchlist/parlay/{day} serves
    assert body["status"] == "ready"
    assert body["order"] == public["order"]
    assert [leg["match_id"] for leg in body["legs"]] == [leg["match_id"] for leg in public["legs"]]


def test_nightly_keeps_early_kickoffs_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    early = [page(str(i), f"2026-11-08T0{i}:00:00+03:00") for i in range(1, 5)]
    late = [page("9", "2026-11-08T18:00:00+03:00")]
    monkeypatch.setattr(
        "kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: early + late
    )
    monkeypatch.setattr(admin_parlay, "slot_day", lambda slot, today: datetime(2026, 11, 8).date())
    body = client.get("/api/admin/parlay/day?slot=nightly").json()
    assert {leg["match_id"] for leg in body["legs"]} == {"1", "2", "3", "4"}
    assert "9" not in body["order"]["balanced"]
    assert body["window_label"] == "00:00–07:00 GMT+3"


def test_preview_renders_exactly_the_legs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages())
    day = client.get("/api/admin/parlay/day").json()
    res = client.post(
        "/api/admin/parlay/preview", json={"slot": "today", "legs": refs(day, ["1", "4", "6"])}
    )
    assert res.status_code == 200
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_too_few_legs_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages())
    day = client.get("/api/admin/parlay/day").json()
    res = client.post(
        "/api/admin/parlay/preview", json={"slot": "today", "legs": refs(day, ["1", "2"])}
    )
    assert res.status_code == 422


def test_a_moved_price_blocks_saving(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages())
    day = client.get("/api/admin/parlay/day").json()
    legs = refs(day, ["1", "2", "3"])
    legs[1]["price"] = 9.99
    saved: list[Any] = []
    monkeypatch.setattr("kalchas_db.parlay_slips.insert_slip_sync", lambda *a, **k: saved.append(k))
    res = client.post(
        "/api/admin/parlay/slips",
        json={"slot": "today", "legs": legs, "channels": {"x": True}},
    )
    assert res.status_code == 409
    assert "9.99" in res.json()["detail"]["changes"][0]
    assert saved == []


def test_save_keeps_the_slip_as_seen(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages())
    day = client.get("/api/admin/parlay/day").json()
    got: dict[str, Any] = {}

    def insert(dsn: str, **kw: Any) -> dict[str, Any]:
        got.update(kw)
        return {"id": 7, "status": "approved", "outcomes": {}, **kw}

    monkeypatch.setattr("kalchas_db.parlay_slips.insert_slip_sync", insert)
    res = client.post(
        "/api/admin/parlay/slips",
        json={
            "slot": "today",
            "style": "bolder",
            "legs": refs(day, ["5", "2", "3"]),
            "channels": {"x": True, "telegram_free": True, "bogus": True},
            "autopost": False,
        },
    )
    assert res.status_code == 200
    assert [leg["match_id"] for leg in got["legs"]] == ["2", "3", "5"]  # kick-off order
    assert got["channels"] == {
        "x": True,
        "telegram_free": True,
        "telegram_paid": False,
        "discord_free": False,
        "discord_paid": False,
    }
    assert got["autopost"] is False
    assert "riskier slip" in got["caption"]
    assert res.json()["verdict"]["done"] is False


def test_save_needs_a_channel(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages())
    day = client.get("/api/admin/parlay/day").json()
    res = client.post(
        "/api/admin/parlay/slips", json={"legs": refs(day, ["1", "2", "3"]), "channels": {}}
    )
    assert res.status_code == 422


def test_decide_only_answers_an_open_question(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = {
        "id": 3,
        "day": "2026-11-07",
        "slot": "today",
        "style": "balanced",
        "status": "needs_decision",
        "legs": [{"match_id": "1", "price": 1.5}, {"match_id": "2", "price": 1.6}],
        "outcomes": {"1": {"outcome": "landed"}, "2": {"state": "off", "note": "Postponed"}},
    }
    monkeypatch.setattr("kalchas_db.parlay_slips.get_slip_sync", lambda dsn, i: row)
    calls: list[Any] = []
    monkeypatch.setattr(
        "kalchas_db.parlay_slips.decide_leg_sync",
        lambda dsn, i, mid, out, by: calls.append((mid, out)) or row,
    )
    bad = client.post(
        "/api/admin/parlay/slips/3/decide", json={"match_id": "2", "outcome": "landed"}
    )
    assert bad.status_code == 409
    ok = client.post("/api/admin/parlay/slips/3/decide", json={"match_id": "2", "outcome": "void"})
    assert ok.status_code == 200
    assert calls == [("2", "void")]


def test_evaluate_sends_unused_legs_in_style_order(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("kalchas_db.watchlist.load_watchlist_matches_on", lambda dsn, day: pages())
    day = client.get("/api/admin/parlay/day").json()
    seen: dict[str, Any] = {}

    def fake(**kw: Any) -> dict[str, Any]:
        seen.update(kw)
        return {"ok": True, "advice": "fine", "suggestions": []}

    monkeypatch.setattr("kalchas_api.parlay_claude.evaluate", fake)
    res = client.post("/api/admin/parlay/evaluate", json={"legs": refs(day, ["1", "2", "3"])})
    assert res.status_code == 200
    assert {leg["match_id"] for leg in seen["unused"]} == {"4", "5", "6", "7"}
    assert len(seen["selected"]) == 3


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


def test_claude_ignores_thinking_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from kalchas_api import parlay_claude

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "claude-sonnet-x",
                "stop_reason": "end_turn",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "abc"},
                    {"type": "text", "text": "Weakest: leg 3"},
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        out = parlay_claude.evaluate(
            slot="today", style="balanced", day="2026-11-07", selected=[], unused=[], client=http
        )
    assert out["ok"] is True
    assert out["advice"] == "Weakest: leg 3"
    assert out["suggestions"] == []


def test_split_suggestions_keeps_only_valid_actions() -> None:
    from kalchas_api.parlay_claude import split_suggestions

    selected = [page("1", "2026-11-07T14:00:00+03:00") | {"label": "BTTS No", "price": 1.9}]
    unused = [page("9", "2026-11-07T22:30:00+03:00") | {"label": "Over 2.5", "price": 1.67}]
    text = (
        "1) Weakest leg: Home1 v Away1.\n\n"
        "```json\n"
        '{"suggestions": ['
        '{"remove": "1", "add": "9", "why": "better hit rate"},'
        '{"remove": "404", "add": null, "why": "made up"},'
        '{"remove": null, "add": "9", "why": "extra"}'
        "]}\n```"
    )
    prose, out = split_suggestions(text, selected, unused)
    assert prose == "1) Weakest leg: Home1 v Away1."
    assert [s["kind"] for s in out] == ["swap", "add"]
    assert out[0]["remove_label"] == "Home1 v Away1 · BTTS No 1.90"
    assert out[0]["add_label"] == "Home9 v Away9 · Over 2.5 1.67"


def test_retry_one_channel(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, str]] = []

    def retry(dsn: str, slip_id: int, channel: str) -> bool:
        calls.append((slip_id, channel))
        return channel == "x"

    monkeypatch.setattr("kalchas_db.parlay_slips.retry_channel_sync", retry)
    monkeypatch.setattr(
        "kalchas_db.parlay_slips.get_slip_sync",
        lambda dsn, i: {"id": i, "legs": [], "outcomes": {}, "status": "approved"},
    )
    assert client.post("/api/admin/parlay/slips/2/retry/x").status_code == 200
    assert client.post("/api/admin/parlay/slips/2/retry/telegram_paid").status_code == 409
    assert client.post("/api/admin/parlay/slips/2/retry/myspace").status_code == 422
    assert calls == [(2, "x"), (2, "telegram_paid")]
