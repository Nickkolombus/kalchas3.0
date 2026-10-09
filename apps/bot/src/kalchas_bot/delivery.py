"""Delivery worker skeleton — claims pending alerts and sends via Telegram."""

from __future__ import annotations

import asyncio
import logging

from telegram import Bot

from kalchas_bot.banner import render_alert_photo
from kalchas_bot.format import format_alert_html

logger = logging.getLogger("kalchas.bot.delivery")


async def deliver_loop(bot: Bot, chat_id: str, *, poll_sec: float = 2.0) -> None:
    """Claim pending outbox rows and send. Requires DATABASE_URL + migrated schema."""
    from kalchas_db import create_pool, get_pool
    from kalchas_db.alerts import claim_pending, mark_failed, mark_sent

    await create_pool()
    pool = get_pool()
    while True:
        try:
            async with pool.acquire() as conn:
                rows = await claim_pending(conn)
            for row in rows:
                try:
                    await _send_alert(bot, chat_id, row)
                    async with pool.acquire() as conn:
                        await mark_sent(conn, int(row["id"]))
                except Exception as exc:
                    logger.exception("send failed for alert %s", row["id"])
                    async with pool.acquire() as conn:
                        await mark_failed(conn, int(row["id"]), str(exc))
        except Exception:
            logger.exception("delivery cycle failed")
        await asyncio.sleep(poll_sec)


async def _send_alert(bot: Bot, chat_id: str, row: object) -> None:
    photo = await asyncio.to_thread(render_alert_photo, row)
    if photo is not None:
        caption = format_alert_html(row)
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode="HTML",
        )
        return
    text = format_alert_html(row, with_score=True)
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
    )
