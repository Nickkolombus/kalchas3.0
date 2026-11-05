"""Browser goal alerts: the site registers a browser and its pinned matches."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from kalchas_api import push
from kalchas_api.app import app

P256DH = "BOr8n2Q0vBu3K4tFHh0gA0TgbW8n1oQe7c3_tl2mXr0qY9Nw2l4rLk1pV0u3o9sGm6c4Yf2xQwzT7aE1dJ0hK8M"
AUTH = "c2VjcmV0LWF1dGgtMTIz"
FCM = "https://fcm.googleapis.com/fcm/send/abc:APA91b"


@pytest.fixture
def saved(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "BPublicKey")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setattr(push, "upsert_subscription", lambda dsn, **kw: calls.append(kw))
    monkeypatch.setattr(
        push, "delete_subscription", lambda dsn, endpoint: calls.append({"deleted": endpoint})
    )
    return calls


def _body(endpoint: str = FCM, **kw: Any) -> dict[str, Any]:
    body = {"endpoint": endpoint, "keys": {"p256dh": P256DH, "auth": AUTH}, "match_ids": []}
    body.update(kw)
    return body


def test_config_off_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    res = TestClient(app).get("/api/push/config")
    assert res.json() == {"enabled": False, "public_key": None}


def test_config_on_with_key(saved: list[dict[str, Any]]) -> None:
    assert TestClient(app).get("/api/push/config").json() == {
        "enabled": True,
        "public_key": "BPublicKey",
    }


def test_save_cleans_match_ids(saved: list[dict[str, Any]]) -> None:
    res = TestClient(app).put(
        "/api/push/subscription",
        json=_body(match_ids=["123", "123", "x1", " 456 ", ""]),
        headers={"user-agent": "UA"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True, "following": 2}
    assert saved[0]["match_ids"] == ["123", "456"]
    assert saved[0]["endpoint"] == FCM
    assert saved[0]["user_agent"] == "UA"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",
        "https://evil.example.com/push",
        "https://fcm.googleapis.com.evil.com/x",
        "https://127.0.0.1/x",
    ],
)
def test_rejects_anything_but_browser_push_services(
    saved: list[dict[str, Any]], endpoint: str
) -> None:
    res = TestClient(app).put("/api/push/subscription", json=_body(endpoint))
    assert res.status_code == 400
    assert saved == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/QAbc",
        "https://wns2-db5p.notify.windows.com/w/?token=abc",
    ],
)
def test_accepts_known_push_services(saved: list[dict[str, Any]], endpoint: str) -> None:
    assert TestClient(app).put("/api/push/subscription", json=_body(endpoint)).status_code == 200


def test_save_refused_when_push_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    assert TestClient(app).put("/api/push/subscription", json=_body()).status_code == 503


def test_delete(saved: list[dict[str, Any]]) -> None:
    res = TestClient(app).request("DELETE", "/api/push/subscription", json={"endpoint": FCM})
    assert res.status_code == 200
    assert saved == [{"deleted": FCM}]
