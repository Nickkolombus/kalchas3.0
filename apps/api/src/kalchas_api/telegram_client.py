"""Direct Telegram Bot HTTP API calls for the paid channel.

No dependency on `python-telegram-bot` here -- the api app only needs two
calls (create a single-use invite link, kick a member) and pulling in the
bot's full framework for that would be a heavier dependency than the task
needs. Same bot token and channel id the `bot` app already uses. Sync httpx,
matching this app's other outbound HTTP client
(`kalchas_football.FootballAPIClient`).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

import httpx

logger = logging.getLogger("kalchas.api.telegram")

TELEGRAM_API = "https://api.telegram.org"


def telegram_token(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    for key in ("TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN"):
        value = (source.get(key) or "").strip()
        if value:
            return value
    return None


def paid_chat_id(env: Mapping[str, str] | None = None) -> str | None:
    """Mirrors `kalchas_bot.paid_channel.paid_chat_id` (TIPS_CHANNEL_ID first)."""
    source = env if env is not None else os.environ
    for key in ("TIPS_CHANNEL_ID", "TELEGRAM_CHAT_ID"):
        value = (source.get(key) or "").strip()
        if value:
            return value
    return None


def create_single_use_invite_link(
    *,
    token: str,
    chat_id: str,
    client: httpx.Client | None = None,
) -> str | None:
    """A one-time invite link for the paid channel, or None on failure."""
    owns_client = client is None
    http_client = client or httpx.Client(timeout=10.0)
    try:
        response = http_client.post(
            f"{TELEGRAM_API}/bot{token}/createChatInviteLink",
            json={"chat_id": chat_id, "member_limit": 1, "name": "Whop Kalchas Premium"},
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            logger.warning("createChatInviteLink rejected: %s", data)
            return None
        return str(data["result"]["invite_link"])
    except Exception:
        logger.exception("createChatInviteLink failed")
        return None
    finally:
        if owns_client:
            http_client.close()


def kick_member(
    telegram_user_id: int,
    *,
    token: str,
    chat_id: str,
    client: httpx.Client | None = None,
) -> None:
    """Remove a member without a permanent ban (unban right after)."""
    owns_client = client is None
    http_client = client or httpx.Client(timeout=10.0)
    try:
        http_client.post(
            f"{TELEGRAM_API}/bot{token}/banChatMember",
            json={"chat_id": chat_id, "user_id": telegram_user_id},
        )
        http_client.post(
            f"{TELEGRAM_API}/bot{token}/unbanChatMember",
            json={"chat_id": chat_id, "user_id": telegram_user_id, "only_if_banned": True},
        )
    except Exception:
        logger.exception("kick_member failed for telegram user %s", telegram_user_id)
    finally:
        if owns_client:
            http_client.close()
