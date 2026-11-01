"""Admin recap review: nothing is approved without a lesson, and only drafts are editable."""

from __future__ import annotations

from datetime import UTC, date, datetime

import kalchas_db.recaps
import pytest
from fastapi.testclient import TestClient
from kalchas_api.app import app
from kalchas_core.recap import build_recap

WEEK = date(2026, 10, 26)


def _row(status: str = "draft", lesson: str = "", x: str = "Short.") -> dict:
    alert = {
        "match_id": "m",
        "minute": 70,
        "strategy_key": "delta_goal",
        "team": "home",
        "value": 1.4,
        "home_team": "Home",
        "away_team": "Away",
        "created_at": datetime(2026, 10, 27, 20, tzinfo=UTC),
        "payload": {"league": "Cup", "possession": {"home": 30, "away": 70}},
        "state": "Expired",
        "detail": {},
    }
    data = build_recap([alert], week_start=WEEK)
    texts = {**data.pop("texts"), "lesson": lesson, "x": x}
    return {
        "week_start": WEEK,
        "status": status,
        "data": data,
        "texts": texts,
        "channels": {"x": True, "telegram_free": True, "telegram_paid": True, "discord": True},
        "post_log": {},
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    c = TestClient(app)
    c.post("/api/admin/login", json={"password": "s3cret"})
    return c


def _store(monkeypatch: pytest.MonkeyPatch, row: dict) -> dict:
    state = {"row": row, "status_calls": []}
    monkeypatch.setattr(kalchas_db.recaps, "get_recap_sync", lambda dsn, week=None: state["row"])
    monkeypatch.setattr(
        kalchas_db.recaps,
        "list_recaps_sync",
        lambda dsn, limit=8: [{"week_start": WEEK, "status": state["row"]["status"]}],
    )

    def set_status(dsn, week, status, *, allowed):
        state["status_calls"].append((status, allowed))
        if state["row"]["status"] not in allowed:
            return False
        state["row"] = {**state["row"], "status": status}
        return True

    monkeypatch.setattr(kalchas_db.recaps, "set_status_sync", set_status)
    return state


def test_recap_requires_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    assert TestClient(app).get("/api/admin/recap").status_code == 401


def test_get_shows_draft_with_notes_and_limits(client: TestClient, monkeypatch) -> None:
    _store(monkeypatch, _row())
    body = client.get("/api/admin/recap").json()
    recap = body["recap"]
    assert recap["status"] == "draft" and recap["editable"] is True
    assert recap["headline"] == "0 of 1 signals found a goal"
    assert any("30%" in note for note in recap["notes"])
    assert recap["limits"]["x"] == {"used": 6, "max": 280}
    assert recap["deadline"].startswith("2026-11-03T12:00")


def test_approve_needs_a_lesson(client: TestClient, monkeypatch) -> None:
    state = _store(monkeypatch, _row(lesson=""))
    res = client.post("/api/admin/recap/2026-10-26/approve")
    assert res.status_code == 422 and "learned" in res.json()["detail"]
    assert state["status_calls"] == []


def test_approve_rejects_an_overlong_tweet(client: TestClient, monkeypatch) -> None:
    _store(monkeypatch, _row(lesson="Fine.", x="x" * 281))
    res = client.post("/api/admin/recap/2026-10-26/approve")
    assert res.status_code == 422 and "x text" in res.json()["detail"]


def test_approve_moves_a_draft_to_approved(client: TestClient, monkeypatch) -> None:
    state = _store(monkeypatch, _row(lesson="Cup form misleads."))
    res = client.post("/api/admin/recap/2026-10-26/approve")
    assert res.status_code == 200
    assert res.json()["recap"]["status"] == "approved"
    assert state["status_calls"] == [("approved", ["draft", "failed"])]


def test_posted_recap_cannot_be_approved_again(client: TestClient, monkeypatch) -> None:
    _store(monkeypatch, _row(status="posted", lesson="x"))
    assert client.post("/api/admin/recap/2026-10-26/approve").status_code == 409


def test_edit_refused_once_approved(client: TestClient, monkeypatch) -> None:
    _store(monkeypatch, _row(status="approved"))
    monkeypatch.setattr(kalchas_db.recaps, "update_texts_sync", lambda *a, **k: False)
    res = client.put("/api/admin/recap/2026-10-26", json={"texts": {"lesson": "late"}})
    assert res.status_code == 409


def test_week_must_be_a_monday(client: TestClient, monkeypatch) -> None:
    _store(monkeypatch, _row())
    assert client.post("/api/admin/recap/2026-10-27/approve").status_code == 400


def test_preview_returns_the_card_png(client: TestClient, monkeypatch) -> None:
    row = _row()
    _store(monkeypatch, row)
    res = client.post(
        "/api/admin/recap/2026-10-26/preview/2",
        json={"texts": {**row["texts"], "lesson": "Typed but not saved."}},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert (
        client.post("/api/admin/recap/2026-10-26/preview/9", json={"texts": {}}).status_code == 404
    )


def test_draft_now_builds_last_week(client: TestClient, monkeypatch) -> None:
    import kalchas_db.settings

    saved = {}
    _store(monkeypatch, _row())
    monkeypatch.setattr(kalchas_db.recaps, "fetch_week_signals_sync", lambda dsn, a, b: [])
    monkeypatch.setattr(kalchas_db.settings, "list_thresholds", lambda dsn: {})

    def save(dsn, week, data, texts):
        saved.update(week=week, texts=texts)
        return True

    monkeypatch.setattr(kalchas_db.recaps, "save_draft_sync", save)
    res = client.post("/api/admin/recap/draft?week=2026-10-26")
    assert res.status_code == 200
    assert saved["week"] == WEEK and saved["texts"]["lesson"] == ""
