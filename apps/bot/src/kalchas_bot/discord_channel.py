"""Cross-post fires to Discord webhooks (one for the free channel, one for
the paid channel).

A webhook takes Markdown, not Telegram's HTML ``parse_mode``, and a photo
goes as a multipart file rather than a Telegram photo upload. This mirrors
the fire message only -- not outcome replies or reactions, which a Discord
webhook has no equivalent for.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from collections.abc import Mapping

import httpx

logger = logging.getLogger("kalchas.bot.discord")

DISCORD_CONTENT_LIMIT = 2000

_BOLD = re.compile(r"<b>(.*?)</b>", re.DOTALL)
_ITALIC = re.compile(r"<i>(.*?)</i>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def discord_webhook_url(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    value = (source.get("DISCORD_WEBHOOK_URL") or "").strip()
    return value or None


def discord_paid_webhook_url(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    value = (source.get("DISCORD_PAID_WEBHOOK_URL") or "").strip()
    return value or None


def html_to_discord(text: str) -> str:
    """Telegram HTML caption -> Discord markdown. Unknown tags are dropped."""
    out = _BOLD.sub(r"**\1**", text)
    out = _ITALIC.sub(r"*\1*", out)
    out = _TAG.sub("", out)
    return html.unescape(out)


async def send_discord_alert(
    webhook_url: str,
    *,
    photo_bytes: bytes | None,
    caption: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Post one fire to the webhook. Logs and swallows failures -- best effort,
    never allowed to break Telegram delivery."""
    content = html_to_discord(caption)
    if len(content) > DISCORD_CONTENT_LIMIT:
        content = content[: DISCORD_CONTENT_LIMIT - 1] + "…"
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=10.0)
    try:
        if photo_bytes is not None:
            response = await http_client.post(
                webhook_url,
                data={"payload_json": json.dumps({"content": content})},
                files={"files[0]": ("alert.png", photo_bytes, "image/png")},
            )
        else:
            response = await http_client.post(webhook_url, json={"content": content})
        response.raise_for_status()
    except Exception:
        logger.exception("discord webhook post failed")
    finally:
        if owns_client:
            await http_client.aclose()
