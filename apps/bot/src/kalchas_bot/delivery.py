"""Delivery worker — paid feed always, free channel when the gate allows."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast

from telegram import Bot, ReactionTypeEmoji
from telegram.error import TelegramError

from kalchas_bot.banner import render_alert_photo
from kalchas_bot.format import format_alert_html, format_joint_html, format_outcome_html
from kalchas_bot.free_channel import allow_free_fire, gathering_open

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
        mark_failed,
    )

    await create_pool()
    pool = get_pool()
    while True:
        try:
            async with pool.acquire() as conn:
                rows = await claim_pending(conn)
            groups = _same_minute_groups(rows)
            for group in groups:
                try:
                    await _deliver_group(
                        bot,
                        pool,
                        chat_id,
                        group,
                        free_chat_id=free_chat_id,
                        unlimited_until=unlimited_until,
                    )
                except Exception as exc:
                    logger.exception("send failed for match %s", group[0].get("match_id"))
                    async with pool.acquire() as conn:
                        for row in group:
                            await mark_failed(conn, int(row["id"]), str(exc))
            async with pool.acquire() as conn:
                outcomes = await claim_pending_outcomes(conn)
            await _deliver_outcomes(bot, pool, chat_id, outcomes, free_chat_id=free_chat_id)
        except Exception:
            logger.exception("delivery cycle failed")
        await asyncio.sleep(poll_sec)


def _same_minute_groups(rows: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    order: list[tuple[str, int]] = []
    for row in rows:
        try:
            minute = int(row.get("minute") or 0)
        except (TypeError, ValueError):
            minute = 0
        key = (str(row.get("match_id") or ""), minute)
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(row)
    return [grouped[key] for key in order]


def outcome_action(sibling_states: Sequence[str | None], batch_states: Sequence[str]) -> str:
    """How a shared post settles: goal reply, miss reaction, wait, or stay quiet."""
    if any(state == "Confirmed" for state in batch_states):
        return "goal"
    if any(state == "Confirmed" for state in sibling_states):
        return "silent"
    if any(state is None for state in sibling_states):
        return "wait"
    return "miss"


async def _deliver_group(
    bot: Bot,
    pool: Any,
    chat_id: str,
    group: Sequence[Mapping[str, Any]],
    *,
    free_chat_id: str | None,
    unlimited_until: str | None,
) -> None:
    from kalchas_db.alerts import attach_free_message, mark_sent, sent_same_minute

    first = group[0]
    async with pool.acquire() as conn:
        siblings = await sent_same_minute(
            conn, str(first.get("match_id") or ""), int(first.get("minute") or 0)
        )
    posted = [cast(Mapping[str, Any], row) for row in siblings]
    combined = [*posted, *group]
    joint = len(combined) > 1
    anchor = combined[0]
    photo_bytes, caption, fallback = await _alert_payload(anchor, rows=combined if joint else None)
    existing_id = _message_id(posted[0]) if posted else None
    if existing_id is not None:
        await _edit_posted(bot, chat_id, existing_id, caption, fallback)
        message_id = existing_id
    else:
        message_id = await _send_alert(bot, chat_id, photo_bytes, caption, fallback)
    async with pool.acquire() as conn:
        for row in group:
            await mark_sent(conn, int(row["id"]), message_id)
    if not free_chat_id:
        return
    free_existing = next(
        (
            mid
            for row in posted
            if (mid := _message_id(row, "telegram_free_message_id")) is not None
        ),
        None,
    )
    if free_existing is not None:
        try:
            await _edit_posted(bot, free_chat_id, free_existing, caption, fallback)
            async with pool.acquire() as conn:
                for row in group:
                    await attach_free_message(conn, int(row["id"]), free_existing)
        except Exception:
            logger.exception("free-channel edit failed for match %s", first.get("match_id"))
        return
    try:
        sent_free = await _try_send_free_fire(
            bot,
            pool,
            alert_id=int(group[0]["id"]),
            free_chat_id=free_chat_id,
            photo_bytes=photo_bytes,
            caption=caption,
            fallback=fallback,
            unlimited_until=unlimited_until,
        )
    except Exception:
        logger.exception("free-channel send failed for match %s", first.get("match_id"))
        return
    if sent_free is None:
        return
    async with pool.acquire() as conn:
        for row in group[1:]:
            await attach_free_message(conn, int(row["id"]), sent_free)


async def _deliver_outcomes(
    bot: Bot,
    pool: Any,
    chat_id: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    free_chat_id: str | None,
) -> None:
    from kalchas_db.alerts import (
        mark_outcome_failed,
        mark_outcome_sent,
        message_alert_states,
        release_outcome,
    )

    grouped: dict[int, list[Mapping[str, Any]]] = {}
    order: list[int] = []
    for row in rows:
        message_id = _message_id(row)
        if message_id is None:
            continue
        if message_id not in grouped:
            order.append(message_id)
            grouped[message_id] = []
        grouped[message_id].append(row)
    for message_id in order:
        batch = grouped[message_id]
        try:
            async with pool.acquire() as conn:
                siblings = await message_alert_states(conn, message_id)
            states = [None if item["state"] is None else str(item["state"]) for item in siblings]
            action = outcome_action(states, [str(row.get("state") or "") for row in batch])
            if action == "wait":
                async with pool.acquire() as conn:
                    for row in batch:
                        await release_outcome(conn, int(row["alert_id"]))
                continue
            if action == "goal":
                confirmed = [row for row in batch if str(row.get("state") or "") == "Confirmed"]
                text = "\n\n".join(format_outcome_html(row) for row in confirmed)
                await _reply_outcome(bot, chat_id, text, message_id)
                await _react_on_fire(bot, chat_id, message_id, _GOAL_REACTIONS)
                free_reply = _message_id(confirmed[0], "telegram_free_message_id")
                if free_chat_id and free_reply is not None:
                    await _reply_outcome(bot, free_chat_id, text, free_reply)
                    await _react_on_fire(bot, free_chat_id, free_reply, _GOAL_REACTIONS)
            elif action == "miss":
                await _react_on_fire(bot, chat_id, message_id, _MISS_REACTIONS)
                free_reply = _message_id(batch[0], "telegram_free_message_id")
                if free_chat_id and free_reply is not None:
                    await _react_on_fire(bot, free_chat_id, free_reply, _MISS_REACTIONS)
            async with pool.acquire() as conn:
                for row in batch:
                    await mark_outcome_sent(conn, int(row["alert_id"]))
        except Exception:
            logger.exception("outcome reply failed for message %s", message_id)
            async with pool.acquire() as conn:
                for row in batch:
                    await mark_outcome_failed(conn, int(row["alert_id"]))


def _message_id(row: Mapping[str, Any], key: str = "telegram_message_id") -> int | None:
    raw = row.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _edit_posted(
    bot: Bot,
    chat_id: str,
    message_id: int,
    caption: str,
    fallback: str,
) -> None:
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            parse_mode="HTML",
        )
        return
    except TelegramError as exc:
        if "not modified" in str(exc).lower():
            return
        logger.info("caption edit failed on %s/%s: %s", chat_id, message_id, exc)
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=fallback,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _try_send_free_fire(
    bot: Bot,
    pool: Any,
    *,
    alert_id: int,
    free_chat_id: str,
    photo_bytes: bytes | None,
    caption: str,
    fallback: str,
    unlimited_until: str | None,
    now: datetime | None = None,
) -> int | None:
    """Post to free only if gathering is open, or this worker wins the 60-minute slot."""
    from kalchas_db.alerts import (
        last_free_sent_at,
        lock_free_gate,
        mark_free_sent,
        unlock_free_gate,
    )

    clock = now or datetime.now(UTC)
    if gathering_open(clock, unlimited_until):
        free_id = await _send_alert(bot, free_chat_id, photo_bytes, caption, fallback)
        async with pool.acquire() as conn:
            await mark_free_sent(conn, alert_id, free_id)
        return free_id
    if not allow_free_fire(now=clock, unlimited_until=unlimited_until, last_free_at=None):
        return None

    async with pool.acquire() as conn:
        locked = await lock_free_gate(conn)
        if not locked:
            logger.info("free-channel gate busy, skip alert %s", alert_id)
            return None
        try:
            last_free_at = await last_free_sent_at(conn)
            if not allow_free_fire(
                now=clock,
                unlimited_until=unlimited_until,
                last_free_at=last_free_at,
            ):
                return None
            free_id = await _send_alert(bot, free_chat_id, photo_bytes, caption, fallback)
            await mark_free_sent(conn, alert_id, free_id)
            return free_id
        finally:
            await unlock_free_gate(conn)


async def _alert_payload(
    mapping: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[bytes | None, str, str]:
    photo = await asyncio.to_thread(render_alert_photo, mapping)
    if rows is not None and len(rows) > 1:
        caption = format_joint_html(rows)
        fallback = format_joint_html(rows, with_score=True)
    else:
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


_GOAL_REACTIONS = ("✅", "👍")
_MISS_REACTIONS = ("😢", "👎")


async def _react_on_fire(
    bot: Bot,
    chat_id: str,
    message_id: int,
    emojis: tuple[str, ...],
) -> None:
    last_error: TelegramError | None = None
    for emoji in emojis:
        try:
            await bot.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
            return
        except TelegramError as exc:
            last_error = exc
    if last_error is not None:
        logger.info("reaction skipped on %s/%s: %s", chat_id, message_id, last_error)


async def _reply_outcome(
    bot: Bot,
    chat_id: str,
    text: str,
    reply_to: object,
) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_to_message_id=int(reply_to) if reply_to is not None else None,
        allow_sending_without_reply=True,
    )


async def _send_outcome(
    bot: Bot,
    chat_id: str,
    row: object,
    *,
    free_chat_id: str | None,
) -> None:
    mapping = cast(Mapping[str, Any], row)
    reply_to = mapping.get("telegram_message_id")
    free_reply = mapping.get("telegram_free_message_id")
    confirmed = str(mapping.get("state") or "") == "Confirmed"
    if confirmed:
        text = format_outcome_html(mapping)
        await _reply_outcome(bot, chat_id, text, reply_to)
        if reply_to is not None:
            await _react_on_fire(bot, chat_id, int(reply_to), _GOAL_REACTIONS)
        if free_chat_id and free_reply is not None:
            await _reply_outcome(bot, free_chat_id, text, free_reply)
            await _react_on_fire(bot, free_chat_id, int(free_reply), _GOAL_REACTIONS)
        return
    if reply_to is not None:
        await _react_on_fire(bot, chat_id, int(reply_to), _MISS_REACTIONS)
    if free_chat_id and free_reply is not None:
        await _react_on_fire(bot, free_chat_id, int(free_reply), _MISS_REACTIONS)
