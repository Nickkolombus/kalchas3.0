"""Contact form: visitors message us from the site without leaving it.

Each message is saved first, then emailed to info@kalchas.live through
Resend (Reply goes straight to the visitor) and pinged to the admin Telegram
chat. Delivery runs after the response so a slow provider never holds up the
form; a failed delivery still leaves the message in admin.

Spam: a hidden field people never see, a minimum time to fill the form, and
a cap per sender and across everyone per hour. Bots that trip the first two
get a normal "sent" reply so they learn nothing.

Env (all on the `kalchas3.0` service):
  RESEND_API_KEY            -- without it, no email (message still saved + pinged)
  CONTACT_TO_EMAIL          -- default info@kalchas.live
  CONTACT_FROM_EMAIL        -- default "Kalchas website <contact@kalchas.live>",
                               must be on a domain verified in Resend
  CONTACT_TELEGRAM_CHAT_ID  -- falls back to RECAP_ADMIN_CHAT_ID
  TELEGRAM_TOKEN            -- the bot token the api already uses
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from kalchas_api.admin_auth import require_admin
from kalchas_api.telegram_client import TELEGRAM_API, telegram_token
from kalchas_api.visitors import client_ip, mask_ip

log = logging.getLogger("kalchas.api.contact")

public_router = APIRouter(prefix="/api", tags=["contact"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin-contact"])

RESEND_URL = "https://api.resend.com/emails"
DEFAULT_TO = "info@kalchas.live"
DEFAULT_FROM = "Kalchas website <contact@kalchas.live>"

MAX_NAME = 80
MAX_EMAIL = 200
MIN_MESSAGE = 10
MAX_MESSAGE = 4000
MAX_USER_AGENT = 400

MIN_FILL_MS = 2500
"""A person needs longer than this to type a name, email and message."""

WINDOW_SECONDS = 3600
PER_SENDER_LIMIT = 3
OVERALL_LIMIT = 30
"""Across everyone per hour: protects the inbox if many addresses join in."""

TELEGRAM_LIMIT = 4096

_EMAIL = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[A-Za-z]{2,}$")


class ContactIn(BaseModel):
    name: str = ""
    email: str = ""
    message: str = ""
    website: str = ""
    """The honeypot: hidden from people, filled in by form-stuffing bots."""
    elapsed_ms: int = 0


@dataclass(frozen=True)
class ContactMessage:
    name: str
    email: str
    message: str
    country: str | None = None


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def _one_line(value: str) -> str:
    return " ".join(value.split())


def clean(body: ContactIn) -> ContactMessage:
    """Trimmed fields, or a 400 whose detail is shown to the visitor as is."""
    name = _one_line(body.name)
    email = body.email.strip()
    message = body.message.replace("\r\n", "\n").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Please add your name.")
    if len(name) > MAX_NAME:
        raise HTTPException(
            status_code=400, detail=f"Please keep your name under {MAX_NAME} characters."
        )
    if not email or len(email) > MAX_EMAIL or not _EMAIL.match(email):
        raise HTTPException(status_code=400, detail="Please check your email address.")
    if len(message) < MIN_MESSAGE:
        raise HTTPException(status_code=400, detail="Please write a little more in your message.")
    if len(message) > MAX_MESSAGE:
        raise HTTPException(
            status_code=400, detail=f"Please keep your message under {MAX_MESSAGE} characters."
        )
    return ContactMessage(name=name, email=email, message=message)


def looks_automated(body: ContactIn) -> bool:
    return bool(body.website.strip()) or body.elapsed_ms < MIN_FILL_MS


def ip_hash(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(f"kalchas-contact:{ip.strip()}".encode()).hexdigest()


def contact_to(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    return (source.get("CONTACT_TO_EMAIL") or "").strip() or DEFAULT_TO


def contact_from(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    return (source.get("CONTACT_FROM_EMAIL") or "").strip() or DEFAULT_FROM


def contact_chat_id(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    for key in ("CONTACT_TELEGRAM_CHAT_ID", "RECAP_ADMIN_CHAT_ID"):
        value = (source.get(key) or "").strip()
        if value:
            return value
    return None


def email_payload(msg: ContactMessage, *, to: str, sender: str) -> dict[str, Any]:
    where = f" ({msg.country})" if msg.country else ""
    return {
        "from": sender,
        "to": [to],
        "reply_to": msg.email,
        "subject": f"Website message from {msg.name}"[:150],
        "text": (
            f"{msg.message}\n\n"
            f"--\n"
            f"From: {msg.name} <{msg.email}>{where}\n"
            f"Sent with the contact form on kalchas.live. Reply to this email to answer them."
        ),
    }


def telegram_text(msg: ContactMessage) -> str:
    head = f"New website message\nFrom: {msg.name} <{msg.email}>\n\n"
    room = TELEGRAM_LIMIT - len(head)
    body = msg.message if len(msg.message) <= room else msg.message[: room - 1] + "…"
    return head + body


def send_email(msg: ContactMessage, client: httpx.Client | None = None) -> bool:
    key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not key:
        log.info("contact email skipped: RESEND_API_KEY not set")
        return False
    owns = client is None
    http = client or httpx.Client(timeout=10.0)
    try:
        response = http.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {key}"},
            json=email_payload(msg, to=contact_to(), sender=contact_from()),
        )
        if response.status_code >= 400:
            log.warning(
                "contact email rejected (%s): %s", response.status_code, response.text[:300]
            )
            return False
        return True
    except httpx.HTTPError:
        log.exception("contact email failed")
        return False
    finally:
        if owns:
            http.close()


def send_telegram(msg: ContactMessage, client: httpx.Client | None = None) -> bool:
    token = telegram_token()
    chat_id = contact_chat_id()
    if not token or not chat_id:
        log.info("contact Telegram ping skipped: token or chat id not set")
        return False
    owns = client is None
    http = client or httpx.Client(timeout=10.0)
    try:
        response = http.post(
            f"{TELEGRAM_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": telegram_text(msg), "disable_web_page_preview": True},
        )
        if response.status_code >= 400 or not response.json().get("ok"):
            log.warning("contact Telegram ping rejected (%s)", response.status_code)
            return False
        return True
    except (httpx.HTTPError, ValueError):
        log.exception("contact Telegram ping failed")
        return False
    finally:
        if owns:
            http.close()


def deliver(msg: ContactMessage, message_id: int | None) -> tuple[bool, bool]:
    emailed = send_email(msg)
    pinged = send_telegram(msg)
    dsn = _dsn()
    if dsn and message_id is not None:
        try:
            from kalchas_db.contact import mark_delivered

            mark_delivered(dsn, message_id, emailed=emailed, telegram_sent=pinged)
        except Exception:
            log.exception("contact delivery flags not saved for message %s", message_id)
    return emailed, pinged


@public_router.post("/contact")
def contact(body: ContactIn, request: Request, background: BackgroundTasks) -> dict[str, bool]:
    if looks_automated(body):
        log.info("contact message dropped as automated")
        return {"ok": True}
    msg = clean(body)
    country = (request.headers.get("CF-IPCountry") or "").strip().upper() or None
    msg = ContactMessage(name=msg.name, email=msg.email, message=msg.message, country=country)
    ip = client_ip(request)
    sender = ip_hash(ip)

    dsn = _dsn()
    if not dsn:
        # Nowhere to keep it: only report success if it actually went out.
        emailed, pinged = deliver(msg, None)
        if not (emailed or pinged):
            raise HTTPException(status_code=503, detail="unavailable")
        return {"ok": True}

    from kalchas_db.contact import insert_message, recent_counts

    try:
        mine, everyone = recent_counts(dsn, sender, WINDOW_SECONDS)
    except Exception:
        log.exception("contact rate check failed")
        raise HTTPException(status_code=503, detail="unavailable") from None
    if mine >= PER_SENDER_LIMIT or everyone >= OVERALL_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="You've sent a few messages already. Please try again in an hour.",
        )
    try:
        message_id = insert_message(
            dsn,
            name=msg.name,
            email=msg.email,
            message=msg.message,
            ip_hash=sender,
            ip_masked=mask_ip(ip),
            country=country,
            user_agent=(request.headers.get("user-agent") or "")[:MAX_USER_AGENT] or None,
        )
    except Exception:
        log.exception("contact message not saved")
        raise HTTPException(status_code=503, detail="unavailable") from None
    background.add_task(deliver, msg, message_id)
    return {"ok": True}


@admin_router.get("/contact")
def admin_contact(request: Request) -> dict[str, Any]:
    require_admin(request)
    dsn = _dsn()
    if not dsn:
        return {"messages": [], "email_ready": False, "telegram_ready": False}
    from kalchas_db.contact import list_messages

    rows = list_messages(dsn)
    for row in rows:
        created = row.get("created_at")
        row["created_at"] = created.isoformat() if created else None
    return {
        "messages": rows,
        "to": contact_to(),
        "email_ready": bool((os.environ.get("RESEND_API_KEY") or "").strip()),
        "telegram_ready": bool(telegram_token() and contact_chat_id()),
    }
