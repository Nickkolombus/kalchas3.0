"""Contact form: saved first, then emailed and pinged; spam is dropped quietly."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from kalchas_api import contact
from kalchas_api.app import app

GOOD = {
    "name": "Sam Reader",
    "email": "sam@example.com",
    "message": "Love the board. Is there an API for the signals?",
    "website": "",
    "elapsed_ms": 9000,
}


class FakeStore:
    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []
        self.delivered: list[tuple[int, bool, bool]] = []
        self.counts = (0, 0)
        self.fail_insert = False

    def recent_counts(self, dsn: str, ip_hash: str | None, seconds: int) -> tuple[int, int]:
        assert seconds == contact.WINDOW_SECONDS
        return self.counts

    def insert_message(self, dsn: str, **row: Any) -> int:
        if self.fail_insert:
            raise RuntimeError("db down")
        self.inserted.append(row)
        return len(self.inserted)

    def mark_delivered(
        self, dsn: str, message_id: int, *, emailed: bool, telegram_sent: bool
    ) -> None:
        self.delivered.append((message_id, emailed, telegram_sent))


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr("kalchas_db.contact.recent_counts", fake.recent_counts)
    monkeypatch.setattr("kalchas_db.contact.insert_message", fake.insert_message)
    monkeypatch.setattr("kalchas_db.contact.mark_delivered", fake.mark_delivered)
    return fake


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def email(msg: contact.ContactMessage, client: httpx.Client | None = None) -> bool:
        calls.append(f"email:{msg.email}")
        return True

    def ping(msg: contact.ContactMessage, client: httpx.Client | None = None) -> bool:
        calls.append(f"telegram:{msg.name}")
        return True

    monkeypatch.setattr(contact, "send_email", email)
    monkeypatch.setattr(contact, "send_telegram", ping)
    return calls


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_message_is_saved_then_emailed_and_pinged(
    client: TestClient, store: FakeStore, sent: list[str]
) -> None:
    res = client.post(
        "/api/contact",
        json={**GOOD, "name": "  Sam \n Reader "},
        headers={"CF-Connecting-IP": "203.0.113.9", "CF-IPCountry": "gb"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    [row] = store.inserted
    assert row["name"] == "Sam Reader"
    assert row["email"] == "sam@example.com"
    assert row["ip_masked"] == "203.0.113.x"
    assert row["country"] == "GB"
    assert row["ip_hash"] and "203.0.113.9" not in row["ip_hash"]
    assert sent == ["email:sam@example.com", "telegram:Sam Reader"]
    assert store.delivered == [(1, True, True)]


@pytest.mark.parametrize(
    "spam",
    [{"website": "http://cheap-pills.example"}, {"elapsed_ms": 400}, {"elapsed_ms": 0}],
)
def test_bots_get_a_normal_reply_but_nothing_is_kept(
    client: TestClient, store: FakeStore, sent: list[str], spam: dict[str, Any]
) -> None:
    res = client.post("/api/contact", json={**GOOD, **spam})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert store.inserted == []
    assert sent == []


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"name": "   "}, "Please add your name."),
        ({"name": "x" * 81}, "Please keep your name under 80 characters."),
        ({"email": "not-an-email"}, "Please check your email address."),
        ({"email": "a@b"}, "Please check your email address."),
        ({"email": "a@b.com, c@d.com"}, "Please check your email address."),
        ({"message": "hi"}, "Please write a little more in your message."),
        ({"message": "x" * 4001}, "Please keep your message under 4000 characters."),
    ],
)
def test_bad_input_says_what_to_fix(
    client: TestClient, store: FakeStore, sent: list[str], change: dict[str, Any], detail: str
) -> None:
    res = client.post("/api/contact", json={**GOOD, **change})
    assert res.status_code == 400
    assert res.json()["detail"] == detail
    assert store.inserted == []


@pytest.mark.parametrize("counts", [(3, 3), (0, 30)])
def test_rate_limit_per_sender_and_overall(
    client: TestClient, store: FakeStore, sent: list[str], counts: tuple[int, int]
) -> None:
    store.counts = counts
    res = client.post("/api/contact", json=GOOD)
    assert res.status_code == 429
    assert "try again in an hour" in res.json()["detail"]
    assert store.inserted == []
    assert sent == []


def test_just_under_the_limit_still_goes_through(
    client: TestClient, store: FakeStore, sent: list[str]
) -> None:
    store.counts = (2, 29)
    assert client.post("/api/contact", json=GOOD).status_code == 200
    assert len(store.inserted) == 1


def test_save_failure_is_an_error_not_a_fake_success(
    client: TestClient, store: FakeStore, sent: list[str]
) -> None:
    store.fail_insert = True
    res = client.post("/api/contact", json=GOOD)
    assert res.status_code == 503
    assert sent == []


def test_failed_delivery_is_recorded_on_the_saved_message(
    client: TestClient, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contact, "send_email", lambda msg, client=None: False)
    monkeypatch.setattr(contact, "send_telegram", lambda msg, client=None: True)
    assert client.post("/api/contact", json=GOOD).status_code == 200
    assert store.delivered == [(1, False, True)]


def test_without_a_database_success_needs_a_delivery(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.setattr(contact, "send_email", lambda msg, client=None: False)
    monkeypatch.setattr(contact, "send_telegram", lambda msg, client=None: False)
    assert client.post("/api/contact", json=GOOD).status_code == 503
    monkeypatch.setattr(contact, "send_telegram", lambda msg, client=None: True)
    assert client.post("/api/contact", json=GOOD).status_code == 200


def test_email_goes_to_info_with_reply_to_the_visitor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("CONTACT_TO_EMAIL", raising=False)
    monkeypatch.delenv("CONTACT_FROM_EMAIL", raising=False)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "abc"})

    msg = contact.ContactMessage(name="Sam", email="sam@example.com", message="Hello there, team")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert contact.send_email(msg, client=http) is True
    [request] = seen
    assert str(request.url) == contact.RESEND_URL
    assert request.headers["Authorization"] == "Bearer re_test_key"
    payload = json.loads(request.content)
    assert payload["to"] == ["info@kalchas.live"]
    assert payload["from"] == "Kalchas website <contact@kalchas.live>"
    assert payload["reply_to"] == "sam@example.com"
    assert payload["subject"] == "Website message from Sam"
    assert payload["text"].startswith("Hello there, team")


def test_email_is_skipped_without_a_key_and_rejections_report_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    msg = contact.ContactMessage(name="Sam", email="sam@example.com", message="Hello there, team")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert contact.send_email(msg) is False
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    rejecting = httpx.MockTransport(lambda r: httpx.Response(403, json={"message": "domain"}))
    with httpx.Client(transport=rejecting) as http:
        assert contact.send_email(msg, client=http) is False


def test_telegram_ping_uses_the_admin_chat_and_fits_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.delenv("CONTACT_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("RECAP_ADMIN_CHAT_ID", "-1009")
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bot123:abc/sendMessage"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    msg = contact.ContactMessage(name="Sam", email="sam@example.com", message="y" * 5000)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert contact.send_telegram(msg, client=http) is True
    [body] = seen
    assert body["chat_id"] == "-1009"
    assert "parse_mode" not in body
    assert len(body["text"]) == contact.TELEGRAM_LIMIT
    assert body["text"].startswith("New website message\nFrom: Sam <sam@example.com>")


def test_contact_chat_prefers_its_own_setting() -> None:
    env = {"CONTACT_TELEGRAM_CHAT_ID": "42", "RECAP_ADMIN_CHAT_ID": "-1009"}
    assert contact.contact_chat_id(env) == "42"
    assert contact.contact_chat_id({}) is None
    assert contact.contact_to({"CONTACT_TO_EMAIL": " hello@kalchas.live "}) == "hello@kalchas.live"


def test_admin_list_needs_login(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    assert client.get("/api/admin/contact").status_code == 401


def test_admin_list_shows_newest_messages(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from kalchas_api.admin_auth import COOKIE_NAME, mint_token

    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    row = {
        "id": 7,
        "created_at": datetime(2026, 11, 4, 12, 30, tzinfo=UTC),
        "name": "Sam",
        "email": "sam@example.com",
        "message": "Hello there, team",
        "ip_masked": "203.0.113.x",
        "country": "GB",
        "emailed": True,
        "telegram_sent": False,
    }
    monkeypatch.setattr("kalchas_db.contact.list_messages", lambda dsn, limit=200: [dict(row)])
    client.cookies.set(COOKIE_NAME, mint_token())
    res = client.get("/api/admin/contact")
    assert res.status_code == 200
    body = res.json()
    assert body["email_ready"] is True
    assert body["to"] == "info@kalchas.live"
    assert body["messages"][0]["created_at"] == "2026-11-04T12:30:00+00:00"
    assert body["messages"][0]["emailed"] is True
