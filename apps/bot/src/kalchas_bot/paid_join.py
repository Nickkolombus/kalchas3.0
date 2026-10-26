"""Paid-channel join tracking.

Whop tells the api app about a purchase and we hand back a single-use
Telegram invite link, but Whop never learns -- and can't tell us -- which
Telegram account actually used it. The bot already long-polls with
``allowed_updates=Update.ALL_TYPES``, so ``chat_member`` updates on the paid
channel already arrive here; this is the only place a Whop membership id
gets tied to a concrete Telegram user id, which is what a later cancellation
needs in order to kick the right account.
"""

from __future__ import annotations

import logging

from telegram import ChatMemberUpdated, Update
from telegram.ext import ContextTypes

from kalchas_bot.paid_channel import paid_chat_id

logger = logging.getLogger("kalchas.bot.paid_join")


def joined_via_invite(update: ChatMemberUpdated) -> tuple[int, str] | None:
    """(telegram_user_id, invite_link) for a fresh join through a link, else None."""
    if update.new_chat_member.status != "member" or update.old_chat_member.status == "member":
        return None
    if update.invite_link is None:
        return None
    return update.new_chat_member.user.id, update.invite_link.invite_link


async def on_paid_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_member = update.chat_member
    if chat_member is None:
        return
    chat_id = paid_chat_id()
    if not chat_id or str(chat_member.chat.id) != chat_id:
        return
    matched = joined_via_invite(chat_member)
    if matched is None:
        return
    telegram_user_id, invite_link = matched
    try:
        from kalchas_db import get_pool
        from kalchas_db.whop_grants import mark_joined_by_invite_link

        pool = get_pool()
        async with pool.acquire() as conn:
            await mark_joined_by_invite_link(conn, invite_link, telegram_user_id)
    except Exception:
        logger.exception("failed to record paid-channel join for user %s", telegram_user_id)
