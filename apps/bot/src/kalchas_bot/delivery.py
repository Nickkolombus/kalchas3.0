"""Delivery worker — paid feed always, free channel when the gate allows."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast

from telegram import Bot

from kalchas_bot.banner import render_alert_photo
from kalchas_bot.format import format_alert_html, format_outcome_html
from kalchas_bot.free_channel import allow_free_fire

logger = logging.getLogger("kalchas.bot.delivery")


async def deliver_loop(
    bot: Bot,
    chat_id: str,
    *,
    free_chat_id: str | None = None,
    unlimited_until: str | None = None,
    poll_sec: float = 2.0,
) -> None:
    """Claim pending outbox rows and send. Requires DATABASE_URL + migrated schema."""
    from kalchas_db import create_pool, get_pool
    from kalchas_db.alerts import (
        claim_pending,
        claim_pending_outcomes,
        last_free_sent_at,
        mark_failed,
        mark_free_sent,
        mark_outcome_failed,
        mark_outcome_sent,
        mark_sent,
    )

    await create_pool()
    pool = get_pool()
    last_free_at: datetime | None = None
    while True:
        try:
            async with pool.acquire() as conn:
                rows = await claim_pending(conn)
                last_free_at = await last_free_sent_at(conn)
            for row in rows:
                try:
                    mapping = cast(Mapping[str, Any], row)
                    photo_bytes, caption, fallback = await _alert_payload(mapping)
                    message_id = await _send_alert(
                        bot, chat_id, photo_bytes, caption, fallback
                    )
                    async with pool.acquire() as conn:
                        await mark_sent(conn, int(row["id"]), message_id)
                    if free_chat_id and allow_free_fire(
                        now=datetime.now(UTC),
                        unlimited_until=unlimited_until,
                        last_free_at=last_free_at,
                    ):
                        try:
                            free_id = await _send_alert(
                                bot, free_chat_id, photo_bytes, caption, fallback
                            )
                            async with pool.acquire() as conn:
                                await mark_free_sent(conn, int(row["id"]), free_id)
                            last_free_at = datetime.now(UTC)
                        except Exception:
                            logger.exception(
                                "free-channel send failed for alert %s", row["id"]
                            )
                except Exception as exc:
                    logger.exception("send failed for alert %s", row["id"])
                    async with pool.acquire() as conn:
                        await mark_failed(conn, int(row["id"]), str(exc))
            async with pool.acquire() as conn:
                outcomes = await claim_pending_outcomes(conn)
            for row in outcomes:
                try:
                    await _send_outcome(bot, chat_id, row, free_chat_id=free_chat_id)
                    async with pool.acquire() as conn:
                        await mark_outcome_sent(conn, int(row["alert_id"]))
                except Exception:
                    logger.exception("outcome reply failed for alert %s", row["alert_id"])
                    async with pool.acquire() as conn:
                        await mark_outcome_failed(conn, int(row["alert_id"]))
        except Exception:
            logger.exception("delivery cycle failed")
        await asyncio.sleep(poll_sec)


async def _alert_payload(
    mapping: Mapping[str, Any],
) -> tuple[bytes | None, str, str]:
    photo = await asyncio.to_thread(render_alert_photo, mapping)
    caption = format_alert_html(mapping)
    fallback = format_alert_html(mapping, with_score=True)
    blob = photo.getvalue() if photo is not None else None
    return blob, caption, fallback


async def _send_alert(
    bot: Bot,
    chat_id: str,
    photo_bytes: bytes | None,
    caption: str,
    fallback: str,
) -> int | None:
    if photo_bytes is not None:
        sent = await bot.send_photo(
            chat_id=chat_id,
            photo=BytesIO(photo_bytes),
            caption=caption,
            parse_mode="HTML",
        )
        return int(sent.message_id) if sent is not None else None
    sent = await bot.send_message(
        chat_id=chat_id,
        text=fallback,
        parse_mode="HTML",
    )
    return int(sent.message_id) if sent is not None else None


async def _send_outcome(
    bot: Bot,
    chat_id: str,
    row: object,
    *,
    free_chat_id: str | None,
) -> None:
    mapping = cast(Mapping[str, Any], row)
    text = format_outcome_html(mapping)
    reply_to = mapping.get("telegram_message_id")
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_to_message_id=int(reply_to) if reply_to is not None else None,
        allow_sending_without_reply=True,
    )
    free_reply = mapping.get("telegram_free_message_id")
    if free_chat_id and free_reply is not None:
        await bot.send_message(
            chat_id=free_chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_to_message_id=int(free_reply),
            allow_sending_without_reply=True,
        )
