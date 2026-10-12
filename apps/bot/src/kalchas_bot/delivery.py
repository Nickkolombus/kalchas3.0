"""Delivery worker — fire photos, then GOAL / No goal replies under them."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, cast

from telegram import Bot

from kalchas_bot.banner import render_alert_photo
from kalchas_bot.format import format_alert_html, format_outcome_html

logger = logging.getLogger("kalchas.bot.delivery")


async def deliver_loop(bot: Bot, chat_id: str, *, poll_sec: float = 2.0) -> None:
    """Claim pending outbox rows and send. Requires DATABASE_URL + migrated schema."""
    from kalchas_db import create_pool, get_pool
    from kalchas_db.alerts import (
        claim_pending,
        claim_pending_outcomes,
        mark_failed,
        mark_outcome_failed,
        mark_outcome_sent,
        mark_sent,
    )

    await create_pool()
    pool = get_pool()
    while True:
        try:
            async with pool.acquire() as conn:
                rows = await claim_pending(conn)
            for row in rows:
                try:
                    message_id = await _send_alert(bot, chat_id, row)
                    async with pool.acquire() as conn:
                        await mark_sent(conn, int(row["id"]), message_id)
                except Exception as exc:
                    logger.exception("send failed for alert %s", row["id"])
                    async with pool.acquire() as conn:
                        await mark_failed(conn, int(row["id"]), str(exc))
            async with pool.acquire() as conn:
                outcomes = await claim_pending_outcomes(conn)
            for row in outcomes:
                try:
                    await _send_outcome(bot, chat_id, row)
                    async with pool.acquire() as conn:
                        await mark_outcome_sent(conn, int(row["alert_id"]))
                except Exception:
                    logger.exception("outcome reply failed for alert %s", row["alert_id"])
                    async with pool.acquire() as conn:
                        await mark_outcome_failed(conn, int(row["alert_id"]))
        except Exception:
            logger.exception("delivery cycle failed")
        await asyncio.sleep(poll_sec)


async def _send_alert(bot: Bot, chat_id: str, row: object) -> int | None:
    mapping = cast(Mapping[str, Any], row)
    photo = await asyncio.to_thread(render_alert_photo, mapping)
    if photo is not None:
        caption = format_alert_html(mapping)
        sent = await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode="HTML",
        )
        return int(sent.message_id) if sent is not None else None
    text = format_alert_html(mapping, with_score=True)
    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
    )
    return int(sent.message_id) if sent is not None else None


async def _send_outcome(bot: Bot, chat_id: str, row: object) -> None:
    mapping = cast(Mapping[str, Any], row)
    reply_to = mapping.get("telegram_message_id")
    await bot.send_message(
        chat_id=chat_id,
        text=format_outcome_html(mapping),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_to_message_id=int(reply_to) if reply_to is not None else None,
        allow_sending_without_reply=True,
    )
