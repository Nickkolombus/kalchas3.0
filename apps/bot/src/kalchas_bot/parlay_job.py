"""Admin parlay slips: post them, watch the matches, reply with the result.

The admin saves a slip in admin#parlay; this loop does the rest, once a minute:

1. Post: the slip image goes to each chosen channel. Every message id is kept,
   because the result is posted as a reply under it.
2. Settle: each leg is judged from the match result the watchlist stores. The
   slip waits until every match is played. A leg that was called off, or that
   the result can't settle, is never guessed: the admin gets a Telegram message
   with buttons and decides it.
3. Reply: the same slip, marked up in blue ballpoint, goes under every original
   post. With autopost off, the admin is sent the marked slip with Post / Skip
   buttons first.

A channel already posted (or replied to) is never sent twice: retries only go
to the channels that failed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from kalchas_core.watchlist.parlay_slips import (
    CHOICES,
    judge,
    marks,
    result_caption,
    verdict,
)
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from kalchas_bot.discord_channel import send_discord_message
from kalchas_bot.parlay_slip import render_parlay_slip
from kalchas_bot.recap_job import RecapTargets
from kalchas_bot.twitter_channel import post_album_tweet, post_tweet, upload_media

logger = logging.getLogger("kalchas.bot.parlay")

REVIEW_URL = "https://kalchas.live/admin#parlay"
CAPTION_LIMIT = 1024
CALLBACK_PREFIX = "pl"

CHANNELS = ("x", "telegram_free", "telegram_paid", "discord_free", "discord_paid")

_CHOICE_LABEL = {
    "void": "Void: drop the leg",
    "missed": "Count it as lost",
    "landed": "It landed",
}
_SLOT = {"today": "Today", "tomorrow": "Tomorrow", "nightly": "Nightly"}


async def parlay_loop(bot: Bot, targets: RecapTargets, *, poll_sec: float = 60.0) -> None:
    from kalchas_db import get_pool

    while True:  # the delivery loop owns the pool; wait for it rather than open a second
        try:
            pool = get_pool()
            break
        except RuntimeError:
            await asyncio.sleep(1)
    while True:
        try:
            await tick(bot, pool, targets)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("parlay loop tick failed")
        await asyncio.sleep(poll_sec)


async def tick(bot: Bot, pool: Any, targets: RecapTargets) -> None:
    from kalchas_db import parlay_slips as db
    from kalchas_db.discord_settings import fetch_discord_settings

    while True:
        async with pool.acquire() as conn:
            slip = await db.claim_approved(conn)
            discord = await fetch_discord_settings(conn) if slip else {}
        if slip is None:
            break
        log = await post_slip(bot, targets, slip, discord)
        ok = any((entry or {}).get("ok") for entry in log.values())
        async with pool.acquire() as conn:
            await db.finish_post(
                conn, slip["id"], status="posted" if ok else "failed", post_log=log
            )
        logger.info("parlay #%s posted: %s", slip["id"], log)

    async with pool.acquire() as conn:
        open_slips = await db.open_slips(conn)
    for slip in open_slips:
        await settle_slip(bot, pool, targets, slip)

    while True:
        async with pool.acquire() as conn:
            slip = await db.claim_reply(conn)
        if slip is None:
            break
        log = await reply_slip(bot, targets, slip)
        wanted = [name for name, entry in (slip.get("post_log") or {}).items() if entry.get("ok")]
        done = all((log.get(name) or {}).get("ok") for name in wanted)
        async with pool.acquire() as conn:
            await db.finish_reply(
                conn, slip["id"], status="replied" if done else "reply_failed", reply_log=log
            )
        logger.info("parlay #%s result replies: %s", slip["id"], log)


# ------------------------------------------------------------------- posting


async def post_slip(
    bot: Bot, targets: RecapTargets, slip: Mapping[str, Any], discord: Mapping[str, Any]
) -> dict[str, Any]:
    image = await asyncio.to_thread(
        render_parlay_slip,
        slip["legs"],
        slot=slip["slot"],
        style=slip["style"],
        day=str(slip["day"]),
    )
    caption = str(slip.get("caption") or "")
    x_text = str(slip.get("x_text") or "") or caption
    out: dict[str, Any] = dict(slip.get("post_log") or {})
    wanted = slip.get("channels") or {}
    for name in CHANNELS:
        if not wanted.get(name) or (out.get(name) or {}).get("ok"):
            continue
        dest = _destination(name, targets, discord)
        if dest is None:
            out[name] = {"ok": False, "error": "not configured"}
            continue
        try:
            if name.startswith("telegram"):
                msg = await bot.send_photo(
                    chat_id=dest, photo=image, caption=caption[:CAPTION_LIMIT]
                )
                ref: Any = msg.message_id
            elif name.startswith("discord"):
                ref = await send_discord_message(
                    str(targets.discord_token), dest, photo_bytes=image, caption=caption
                )
            elif targets.twitter is not None:
                ref = await post_album_tweet(targets.twitter, x_text, [image])
            else:
                ref = None
        except Exception as exc:
            logger.exception("parlay #%s %s post failed", slip["id"], name)
            out[name] = {"ok": False, "error": str(exc)[:300]}
            continue
        if ref is None:
            out[name] = {"ok": False, "error": "rejected"}
        else:
            out[name] = {"ok": True, "ref": str(ref), "to": dest, "at": _now()}
    return out


def _destination(name: str, targets: RecapTargets, discord: Mapping[str, Any]) -> str | None:
    if name == "telegram_free":
        return targets.free_chat_id
    if name == "telegram_paid":
        return targets.paid_chat_id
    if name.startswith("discord"):
        tier = name.removeprefix("discord_")
        if not targets.discord_token or not discord.get(f"{tier}_enabled"):
            return None
        return str(discord.get(f"{tier}_channel_id") or "") or None
    return "x" if targets.twitter is not None else None


# ------------------------------------------------------------------ settling


async def settle_slip(bot: Bot, pool: Any, targets: RecapTargets, slip: Mapping[str, Any]) -> None:
    """Judge what has been played; ask, wait or move the slip on to its reply."""
    from kalchas_db import parlay_slips as db

    legs = list(slip["legs"])
    outcomes: dict[str, Any] = dict(slip.get("outcomes") or {})
    final = {mid for mid, e in outcomes.items() if isinstance(e, Mapping) and e.get("outcome")}
    todo = [str(leg["match_id"]) for leg in legs if str(leg["match_id"]) not in final]
    if todo:
        async with pool.acquire() as conn:
            pages = await db.fetch_pages(conn, todo)
    else:
        pages = {}

    pending = False
    questions: list[tuple[int, Mapping[str, Any], dict[str, Any]]] = []
    for n, leg in enumerate(legs, start=1):
        mid = str(leg["match_id"])
        if mid in final:
            continue
        seen = judge(leg, pages.get(mid))
        if seen["state"] == "pending":
            pending = True
        elif seen["state"] in ("landed", "missed"):
            outcomes[mid] = {
                "outcome": seen["state"],
                "note": seen["note"],
                "score": seen.get("score"),
                "by": "result",
            }
        else:
            entry = {"state": seen["state"], "note": seen["note"], "score": seen.get("score")}
            entry["asked"] = bool((outcomes.get(mid) or {}).get("asked"))
            outcomes[mid] = entry
            questions.append((n, leg, entry))

    if pending:
        # Every match has to be played before anything is asked or posted.
        await _save(pool, slip, outcomes, status="posted", result=None)
        return

    if questions:
        asked_now = False
        for n, leg, entry in questions:
            if entry["asked"] or not targets.admin_chat_id:
                continue
            if await _ask_admin(bot, targets.admin_chat_id, slip, n, leg, entry):
                entry["asked"] = True
                asked_now = True
        await _save(pool, slip, outcomes, status="needs_decision", result=None, asked=asked_now)
        return

    v = verdict(legs, outcomes)
    status = "reply_approved" if slip.get("autopost") else "awaiting_reply"
    saved = await _save(pool, slip, outcomes, status=status, result=v["result"])
    if saved and status == "awaiting_reply" and targets.admin_chat_id:
        await _offer_reply(bot, targets.admin_chat_id, {**slip, "outcomes": outcomes}, v)
    logger.info("parlay #%s settled: %s", slip["id"], v["result"])


async def _save(
    pool: Any,
    slip: Mapping[str, Any],
    outcomes: dict[str, Any],
    *,
    status: str,
    result: str | None,
    asked: bool = False,
) -> bool:
    from kalchas_db import parlay_slips as db

    if outcomes == (slip.get("outcomes") or {}) and status == slip["status"] and not asked:
        return False
    async with pool.acquire() as conn:
        return await db.save_settle(
            conn,
            slip["id"],
            outcomes=outcomes,
            status=status,
            result=result,
            seen_at=slip["updated_at"],
            asked=asked,
        )


def slip_title(slip: Mapping[str, Any]) -> str:
    return (
        f"Parlay #{slip['id']} ({_SLOT.get(slip['slot'], slip['slot'])}, {len(slip['legs'])} legs)"
    )


def leg_name(leg: Mapping[str, Any]) -> str:
    home = (leg.get("home") or {}).get("name") or ""
    away = (leg.get("away") or {}).get("name") or ""
    return f"{home} v {away} · {leg.get('label') or leg.get('market')} {float(leg['price']):.2f}"


async def _ask_admin(
    bot: Bot,
    chat_id: str,
    slip: Mapping[str, Any],
    n: int,
    leg: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> bool:
    why = (
        f"was {str(entry['note']).lower()}"
        if entry["state"] == "off"
        else f"finished {entry.get('score') or ''} but the result can't settle this market"
    )
    text = (
        f"{slip_title(slip)}\n"
        f"Leg {n}: {leg_name(leg)} {why}.\n\n"
        "How should it count? The result is posted once every leg is decided.\n"
        f"{REVIEW_URL}"
    )
    buttons = [
        InlineKeyboardButton(
            _CHOICE_LABEL[choice],
            callback_data=f"{CALLBACK_PREFIX}:leg:{slip['id']}:{leg['match_id']}:{choice}",
        )
        for choice in CHOICES[entry["state"]]
    ]
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=InlineKeyboardMarkup([buttons]),
            disable_web_page_preview=True,
        )
        return True
    except Exception:
        logger.exception("parlay #%s: asking the admin failed", slip["id"])
        return False


async def _offer_reply(
    bot: Bot, chat_id: str, slip: Mapping[str, Any], v: Mapping[str, Any]
) -> None:
    image = await asyncio.to_thread(marked_slip, slip)
    caption = (
        f"{slip_title(slip)} is settled.\n\n{result_caption(slip, v)}\n\n"
        "Post this as a reply under the original posts?"
    )
    buttons = [
        InlineKeyboardButton(
            "Post result", callback_data=f"{CALLBACK_PREFIX}:reply:{slip['id']}:post"
        ),
        InlineKeyboardButton("Skip", callback_data=f"{CALLBACK_PREFIX}:reply:{slip['id']}:skip"),
    ]
    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=image,
            caption=caption[:CAPTION_LIMIT],
            reply_markup=InlineKeyboardMarkup([buttons]),
        )
    except Exception:
        logger.exception("parlay #%s: offering the result reply failed", slip["id"])


def marked_slip(slip: Mapping[str, Any]) -> bytes:
    return render_parlay_slip(
        slip["legs"],
        slot=slip["slot"],
        style=slip["style"],
        day=str(slip["day"]),
        settled=marks(slip.get("outcomes") or {}),
        seed=f"parlay-{slip['id']}",
    )


# ------------------------------------------------------------------ replying


async def reply_slip(bot: Bot, targets: RecapTargets, slip: Mapping[str, Any]) -> dict[str, Any]:
    v = verdict(slip["legs"], slip.get("outcomes") or {})
    image = await asyncio.to_thread(marked_slip, slip)
    caption = result_caption(slip, v)
    out: dict[str, Any] = dict(slip.get("reply_log") or {})
    for name, posted in (slip.get("post_log") or {}).items():
        if not posted.get("ok") or (out.get(name) or {}).get("ok"):
            continue
        try:
            ref = await _reply_one(bot, targets, name, posted, image, caption)
        except Exception as exc:
            logger.exception("parlay #%s %s reply failed", slip["id"], name)
            out[name] = {"ok": False, "error": str(exc)[:300]}
            continue
        out[name] = (
            {"ok": True, "ref": str(ref), "at": _now()}
            if ref
            else {"ok": False, "error": "rejected"}
        )
    return out


async def _reply_one(
    bot: Bot,
    targets: RecapTargets,
    name: str,
    posted: Mapping[str, Any],
    image: bytes,
    caption: str,
) -> Any:
    ref, dest = str(posted["ref"]), str(posted.get("to") or "")
    if name.startswith("telegram"):
        msg = await bot.send_photo(
            chat_id=dest,
            photo=image,
            caption=caption[:CAPTION_LIMIT],
            reply_to_message_id=int(ref),
        )
        return msg.message_id
    if name.startswith("discord"):
        if not targets.discord_token:
            return None
        return await send_discord_message(
            targets.discord_token,
            dest,
            photo_bytes=image,
            caption=caption,
            reply_to_message_id=int(ref),
        )
    if targets.twitter is None:
        return None
    import httpx

    async with httpx.AsyncClient(timeout=60.0) as client:
        media = await upload_media(targets.twitter, image, client=client)
        if media is None:
            return None
        return await post_tweet(
            targets.twitter, caption[:280], media_id=media, reply_to=ref, client=client
        )


# ---------------------------------------------------------- admin's buttons


async def on_parlay_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The admin's answer from Telegram: how a leg counts, or post/skip a result."""
    from kalchas_db import get_pool
    from kalchas_db import parlay_slips as db

    query = update.callback_query
    if query is None or not query.data:
        return
    admin = str(context.bot_data.get("parlay_admin_chat") or "")
    chat = str(query.message.chat.id) if query.message else ""
    if not admin or chat != admin:
        await query.answer("Not allowed here.")
        return
    parts = query.data.split(":")
    try:
        if parts[1] == "leg":
            slip_id, match_id, choice = int(parts[2]), parts[3], parts[4]
            async with get_pool().acquire() as conn:
                row = await db.decide_leg(conn, slip_id, match_id, choice, by="admin")
            note = (
                f"→ {_CHOICE_LABEL[choice]}. Saved."
                if row
                else "→ This slip no longer takes answers."
            )
        elif parts[1] == "reply":
            slip_id, action = int(parts[2]), parts[3]
            async with get_pool().acquire() as conn:
                ok = await db.set_reply(conn, slip_id, action)
            if action == "post":
                note = "→ Posting the result within a minute." if ok else "→ Already handled."
            else:
                note = "→ Skipped: no result reply." if ok else "→ Already handled."
        else:
            return
    except (IndexError, ValueError, KeyError):
        await query.answer("Unknown button.")
        return
    await query.answer()
    message = query.message
    try:
        if isinstance(message, Message) and message.photo:
            await query.edit_message_caption(
                caption=f"{message.caption or ''}\n\n{note}"[:CAPTION_LIMIT]
            )
        elif isinstance(message, Message):
            await query.edit_message_text(text=f"{message.text or ''}\n\n{note}")
    except Exception:
        logger.warning("could not update the admin message", exc_info=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()
