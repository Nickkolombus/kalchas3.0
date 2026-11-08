"""Telegram bot — commands + optional Postgres outbox delivery."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram import Update
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
)

from kalchas_bot.discord_channel import discord_bot_token
from kalchas_bot.paid_channel import paid_chat_id
from kalchas_bot.paid_join import on_paid_chat_member
from kalchas_bot.twitter_channel import twitter_credentials

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


def _maybe_start_goal_push(application: Application) -> None:
    """Browser goal alerts: independent of the Telegram channels."""
    from kalchas_bot.push_goals import push_goals_loop, vapid_private_key

    dsn = os.environ.get("DATABASE_URL")
    key = vapid_private_key()
    if not dsn or not key:
        logger.info("goal push worker idle (DATABASE_URL and VAPID_PRIVATE_KEY required)")
        return
    application.bot_data["push_task"] = asyncio.create_task(push_goals_loop(dsn, key))


async def _maybe_start_delivery(application: Application) -> None:
    _maybe_start_goal_push(application)
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
            discord_bot_token=discord_bot_token(),
            twitter=twitter_credentials(),
        )
    )

    from kalchas_bot.recap_job import RecapTargets, recap_admin_chat_id, recap_loop

    targets = RecapTargets(
        paid_chat_id=chat_id,
        free_chat_id=free_chat_id,
        admin_chat_id=recap_admin_chat_id(),
        discord_token=discord_bot_token(),
        twitter=twitter_credentials(),
    )
    application.bot_data["recap_task"] = asyncio.create_task(recap_loop(application.bot, targets))

    # Admin parlay slips: post, settle when every match is played, reply with
    # the hand-marked result. The admin answers its questions with buttons.
    from kalchas_bot.parlay_job import CALLBACK_PREFIX, on_parlay_button, parlay_loop

    application.bot_data["parlay_admin_chat"] = targets.admin_chat_id
    application.add_handler(CallbackQueryHandler(on_parlay_button, pattern=f"^{CALLBACK_PREFIX}:"))
    application.bot_data["parlay_task"] = asyncio.create_task(parlay_loop(application.bot, targets))


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
