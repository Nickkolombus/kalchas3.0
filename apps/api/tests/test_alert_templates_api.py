"""Admin > Alert text: load, live preview, save with checks, reset."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from kalchas_api.alert_templates import alert_samples
from kalchas_api.app import app


def _alert(alert_id: int, minute: int, key: str = "delta_5min", **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": alert_id,
        "match_id": "m1",
        "strategy_slot": alert_id,
        "strategy_key": key,
        "team": "home",
        "value": 8.4,
        "minute": minute,
        "score": "0-0",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "payload": {"league": "Premier League"},
        "state": None,
        "detail": None,
    }
    row.update(extra)
    return row


class FakeStore:
    def __init__(self) -> None:
        self.saved: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.deleted: list[tuple[str, str, str]] = []

    def list_templates(self, dsn: str) -> list[dict[str, Any]]:
        return [
            {"strategy": st, "channel": c, "kind": k, **row}
            for (st, c, k), row in self.saved.items()
        ]

    def save_template(
        self, dsn: str, *, strategy: str, channel: str, kind: str, body: str, enabled: bool
    ) -> None:
        self.saved[(strategy, channel, kind)] = {
            "body": body,
            "enabled": enabled,
            "fallback_count": 0,
        }

    def delete_template(self, dsn: str, *, strategy: str, channel: str, kind: str) -> None:
        self.deleted.append((strategy, channel, kind))
        self.saved.pop((strategy, channel, kind), None)

    def recent_alerts(self, dsn: str, limit: int = 60) -> list[dict[str, Any]]:
        return [_alert(2, 30), _alert(1, 30, "rule_of_three"), _alert(3, 12)]

    def recent_goals(self, dsn: str, limit: int = 20) -> list[dict[str, Any]]:
        return [_alert(3, 12, state="Confirmed", detail={"goal_minute": 15})]

    def recent_misses(self, dsn: str, limit: int = 20) -> list[dict[str, Any]]:
        return [_alert(1, 30, "rule_of_three", state="Expired", detail={})]

    def alerts_by_ids(self, dsn: str, ids: list[int]) -> list[dict[str, Any]]:
        rows = {r["id"]: r for r in self.recent_alerts(dsn)}
        return [rows[i] for i in ids if i in rows]


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    for name in (
        "list_templates",
        "save_template",
        "delete_template",
        "recent_alerts",
        "recent_goals",
        "recent_misses",
        "alerts_by_ids",
    ):
        monkeypatch.setattr(f"kalchas_db.alert_templates.{name}", getattr(fake, name))
    return fake


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    from kalchas_api.admin_auth import COOKIE_NAME, mint_token

    test_client = TestClient(app)
    test_client.cookies.set(COOKIE_NAME, mint_token())
    return test_client


def test_needs_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    assert TestClient(app).get("/api/admin/alert-templates").status_code == 401


def test_load_shows_built_in_until_saved(client: TestClient, store: FakeStore) -> None:
    body = client.get("/api/admin/alert-templates").json()
    paid = body["templates"]["default"]["paid"]["alert"]
    assert paid["saved"] is False
    assert paid["body"] == body["defaults"]["paid"]["alert"]
    assert paid["limit"] == 1024
    assert body["templates"]["default"]["discord"]["goal"]["limit"] == 2000
    assert body["templates"]["kscore"]["x"]["alert"]["limit"] == 280
    assert set(body["templates"]["default"]["x"]) == {"alert", "goal", "miss"}
    assert "miss" not in body["templates"]["default"]["paid"]
    assert [s["key"] for s in body["strategies"]] == [
        "default",
        "delta_5min",
        "pressure_index",
        "delta_goal",
        "rule_of_three",
        "kscore",
    ]
    assert any(tag["name"] == "home" for tag in body["tags"])
    # Two alerts on minute 30 are one joint post, led by the 5-minute strategy.
    assert body["samples"]["alert"][0]["ids"] == [2, 1]
    assert body["samples"]["alert"][0]["lead"] == "delta_5min"
    assert body["samples"]["alert"][0]["label"].endswith("(joint post)")
    assert body["samples"]["goal"][0]["ids"] == [3]
    assert body["samples"]["miss"][0]["lead"] == "rule_of_three"


def test_strategy_starts_from_defaults_saved_text(client: TestClient, store: FakeStore) -> None:
    store.saved[("default", "paid", "alert")] = {"body": "D {home}", "enabled": True}
    slot = client.get("/api/admin/alert-templates").json()["templates"]["kscore"]["paid"]["alert"]
    assert slot["saved"] is False
    assert slot["body"] == "D {home}"


def test_preview_uses_the_chosen_alert(client: TestClient, store: FakeStore) -> None:
    res = client.post(
        "/api/admin/alert-templates/preview",
        json={
            "strategy": "default",
            "channel": "free",
            "kind": "alert",
            "body": "**{home}** {strategy_short}",
            "ids": [1, 2],
        },
    )
    out = res.json()
    assert out["example"] is False
    assert out["telegram"].startswith("<b>Arsenal</b> ")
    assert "+" in out["telegram"]
    assert out["x"].startswith("Arsenal ")


def test_preview_without_alerts_uses_the_made_up_one(client: TestClient, store: FakeStore) -> None:
    out = client.post(
        "/api/admin/alert-templates/preview",
        json={"channel": "paid", "kind": "goal", "body": "{goal_line}", "ids": []},
    ).json()
    assert out["example"] is True
    assert out["telegram"].startswith("GOAL at")


def test_save_refuses_a_broken_template(client: TestClient, store: FakeStore) -> None:
    res = client.put(
        "/api/admin/alert-templates/default/paid/alert",
        json={"body": "{nope}", "enabled": True},
    )
    assert res.status_code == 422
    assert "no {nope} tag" in res.json()["problems"][0]
    assert store.saved == {}


def test_save_and_reset(client: TestClient, store: FakeStore) -> None:
    res = client.put(
        "/api/admin/alert-templates/kscore/free/alert",
        json={"body": "{home} vs {away}", "enabled": True},
    )
    assert res.status_code == 200
    assert store.saved[("kscore", "free", "alert")]["body"] == "{home} vs {away}"
    templates = client.get("/api/admin/alert-templates").json()["templates"]
    assert templates["kscore"]["free"]["alert"]["saved"] is True
    assert templates["default"]["free"]["alert"]["saved"] is False
    assert client.delete("/api/admin/alert-templates/kscore/free/alert").status_code == 200
    assert store.deleted == [("kscore", "free", "alert")]


def test_x_saves_long_text_and_miss_is_x_only(client: TestClient, store: FakeStore) -> None:
    long_body = "{versus}\n" + "\n".join(["{strategy_lines}"] * 6)
    res = client.put("/api/admin/alert-templates/delta_5min/x/alert", json={"body": long_body})
    assert res.status_code == 200
    res = client.put("/api/admin/alert-templates/default/paid/miss", json={"body": "x"})
    assert res.status_code == 404


def test_unknown_channel_is_404(client: TestClient, store: FakeStore) -> None:
    res = client.put("/api/admin/alert-templates/default/sms/alert", json={"body": "x"})
    assert res.status_code == 404
    res = client.put("/api/admin/alert-templates/npei/paid/alert", json={"body": "x"})
    assert res.status_code == 404


def test_samples_keep_newest_first() -> None:
    rows = [_alert(5, 80), _alert(4, 70), _alert(3, 70, "rule_of_three")]
    samples = alert_samples(rows)
    assert [s["ids"] for s in samples] == [[5], [4, 3]]
