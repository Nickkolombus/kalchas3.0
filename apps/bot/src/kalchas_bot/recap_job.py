"""The weekly recap job: draft on Monday, ping the admin, post only once approved.

Monday 08:00 UTC: last week's signals become a draft (stats, picks, first-draft
stories) and the admin gets a Telegram message with a link to review it.
Nothing goes out until the admin approves it in admin#recap. A draft nobody
approves by Tuesday 12:00 UTC is skipped.

Each channel is posted once: the post log remembers what already went out, so
approving a failed post again only retries the channels that failed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from kalchas_core.recap import build_recap, final_caption, headline, week_bounds, week_label
from kalchas_core.runner import DEFAULT_THRESHOLDS
from telegram import Bot, InputMediaPhoto

from kalchas_bot.discord_channel import send_discord_album
from kalchas_bot.recap_cards import render_recap_cards
from kalchas_bot.twitter_channel import TwitterCredentials, post_album_tweet

logger = logging.getLogger("kalchas.bot.recap")

DRAFT_AT = time(8, 0)
DEADLINE = timedelta(days=1, hours=12)  # Tuesday 12:00 UTC
REVIEW_URL = "https://kalchas.live/admin#recap"
FREE_CHANNEL_URL = "https://t.me/Kalchas_Tips_Free"
CAPTION_LIMIT = 1024


@dataclass(frozen=True)
class RecapTargets:
    paid_chat_id: str | None
    free_chat_id: str | None
    admin_chat_id: str | None
    discord_token: str | None
    twitter: TwitterCredentials | None


def recap_admin_chat_id(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    return (source.get("RECAP_ADMIN_CHAT_ID") or "").strip() or None


def _monday(now: datetime) -> datetime:
    today = now.astimezone(UTC).date()
    return datetime.combine(today - timedelta(days=today.weekday()), time.min, tzinfo=UTC)


def draft_due(now: datetime) -> date | None:
    """Last week's Monday while the draft window is open (Mon 08:00 – Tue 12:00 UTC)."""
    monday = _monday(now)
    if not (monday + timedelta(hours=DRAFT_AT.hour) <= now < monday + DEADLINE):
        return None
    return week_bounds(monday.date())[0]


def stale_through(now: datetime) -> date:
    """Drafts for this week start or earlier have missed their approval deadline."""
    monday = _monday(now)
    last_week = monday.date() - timedelta(days=7)
    return last_week if now >= monday + DEADLINE else last_week - timedelta(days=7)


async def recap_loop(bot: Bot, targets: RecapTargets, *, poll_sec: float = 60.0) -> None:
    from kalchas_db import get_pool

    while True:  # the delivery loop owns the pool; wait for it rather than open a second
        try:
            pool = get_pool()
            break
        except RuntimeError:
            await asyncio.sleep(1)
    while True:
        try:
            now = datetime.now(UTC)
            await _maybe_draft(bot, pool, targets, now)
            async with pool.acquire() as conn:
                from kalchas_db.recaps import skip_stale_drafts

                for week in await skip_stale_drafts(conn, stale_through(now)):
                    logger.info("weekly recap for %s skipped: not approved in time", week)
            await _post_approved(bot, pool, targets)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("recap loop tick failed")
        await asyncio.sleep(poll_sec)


async def _maybe_draft(bot: Bot, pool: Any, targets: RecapTargets, now: datetime) -> None:
    from kalchas_db.recaps import (
        fetch_threshold_overrides,
        fetch_week_signals,
        insert_draft,
        mark_notified,
        refresh_early_draft,
    )
    from kalchas_db.settings import KEY_BY_SLOT

    week = draft_due(now)
    if week is None:
        return
    start = datetime.combine(week, time.min, tzinfo=UTC)
    ended = start + timedelta(days=7)
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT status, created_at FROM weekly_recaps WHERE week_start = $1", week
        )
        if existing is not None and not (
            existing["status"] == "draft" and existing["created_at"] < ended
        ):
            return
        rows = await fetch_week_signals(conn, start, ended)
        overrides = await fetch_threshold_overrides(conn)
        thresholds = {
            key: overrides.get(slot, DEFAULT_THRESHOLDS.get(slot, 0.0))
            for slot, key in KEY_BY_SLOT.items()
        }
        data = build_recap(rows, week_start=week, thresholds=thresholds)
        texts = data.pop("texts")
        if existing is None:
            saved = await insert_draft(conn, week, data, texts)
        else:
            saved = await refresh_early_draft(conn, week, data, texts, week_ended_at=ended)
        if not saved:
            return
        logger.info("weekly recap drafted for %s: %s", week, headline(data))
        if targets.admin_chat_id and await _ping_admin(bot, targets.admin_chat_id, data):
            await mark_notified(conn, week)


async def _ping_admin(bot: Bot, chat_id: str, data: Mapping[str, Any]) -> bool:
    text = (
        f"Weekly recap ready to review ({week_label(data)}).\n"
        f"{headline(data)}.\n\n"
        "Edit the stories, write what we learned, and approve by Tuesday 12:00 UTC. "
        f"Nothing posts until you do.\n{REVIEW_URL}"
    )
    try:
        await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
        return True
    except Exception:
        logger.exception("recap admin ping failed")
        return False


async def _post_approved(bot: Bot, pool: Any, targets: RecapTargets) -> None:
    from kalchas_db.discord_settings import fetch_discord_settings
    from kalchas_db.recaps import claim_approved, finish_post

    async with pool.acquire() as conn:
        recap = await claim_approved(conn)
        discord = await fetch_discord_settings(conn) if recap else {}
    if recap is None:
        return
    week = recap["week_start"]
    log: dict[str, Any] = dict(recap.get("post_log") or {})
    try:
        images = await asyncio.to_thread(render_recap_cards, recap["data"], recap["texts"])
        log = await post_recap(
            bot, targets, recap["texts"], recap["channels"], images, log, discord=discord
        )
    except Exception as exc:
        logger.exception("weekly recap post failed")
        log["error"] = str(exc)[:300]
    wanted = [name for name, on in (recap.get("channels") or {}).items() if on]
    done = all(log.get(name, {}).get("ok") for name in wanted if name in _POSTERS)
    async with pool.acquire() as conn:
        await finish_post(conn, week, status="posted" if done else "failed", post_log=log)
    logger.info("weekly recap for %s: %s", week, "posted" if done else f"failed {log}")


async def post_recap(
    bot: Bot,
    targets: RecapTargets,
    texts: Mapping[str, Any],
    channels: Mapping[str, Any],
    images: list[bytes],
    log: dict[str, Any],
    *,
    discord: Mapping[str, Any],
) -> dict[str, Any]:
    """Post to every chosen channel that hasn't already had it. Returns the updated log."""
    caption = final_caption(texts)
    out = dict(log)
    for name, poster in _POSTERS.items():
        if not channels.get(name) or (out.get(name) or {}).get("ok"):
            continue
        try:
            ref = await poster(bot, targets, texts, caption, images, discord)
        except Exception as exc:
            logger.exception("weekly recap %s failed", name)
            out[name] = {"ok": False, "error": str(exc)[:300]}
            continue
        if ref is None:
            out[name] = {"ok": False, "error": "not configured or rejected"}
        else:
            out[name] = {"ok": True, "ref": str(ref), "at": datetime.now(UTC).isoformat()}
    return out


async def _telegram(bot: Bot, chat_id: str | None, caption: str, images: list[bytes]) -> Any:
    if not chat_id:
        return None
    media = [
        InputMediaPhoto(image, caption=caption[:CAPTION_LIMIT] if i == 0 else None)
        for i, image in enumerate(images)
    ]
    messages = await bot.send_media_group(chat_id=chat_id, media=media)
    return messages[0].message_id if messages else None


async def _telegram_paid(
    bot: Bot,
    targets: RecapTargets,
    texts: Mapping[str, Any],
    caption: str,
    images: list[bytes],
    discord: Mapping[str, Any],
) -> Any:
    return await _telegram(bot, targets.paid_chat_id, caption, images)


async def _telegram_free(
    bot: Bot,
    targets: RecapTargets,
    texts: Mapping[str, Any],
    caption: str,
    images: list[bytes],
    discord: Mapping[str, Any],
) -> Any:
    return await _telegram(bot, targets.free_chat_id, caption, images)


async def _discord(
    bot: Bot,
    targets: RecapTargets,
    texts: Mapping[str, Any],
    caption: str,
    images: list[bytes],
    discord: Mapping[str, Any],
) -> Any:
    channel = discord.get("free_channel_id") or discord.get("paid_channel_id")
    if not targets.discord_token or not channel:
        return None
    return await send_discord_album(
        targets.discord_token, str(channel), images=images, content=caption
    )


async def _x(
    bot: Bot,
    targets: RecapTargets,
    texts: Mapping[str, Any],
    caption: str,
    images: list[bytes],
    discord: Mapping[str, Any],
) -> Any:
    if targets.twitter is None:
        return None
    reply = f"Signals go out free on Telegram, live, before the goal 👉 {FREE_CHANNEL_URL}"
    return await post_album_tweet(
        targets.twitter, str(texts.get("x") or ""), images, reply_text=reply
    )


_POSTERS = {
    "telegram_paid": _telegram_paid,
    "telegram_free": _telegram_free,
    "discord": _discord,
    "x": _x,
}
