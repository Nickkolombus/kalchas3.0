"""Telegram bot — commands + optional Postgres outbox delivery."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram import Update
from telegram.error import Conflict
from telegram.ext import Application, ChatMemberHandler, CommandHandler, ContextTypes

from kalchas_bot.discord_channel import discord_paid_webhook_url, discord_webhook_url
from kalchas_bot.paid_channel import paid_chat_id
from kalchas_bot.paid_join import on_paid_chat_member

logger = logging.getLogger("kalchas.bot")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        # Expected for a few seconds during a redeploy: the outgoing container's
        # long-poll briefly overlaps with the new one's. Self-resolves.
        logger.warning("Conflict on getUpdates (redeploy overlap) — ignoring")
        return
    logger.error("Unhandled error", exc_info=context.error)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Kalchas 3.0 bot is up. Alerts are delivered from the scanner pipeline."
        )


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("ok")


async def _maybe_start_delivery(application: Application) -> None:
    chat_id = paid_chat_id()
    if not chat_id or not os.environ.get("DATABASE_URL"):
        logger.info("delivery worker idle (TIPS_CHANNEL_ID and DATABASE_URL required)")
        return
    from kalchas_bot.delivery import deliver_loop

    application.add_handler(ChatMemberHandler(on_paid_chat_member, ChatMemberHandler.CHAT_MEMBER))

    free_chat_id = (os.environ.get("TELEGRAM_FREE_CHANNEL") or "").strip() or None
    unlimited_until = (os.environ.get("TELEGRAM_FREE_UNLIMITED_UNTIL") or "").strip() or None
    application.bot_data["delivery_task"] = asyncio.create_task(
        deliver_loop(
            application.bot,
            chat_id,
            free_chat_id=free_chat_id,
            unlimited_until=unlimited_until,
            discord_webhook_url=discord_webhook_url(),
            discord_paid_webhook_url=discord_paid_webhook_url(),
        )
    )


def build_app(token: str) -> Application:
    app = Application.builder().token(token).post_init(_maybe_start_delivery).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("health", health))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    # httpx logs every request URL at INFO, and Telegram's URLs carry the bot
    # token (api.telegram.org/bot<token>/...). Failures still log at WARNING.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_TOKEN is required")
    # Single-replica only: long polling must not run twice.
    build_app(token).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
