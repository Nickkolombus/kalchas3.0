"""Deliver a message to a Whop member via Whop's own DM API.

POST /dm_channels (reuses an existing channel if one exists) then
POST /messages. Best-effort: a failed DM should not fail the webhook, the
grant row is already written and the admin can always resend the invite
link by hand. Sync httpx, matching this app's other outbound HTTP client
(`kalchas_football.FootballAPIClient`).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

import httpx

logger = logging.getLogger("kalchas.api.whop")

WHOP_API = "https://api.whop.com/api/v1"


def whop_api_key(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    value = (source.get("WHOP_API_KEY") or "").strip()
    return value or None


def dm_user(
    whop_user_id: str,
    content: str,
    *,
    api_key: str,
    client: httpx.Client | None = None,
) -> None:
    owns_client = client is None
    http_client = client or httpx.Client(
        timeout=10.0, headers={"Authorization": f"Bearer {api_key}"}
    )
    try:
        channel_resp = http_client.post(
            f"{WHOP_API}/dm_channels", json={"with_user_ids": [whop_user_id]}
        )
        channel_resp.raise_for_status()
        channel_id = channel_resp.json()["id"]
        message_resp = http_client.post(
            f"{WHOP_API}/messages", json={"channel_id": channel_id, "content": content}
        )
        message_resp.raise_for_status()
    except Exception:
        logger.exception("whop DM failed for user %s", whop_user_id)
    finally:
        if owns_client:
            http_client.close()
