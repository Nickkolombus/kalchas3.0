"""Delivery worker skeleton — claims pending alerts and sends via Telegram."""

from __future__ import annotations

import asyncio
import logging

from telegram import Bot

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
                text = (
                    f"*{row['home_team']}* vs *{row['away_team']}* ({row['minute']}')\n"
                    f"{row['strategy_key']} · {row['team'] or 'match'} · {row['value']:.2f}"
                )
                try:
                    await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
                    async with pool.acquire() as conn:
                        await mark_sent(conn, int(row["id"]))
                except Exception as exc:
                    logger.exception("send failed for alert %s", row["id"])
                    async with pool.acquire() as conn:
                        await mark_failed(conn, int(row["id"]), str(exc))
        except Exception:
            logger.exception("delivery cycle failed")
        await asyncio.sleep(poll_sec)
