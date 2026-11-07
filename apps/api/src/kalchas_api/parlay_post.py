"""Post an admin parlay slip image to X / Telegram / Discord.

Sync helpers so the API can fan out without waiting on the bot worker.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from typing import Any

import httpx

from kalchas_api.telegram_client import paid_chat_id, telegram_token

log = logging.getLogger("kalchas.api.parlay_post")

TELEGRAM_API = "https://api.telegram.org"
DISCORD_API = "https://discord.com/api/v10"


def free_chat_id(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    return (source.get("TELEGRAM_FREE_CHANNEL") or "").strip() or None


def discord_bot_token(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    return (source.get("DISCORD_BOT_TOKEN") or "").strip() or None


def post_telegram_photo(
    chat_id: str,
    image: bytes,
    caption: str,
    *,
    token: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    tok = token or telegram_token()
    if not tok or not chat_id:
        return {"ok": False, "error": "telegram not configured"}
    owns = client is None
    http = client or httpx.Client(timeout=30.0)
    try:
        res = http.post(
            f"{TELEGRAM_API}/bot{tok}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"photo": ("parlay.png", image, "image/png")},
        )
        body = (
            res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        )
        if res.status_code >= 400 or not body.get("ok"):
            return {"ok": False, "error": f"telegram HTTP {res.status_code}"}
        mid = (body.get("result") or {}).get("message_id")
        return {"ok": True, "ref": str(mid) if mid is not None else "ok"}
    except Exception as exc:
        log.exception("parlay telegram post failed")
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        if owns:
            http.close()


def post_discord_photo(
    channel_id: str,
    image: bytes,
    caption: str,
    *,
    token: str | None = None,
) -> dict[str, Any]:
    tok = token or discord_bot_token()
    if not tok or not channel_id:
        return {"ok": False, "error": "discord not configured"}

    async def _send() -> dict[str, Any]:
        from kalchas_bot.discord_channel import send_discord_message

        mid = await send_discord_message(tok, channel_id, photo_bytes=image, caption=caption)
        if mid is None:
            return {"ok": False, "error": "discord send failed"}
        return {"ok": True, "ref": str(mid)}

    try:
        return asyncio.run(_send())
    except Exception as exc:
        log.exception("parlay discord post failed")
        return {"ok": False, "error": str(exc)[:300]}


def post_x_photo(image: bytes, text: str) -> dict[str, Any]:
    try:
        from kalchas_bot.twitter_channel import post_album_tweet, twitter_credentials
    except ImportError as exc:
        return {"ok": False, "error": f"twitter import failed: {exc}"[:300]}

    creds = twitter_credentials()
    if creds is None:
        return {"ok": False, "error": "twitter not configured"}

    async def _send() -> dict[str, Any]:
        ref = await post_album_tweet(creds, text, [image])
        if ref is None:
            return {"ok": False, "error": "twitter send failed"}
        return {"ok": True, "ref": str(ref)}

    try:
        return asyncio.run(_send())
    except Exception as exc:
        log.exception("parlay twitter post failed")
        return {"ok": False, "error": str(exc)[:300]}


def fanout(
    image: bytes,
    *,
    caption: str,
    x_text: str,
    channels: Mapping[str, bool],
    discord_settings: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Post to each requested channel. Returns a post_log map."""
    log_out: dict[str, Any] = {}
    if channels.get("telegram_free"):
        log_out["telegram_free"] = post_telegram_photo(free_chat_id() or "", image, caption)
    if channels.get("telegram_paid"):
        log_out["telegram_paid"] = post_telegram_photo(paid_chat_id() or "", image, caption)
    if channels.get("discord_free"):
        cid = ""
        if discord_settings and discord_settings.get("free_enabled"):
            cid = str(discord_settings.get("free_channel_id") or "")
        log_out["discord_free"] = post_discord_photo(cid, image, caption)
    if channels.get("discord_paid"):
        cid = ""
        if discord_settings and discord_settings.get("paid_enabled"):
            cid = str(discord_settings.get("paid_channel_id") or "")
        log_out["discord_paid"] = post_discord_photo(cid, image, caption)
    if channels.get("x"):
        log_out["x"] = post_x_photo(image, x_text)
    return log_out
