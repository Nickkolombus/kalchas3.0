"""Discord delivery via the real Bot REST API (not an incoming webhook).

A webhook can only post new messages. Posting as a bot user instead gives us
a message id we can edit, reply to, and react on -- the same shape as the
Telegram side in ``delivery.py``. No Gateway connection is needed for any of
this; everything here is a plain authenticated REST call.

Every call is best effort: logged and swallowed, never allowed to break
Telegram delivery.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import urllib.parse
from collections.abc import Mapping

import httpx

logger = logging.getLogger("kalchas.bot.discord")

API_BASE = "https://discord.com/api/v10"
DISCORD_CONTENT_LIMIT = 2000

_BOLD = re.compile(r"<b>(.*?)</b>", re.DOTALL)
_ITALIC = re.compile(r"<i>(.*?)</i>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def discord_bot_token(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    value = (source.get("DISCORD_BOT_TOKEN") or "").strip()
    return value or None


def html_to_discord(text: str) -> str:
    """Telegram HTML caption -> Discord markdown. Unknown tags are dropped."""
    out = _BOLD.sub(r"**\1**", text)
    out = _ITALIC.sub(r"*\1*", out)
    out = _TAG.sub("", out)
    return html.unescape(out)


def _clip(content: str) -> str:
    if len(content) > DISCORD_CONTENT_LIMIT:
        return content[: DISCORD_CONTENT_LIMIT - 1] + "…"
    return content


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bot {token}"}


async def send_discord_message(
    token: str,
    channel_id: str,
    *,
    photo_bytes: bytes | None,
    caption: str,
    client: httpx.AsyncClient | None = None,
) -> int | None:
    """Post a new message. Returns its id, or None on failure."""
    content = _clip(html_to_discord(caption))
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=10.0)
    try:
        url = f"{API_BASE}/channels/{channel_id}/messages"
        if photo_bytes is not None:
            response = await http_client.post(
                url,
                headers=_headers(token),
                data={"payload_json": json.dumps({"content": content})},
                files={"files[0]": ("alert.png", photo_bytes, "image/png")},
            )
        else:
            response = await http_client.post(
                url, headers=_headers(token), json={"content": content}
            )
        response.raise_for_status()
        return int(response.json()["id"])
    except Exception:
        logger.exception("discord send failed")
        return None
    finally:
        if owns_client:
            await http_client.aclose()


async def edit_discord_message(
    token: str,
    channel_id: str,
    message_id: int,
    *,
    caption: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    content = _clip(html_to_discord(caption))
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=10.0)
    try:
        url = f"{API_BASE}/channels/{channel_id}/messages/{message_id}"
        response = await http_client.patch(url, headers=_headers(token), json={"content": content})
        response.raise_for_status()
    except Exception:
        logger.exception("discord edit failed")
    finally:
        if owns_client:
            await http_client.aclose()


async def reply_discord_message(
    token: str,
    channel_id: str,
    *,
    text: str,
    reply_to_message_id: int,
    client: httpx.AsyncClient | None = None,
) -> int | None:
    content = _clip(html_to_discord(text))
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=10.0)
    try:
        url = f"{API_BASE}/channels/{channel_id}/messages"
        response = await http_client.post(
            url,
            headers=_headers(token),
            json={
                "content": content,
                "message_reference": {"message_id": str(reply_to_message_id)},
            },
        )
        response.raise_for_status()
        return int(response.json()["id"])
    except Exception:
        logger.exception("discord reply failed")
        return None
    finally:
        if owns_client:
            await http_client.aclose()


async def react_discord_message(
    token: str,
    channel_id: str,
    message_id: int,
    emoji: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=10.0)
    try:
        encoded = urllib.parse.quote(emoji)
        url = f"{API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me"
        response = await http_client.put(url, headers=_headers(token))
        response.raise_for_status()
    except Exception:
        logger.exception("discord reaction failed")
    finally:
        if owns_client:
            await http_client.aclose()
