"""Telegram bot — commands + optional Postgres outbox delivery."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger("kalchas.bot")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Kalchas 3.0 bot is up. Alerts are delivered from the scanner pipeline."
        )


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("ok")


async def _maybe_start_delivery(application: Application) -> None:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id or not os.environ.get("DATABASE_URL"):
        logger.info("delivery worker idle (TELEGRAM_CHAT_ID and DATABASE_URL required)")
        return
    from kalchas_bot.delivery import deliver_loop

    application.bot_data["delivery_task"] = asyncio.create_task(
        deliver_loop(application.bot, chat_id)
    )


def build_app(token: str) -> Application:
    app = Application.builder().token(token).post_init(_maybe_start_delivery).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("health", health))
    return app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_TOKEN is required")
    # Single-replica only: long polling must not run twice.
    build_app(token).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
