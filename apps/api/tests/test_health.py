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


def test_live_placeholder() -> None:
    client = TestClient(app)
    res = client.get("/api/live")
    assert res.status_code == 200
    body = res.json()
    assert body["matches"] == []
    assert body["source"] == "empty"
