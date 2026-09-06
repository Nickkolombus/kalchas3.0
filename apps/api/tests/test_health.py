"""API health smoke test (no live server required)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from kalchas_api.app import app


def test_health() -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "npei" in body["strategies"] or "rule_of_three" in body["strategies"]


def test_default_weights() -> None:
    client = TestClient(app)
    res = client.get("/api/weights/defaults")
    assert res.status_code == 200
    assert "npei" in res.json()["strategies"]


def test_live_empty_without_database(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    client = TestClient(app)
    res = client.get("/api/live")
    assert res.status_code == 200
    body = res.json()
    assert body["matches"] == []
    assert body["source"] == "empty"


def test_strategy_rules_defaults() -> None:
    client = TestClient(app)
    res = client.get("/api/strategy-rules")
    assert res.status_code == 200
    by_slot = {r["strategy_slot"]: r for r in res.json()["rules"]}
    assert by_slot[2]["team_specific"] is False
    assert by_slot[3]["team_specific"] is False
    assert by_slot[4]["team_specific"] is False
    assert by_slot[1]["team_specific"] is True


def test_patch_team_specific_requires_database() -> None:
    client = TestClient(app)
    res = client.patch("/api/strategy-rules/2", json={"team_specific": True})
    assert res.status_code == 503
