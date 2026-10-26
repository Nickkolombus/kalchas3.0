"""Whop webhook: signature verification and the grant/revoke dispatch."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from kalchas_api.app import app
from kalchas_api.whop_webhook import (
    _handle_membership_updated,
    _handle_payment_succeeded,
    verify_whop_signature,
)

SECRET = "ws_test_secret"  # noqa: S105 — test fixture, not a real credential


def _signed_headers(body: bytes, *, secret: str = SECRET, webhook_id: str = "msg_1", ts: int = 0):
    signed_content = f"{webhook_id}.{ts}.".encode() + body
    sig = base64.b64encode(
        hmac.new(secret.encode("utf-8"), signed_content, hashlib.sha256).digest()
    ).decode()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": str(ts),
        "webhook-signature": f"v1,{sig}",
    }


class TestVerifyWhopSignature:
    def test_accepts_a_correctly_signed_body(self) -> None:
        body = b'{"type":"payment.succeeded"}'
        headers = _signed_headers(body, ts=1000)
        assert verify_whop_signature(body, headers, SECRET, now=1000) is True

    def test_rejects_wrong_secret(self) -> None:
        body = b'{"type":"payment.succeeded"}'
        headers = _signed_headers(body, ts=1000)
        assert verify_whop_signature(body, headers, "ws_other", now=1000) is False

    def test_rejects_tampered_body(self) -> None:
        headers = _signed_headers(b'{"a":1}', ts=1000)
        assert verify_whop_signature(b'{"a":2}', headers, SECRET, now=1000) is False

    def test_rejects_stale_timestamp(self) -> None:
        body = b'{"type":"payment.succeeded"}'
        headers = _signed_headers(body, ts=1000)
        assert verify_whop_signature(body, headers, SECRET, now=1000 + 301) is False

    def test_rejects_missing_headers(self) -> None:
        assert verify_whop_signature(b"{}", {}, SECRET) is False


def test_webhook_endpoint_requires_configured_secret(monkeypatch) -> None:
    monkeypatch.delenv("WHOP_WEBHOOK_SECRET", raising=False)
    res = TestClient(app).post("/api/webhooks/whop", content=b"{}")
    assert res.status_code == 503


def test_webhook_endpoint_rejects_bad_signature(monkeypatch) -> None:
    monkeypatch.setenv("WHOP_WEBHOOK_SECRET", SECRET)
    res = TestClient(app).post(
        "/api/webhooks/whop",
        content=b'{"type":"payment.succeeded"}',
        headers={"webhook-id": "x", "webhook-timestamp": "1", "webhook-signature": "v1,bad"},
    )
    assert res.status_code == 401


def test_webhook_endpoint_accepts_valid_delivery(monkeypatch) -> None:
    monkeypatch.setenv("WHOP_WEBHOOK_SECRET", SECRET)
    body = json.dumps({"type": "unhandled.event", "data": {}}).encode()
    headers = _signed_headers(body, ts=1000)
    monkeypatch.setattr("kalchas_api.whop_webhook.time.time", lambda: 1000)
    res = TestClient(app).post("/api/webhooks/whop", content=body, headers=headers)
    assert res.status_code == 200
    assert res.json() == {"ok": True}


class TestHandlePaymentSucceeded:
    def _set_prereqs(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
        monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
        monkeypatch.setenv("TIPS_CHANNEL_ID", "-100")
        monkeypatch.delenv("WHOP_PRODUCT_ID", raising=False)

    def test_new_membership_creates_grant_and_schedules_dm(self, monkeypatch) -> None:
        self._set_prereqs(monkeypatch)
        monkeypatch.setenv("WHOP_API_KEY", "key")
        monkeypatch.setattr("kalchas_db.whop_grants.get_grant", lambda dsn, mid: None)
        calls: list[tuple] = []
        monkeypatch.setattr(
            "kalchas_db.whop_grants.upsert_invited_grant",
            lambda dsn, **kw: calls.append(("upsert", kw)),
        )
        monkeypatch.setattr(
            "kalchas_api.telegram_client.create_single_use_invite_link",
            lambda **kw: "https://t.me/+abc",
        )
        bg = BackgroundTasks()
        _handle_payment_succeeded(
            {"membership_id": "mem_1", "product_id": "prod_1", "user": {"id": "user_1"}}, bg
        )
        assert calls == [
            (
                "upsert",
                {"membership_id": "mem_1", "user_id": "user_1", "invite_link": "https://t.me/+abc"},
            )
        ]
        assert len(bg.tasks) == 1

    def test_renewal_payment_is_a_noop(self, monkeypatch) -> None:
        self._set_prereqs(monkeypatch)
        monkeypatch.setattr(
            "kalchas_db.whop_grants.get_grant", lambda dsn, mid: {"status": "joined"}
        )
        invited = []
        monkeypatch.setattr(
            "kalchas_api.telegram_client.create_single_use_invite_link",
            lambda **kw: invited.append(1) or "https://t.me/+abc",
        )
        bg = BackgroundTasks()
        _handle_payment_succeeded(
            {"membership_id": "mem_1", "product_id": "prod_1", "user": {"id": "user_1"}}, bg
        )
        assert invited == []
        assert bg.tasks == []

    def test_wrong_product_is_ignored(self, monkeypatch) -> None:
        self._set_prereqs(monkeypatch)
        monkeypatch.setenv("WHOP_PRODUCT_ID", "prod_premium")
        touched = []
        monkeypatch.setattr("kalchas_db.whop_grants.get_grant", lambda dsn, mid: touched.append(1))
        bg = BackgroundTasks()
        _handle_payment_succeeded(
            {"membership_id": "mem_1", "product_id": "prod_other", "user": {"id": "user_1"}}, bg
        )
        assert touched == []


class TestHandleMembershipUpdated:
    def _set_prereqs(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
        monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
        monkeypatch.setenv("TIPS_CHANNEL_ID", "-100")
        monkeypatch.delenv("WHOP_PRODUCT_ID", raising=False)

    def test_cancellation_kicks_joined_member(self, monkeypatch) -> None:
        self._set_prereqs(monkeypatch)
        monkeypatch.setattr(
            "kalchas_db.whop_grants.get_grant",
            lambda dsn, mid: {"status": "joined", "telegram_user_id": 555},
        )
        kicked = []
        monkeypatch.setattr(
            "kalchas_api.telegram_client.kick_member",
            lambda uid, **kw: kicked.append(uid),
        )
        revoked = []
        monkeypatch.setattr(
            "kalchas_db.whop_grants.mark_revoked", lambda dsn, mid: revoked.append(mid)
        )
        _handle_membership_updated(
            {"id": "mem_1", "product_id": "prod_1", "status": "canceled"},
            {"status": "active"},
        )
        assert kicked == [555]
        assert revoked == ["mem_1"]

    def test_cancellation_without_a_join_just_revokes(self, monkeypatch) -> None:
        self._set_prereqs(monkeypatch)
        monkeypatch.setattr(
            "kalchas_db.whop_grants.get_grant",
            lambda dsn, mid: {"status": "invited", "telegram_user_id": None},
        )
        kicked = []
        monkeypatch.setattr(
            "kalchas_api.telegram_client.kick_member", lambda uid, **kw: kicked.append(uid)
        )
        revoked = []
        monkeypatch.setattr(
            "kalchas_db.whop_grants.mark_revoked", lambda dsn, mid: revoked.append(mid)
        )
        _handle_membership_updated(
            {"id": "mem_1", "product_id": "prod_1", "status": "expired"},
            {"status": "active"},
        )
        assert kicked == []
        assert revoked == ["mem_1"]

    def test_already_revoked_is_a_noop(self, monkeypatch) -> None:
        self._set_prereqs(monkeypatch)
        monkeypatch.setattr(
            "kalchas_db.whop_grants.get_grant",
            lambda dsn, mid: {"status": "revoked", "telegram_user_id": 555},
        )
        kicked = []
        monkeypatch.setattr(
            "kalchas_api.telegram_client.kick_member", lambda uid, **kw: kicked.append(uid)
        )
        _handle_membership_updated(
            {"id": "mem_1", "product_id": "prod_1", "status": "canceled"},
            {"status": "active"},
        )
        assert kicked == []

    def test_duplicate_delivery_with_unchanged_status_is_ignored(self, monkeypatch) -> None:
        self._set_prereqs(monkeypatch)
        touched = []
        monkeypatch.setattr("kalchas_db.whop_grants.get_grant", lambda dsn, mid: touched.append(1))
        _handle_membership_updated(
            {"id": "mem_1", "product_id": "prod_1", "status": "canceled"},
            {"status": "canceled"},
        )
        assert touched == []
