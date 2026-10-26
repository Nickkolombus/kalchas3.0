"""Whop webhook: grants/revokes Telegram access to match Discord's auto-role.

Two events matter here (docs.whop.com/webhooks):
  - ``payment.succeeded`` -- fires on first purchase *and* every renewal.
    A single-use Telegram invite link is created and DM'd to the buyer, but
    only the first time (or after a prior cancellation) -- a renewal while
    already `invited`/`joined` is a no-op, so this doesn't re-send an invite
    every month.
  - ``membership.updated`` -- carries `data.status` +
    `previous_attributes.status`. A transition into `canceled`/`expired`
    kicks the matching Telegram account, if one ever joined.

Verification follows the Standard-Webhooks-style scheme Whop documents:
HMAC-SHA256 of ``{webhook-id}.{webhook-timestamp}.{raw body}`` keyed with the
raw ``ws_...`` secret, compared against the ``v1,<base64>`` signature header,
with a 5-minute replay window. The payload shape and the exact signing key
derivation are per Whop's docs, not yet confirmed against a live delivery --
see the plan's "known risk" note. Verify with a real test delivery
(Whop dashboard -> webhook -> Send test event) before relying on this.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from kalchas_api import telegram_client, whop_client

logger = logging.getLogger("kalchas.api.whop_webhook")

router = APIRouter(prefix="/api/webhooks", tags=["whop"])

REPLAY_WINDOW_SECONDS = 300

# Membership statuses that mean "has access" (docs.whop.com beta Membership
# object). A transition *out* of this set is what triggers a Telegram kick.
GRANTING_STATUSES = {"active", "trialing", "past_due", "completed"}
NON_GRANTING_STATUSES = {"canceled", "expired"}


def whop_webhook_secret(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    value = (source.get("WHOP_WEBHOOK_SECRET") or "").strip()
    return value or None


def whop_product_id(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    value = (source.get("WHOP_PRODUCT_ID") or "").strip()
    return value or None


def verify_whop_signature(
    body: bytes,
    headers: Mapping[str, str],
    secret: str,
    *,
    now: float | None = None,
) -> bool:
    webhook_id = headers.get("webhook-id")
    timestamp = headers.get("webhook-timestamp")
    signature_header = headers.get("webhook-signature")
    if not webhook_id or not timestamp or not signature_header:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    current = now if now is not None else time.time()
    if abs(current - sent_at) > REPLAY_WINDOW_SECONDS:
        return False
    signed_content = f"{webhook_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(
        hmac.new(secret.encode("utf-8"), signed_content, hashlib.sha256).digest()
    ).decode()
    for candidate in signature_header.split():
        version, _, value = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return True
    return False


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def _handle_payment_succeeded(data: dict[str, Any], background_tasks: BackgroundTasks) -> None:
    if whop_product_id() and str(data.get("product_id") or "") != whop_product_id():
        return
    membership_id = data.get("membership_id")
    user = data.get("user") or {}
    user_id = user.get("id")
    dsn = _dsn()
    token = telegram_client.telegram_token()
    chat_id = telegram_client.paid_chat_id()
    if not membership_id or not user_id or not dsn or not token or not chat_id:
        logger.warning(
            "payment.succeeded missing prerequisites (membership=%s user=%s dsn=%s "
            "token=%s chat=%s)",
            bool(membership_id),
            bool(user_id),
            bool(dsn),
            bool(token),
            bool(chat_id),
        )
        return
    from kalchas_db.whop_grants import get_grant, upsert_invited_grant

    existing = get_grant(dsn, str(membership_id))
    if existing is not None and existing["status"] in ("invited", "joined"):
        return  # renewal payment -- already has access, nothing to do
    invite_link = telegram_client.create_single_use_invite_link(token=token, chat_id=chat_id)
    if not invite_link:
        return
    upsert_invited_grant(
        dsn,
        membership_id=str(membership_id),
        user_id=str(user_id),
        invite_link=invite_link,
    )
    api_key = whop_client.whop_api_key()
    if api_key:
        content = (
            "You're in! Join the Kalchas Premium Telegram channel with this "
            f"one-time link:\n{invite_link}"
        )
        background_tasks.add_task(whop_client.dm_user, str(user_id), content, api_key=api_key)


def _handle_membership_updated(data: dict[str, Any], previous: dict[str, Any]) -> None:
    if whop_product_id() and str(data.get("product_id") or "") != whop_product_id():
        return
    membership_id = data.get("id")
    new_status = str(data.get("status") or "")
    prev_status = str(previous.get("status") or "")
    if not membership_id or new_status not in NON_GRANTING_STATUSES:
        return
    if prev_status and prev_status not in GRANTING_STATUSES:
        return  # not a real grant -> revoke transition (e.g. already canceled)
    dsn = _dsn()
    if not dsn:
        return
    from kalchas_db.whop_grants import get_grant, mark_revoked

    grant = get_grant(dsn, str(membership_id))
    if grant is None or grant["status"] == "revoked":
        return
    telegram_user_id = grant.get("telegram_user_id")
    if telegram_user_id:
        token = telegram_client.telegram_token()
        chat_id = telegram_client.paid_chat_id()
        if token and chat_id:
            telegram_client.kick_member(int(telegram_user_id), token=token, chat_id=chat_id)
    mark_revoked(dsn, str(membership_id))


@router.post("/whop")
async def whop_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, bool]:
    secret = whop_webhook_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="WHOP_WEBHOOK_SECRET is not set")
    body = await request.body()
    if not verify_whop_signature(body, request.headers, secret):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 — malformed body is a 400, not a crash
        raise HTTPException(status_code=400, detail="invalid JSON") from None
    event_type = str(payload.get("type") or "")
    data = payload.get("data") or {}
    previous = payload.get("previous_attributes") or {}
    try:
        if event_type == "payment.succeeded":
            await run_in_threadpool(_handle_payment_succeeded, data, background_tasks)
        elif event_type == "membership.updated":
            await run_in_threadpool(_handle_membership_updated, data, previous)
    except Exception:
        logger.exception("whop webhook handling failed for event %s", event_type)
    return {"ok": True}
