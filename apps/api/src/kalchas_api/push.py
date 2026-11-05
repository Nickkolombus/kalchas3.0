"""Browser goal alerts: a visitor's browser registers here with its pinned matches.

The site asks for notification permission, subscribes through the browser's
push service and sends us that subscription plus the match ids it has pinned
(again whenever the pins change). The bot does the sending.

Env (on the `kalchas3.0` service):
  VAPID_PUBLIC_KEY  -- base64url application server key; without it the site
                       hides the goal-alert switch.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from kalchas_db.push import clean_match_ids, delete_subscription, upsert_subscription
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/push", tags=["push"])

PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",  # Chrome, Edge on Android, Brave, Opera, Samsung
    "push.services.mozilla.com",  # Firefox
    "push.apple.com",  # Safari, iOS home-screen apps
    "notify.windows.com",  # Edge on Windows
)
"""Only real browser push services: we POST to these, so never to anything a
visitor makes up."""

_B64URL = re.compile(r"^[A-Za-z0-9_\-]+=*$")
MAX_ENDPOINT = 1024
MAX_USER_AGENT = 400


def vapid_public_key() -> str:
    return (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="Goal alerts are not available")
    return dsn


def allowed_endpoint(endpoint: str) -> bool:
    if not endpoint or len(endpoint) > MAX_ENDPOINT:
        return False
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in PUSH_HOST_SUFFIXES)


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: SubscriptionKeys
    match_ids: list[str] = Field(default_factory=list, max_length=200)


class EndpointIn(BaseModel):
    endpoint: str


@router.get("/config")
def push_config() -> dict[str, object]:
    key = vapid_public_key()
    return {"enabled": bool(key), "public_key": key or None}


@router.put("/subscription")
def save_subscription(body: SubscriptionIn, request: Request) -> dict[str, object]:
    if not vapid_public_key():
        raise HTTPException(status_code=503, detail="Goal alerts are not available")
    if not allowed_endpoint(body.endpoint):
        raise HTTPException(status_code=400, detail="Unsupported push service")
    if not (_B64URL.match(body.keys.p256dh) and _B64URL.match(body.keys.auth)):
        raise HTTPException(status_code=400, detail="Bad subscription keys")
    match_ids = clean_match_ids(body.match_ids)
    user_agent = (request.headers.get("user-agent") or "")[:MAX_USER_AGENT] or None
    upsert_subscription(
        _dsn(),
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        match_ids=match_ids,
        user_agent=user_agent,
    )
    return {"ok": True, "following": len(match_ids)}


@router.delete("/subscription")
def remove_subscription(body: EndpointIn) -> dict[str, bool]:
    if not allowed_endpoint(body.endpoint):
        return {"ok": True}
    delete_subscription(_dsn(), body.endpoint)
    return {"ok": True}
