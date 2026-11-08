"""Admin parlay slips in the bot: post, settle when all is played, ask, reply."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from kalchas_bot import parlay_job
from kalchas_bot.recap_job import RecapTargets
from kalchas_db import parlay_slips as db

TARGETS = RecapTargets(
    paid_chat_id="-100paid",
    free_chat_id="-100free",
    admin_chat_id="42",
    discord_token="dtok",
    twitter=None,
)


def leg(mid: str, market: str = "over_2_5", price: float = 1.5) -> dict[str, Any]:
    return {
        "match_id": mid,
        "market": market,
        "label": "Over 2.5 goals",
        "price": price,
        "kickoff": "2026-11-08T18:00:00+02:00",
        "home": {"name": f"H{mid}"},
        "away": {"name": f"A{mid}"},
    }


def slip(**over: Any) -> dict[str, Any]:
    base = {
        "id": 5,
        "day": "2026-11-08",
        "slot": "today",
        "style": "balanced",
        "legs": [leg("1"), leg("2"), leg("3")],
        "caption": "Today's parlay",
        "x_text": "",
        "channels": {"telegram_free": True, "discord_free": True, "x": True},
        "autopost": True,
        "status": "posted",
        "post_log": {},
        "outcomes": {},
        "reply_log": {},
        "updated_at": datetime(2026, 11, 8, tzinfo=UTC),
    }
    return base | over


def finished(h: int, a: int) -> dict[str, Any]:
    return {
        "result": {
            "status": "finished",
            "label": "FT",
            "home": h,
            "away": a,
            "home_90": h,
            "away_90": a,
        }
    }


class Bot:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.next_id = 100

    async def send_photo(self, **kw: Any) -> Any:
        self.sent.append(("photo", kw))
        self.next_id += 1
        return SimpleNamespace(message_id=self.next_id)

    async def send_message(self, **kw: Any) -> Any:
        self.sent.append(("message", kw))
        return SimpleNamespace(message_id=1)


class Pool:
    @asynccontextmanager
    async def acquire(self) -> Any:
        yield object()


@pytest.fixture
def saved(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    async def save_settle(conn: Any, slip_id: int, **kw: Any) -> bool:
        out.append(kw)
        return True

    monkeypatch.setattr(db, "save_settle", save_settle)
    return out


def pages_are(monkeypatch: pytest.MonkeyPatch, pages: dict[str, Any]) -> None:
    async def fetch_pages(conn: Any, ids: list[str]) -> dict[str, Any]:
        return {mid: pages[mid] for mid in ids if mid in pages}

    monkeypatch.setattr(db, "fetch_pages", fetch_pages)


async def test_nothing_is_asked_or_replied_while_a_match_is_still_on(
    monkeypatch: pytest.MonkeyPatch, saved: list[dict[str, Any]]
) -> None:
    pages_are(
        monkeypatch, {"1": finished(0, 0), "2": {"result": {"status": "off", "label": "Postponed"}}}
    )
    bot = Bot()
    await parlay_job.settle_slip(bot, Pool(), TARGETS, slip())
    assert bot.sent == []
    assert saved[-1]["status"] == "posted"
    assert saved[-1]["outcomes"]["1"]["outcome"] == "missed"  # early miss is kept, not posted


async def test_all_played_and_autopost_goes_straight_to_the_reply(
    monkeypatch: pytest.MonkeyPatch, saved: list[dict[str, Any]]
) -> None:
    pages_are(monkeypatch, {"1": finished(2, 1), "2": finished(3, 0), "3": finished(1, 1)})
    bot = Bot()
    await parlay_job.settle_slip(bot, Pool(), TARGETS, slip())
    assert saved[-1]["status"] == "reply_approved"
    assert saved[-1]["result"] == "lost"
    assert bot.sent == []


async def test_autopost_off_offers_the_marked_slip_to_the_admin(
    monkeypatch: pytest.MonkeyPatch, saved: list[dict[str, Any]]
) -> None:
    pages_are(monkeypatch, {"1": finished(2, 1), "2": finished(3, 0), "3": finished(2, 2)})
    bot = Bot()
    await parlay_job.settle_slip(bot, Pool(), TARGETS, slip(autopost=False))
    assert saved[-1]["status"] == "awaiting_reply"
    kind, sent = bot.sent[0]
    assert kind == "photo" and sent["chat_id"] == "42"
    labels = [b.callback_data for b in sent["reply_markup"].inline_keyboard[0]]
    assert labels == ["pl:reply:5:post", "pl:reply:5:skip"]


async def test_a_called_off_leg_is_asked_once(
    monkeypatch: pytest.MonkeyPatch, saved: list[dict[str, Any]]
) -> None:
    pages_are(
        monkeypatch,
        {
            "1": finished(2, 1),
            "2": {"result": {"status": "off", "label": "Postponed"}},
            "3": finished(3, 1),
        },
    )
    bot = Bot()
    await parlay_job.settle_slip(bot, Pool(), TARGETS, slip())
    assert saved[-1]["status"] == "needs_decision"
    kind, sent = bot.sent[0]
    assert kind == "message" and "Leg 2" in sent["text"] and "postponed" in sent["text"]
    data = [b.callback_data for b in sent["reply_markup"].inline_keyboard[0]]
    assert data == ["pl:leg:5:2:void", "pl:leg:5:2:missed"]

    again = slip(status="needs_decision", outcomes=saved[-1]["outcomes"])
    await parlay_job.settle_slip(bot, Pool(), TARGETS, again)
    assert len(bot.sent) == 1  # not asked twice


async def test_the_admin_answer_completes_the_slip(
    monkeypatch: pytest.MonkeyPatch, saved: list[dict[str, Any]]
) -> None:
    pages_are(monkeypatch, {"1": finished(2, 1), "3": finished(3, 1)})
    answered = {"2": {"outcome": "void", "by": "admin"}}
    await parlay_job.settle_slip(Bot(), Pool(), TARGETS, slip(outcomes=answered))
    assert saved[-1]["status"] == "reply_approved"
    assert saved[-1]["result"] == "came_in"


async def test_post_keeps_every_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def discord_send(token: str, channel: str, **kw: Any) -> int:
        return 777

    monkeypatch.setattr(parlay_job, "send_discord_message", discord_send)
    bot = Bot()
    discord = {"free_enabled": True, "free_channel_id": "chan1"}
    log = await parlay_job.post_slip(bot, TARGETS, slip(status="posting"), discord)
    assert log["telegram_free"] == {
        "ok": True,
        "ref": "101",
        "to": "-100free",
        "at": log["telegram_free"]["at"],
    }
    assert log["discord_free"]["ref"] == "777" and log["discord_free"]["to"] == "chan1"
    assert log["x"] == {"ok": False, "error": "not configured"}


async def test_post_skips_channels_already_sent() -> None:
    bot = Bot()
    done = {"telegram_free": {"ok": True, "ref": "9", "to": "-100free"}}
    one = slip(channels={"telegram_free": True}, post_log=done)
    log = await parlay_job.post_slip(bot, TARGETS, one, {})
    assert bot.sent == []
    assert log == done


async def test_reply_goes_under_each_original_post(monkeypatch: pytest.MonkeyPatch) -> None:
    replies: list[dict[str, Any]] = []

    async def discord_send(token: str, channel: str, **kw: Any) -> int:
        replies.append({"channel": channel, **kw})
        return 888

    monkeypatch.setattr(parlay_job, "send_discord_message", discord_send)
    bot = Bot()
    posted = {
        "telegram_free": {"ok": True, "ref": "55", "to": "-100free"},
        "discord_free": {"ok": True, "ref": "66", "to": "chan1"},
        "x": {"ok": False, "error": "rejected"},
    }
    outcomes = {m: {"outcome": "landed"} for m in ("1", "2", "3")}
    log = await parlay_job.reply_slip(bot, TARGETS, slip(post_log=posted, outcomes=outcomes))
    kind, sent = bot.sent[0]
    assert kind == "photo" and sent["reply_to_message_id"] == 55
    assert sent["caption"].startswith("Came in")
    assert replies[0]["reply_to_message_id"] == 66 and replies[0]["photo_bytes"][:4] == b"\x89PNG"
    assert set(log) == {"telegram_free", "discord_free"}


async def test_buttons_only_work_in_the_admin_chat() -> None:
    answered: list[str] = []

    async def answer(text: str | None = None) -> None:
        answered.append(text or "")

    query = SimpleNamespace(
        data="pl:leg:5:2:void",
        message=SimpleNamespace(chat=SimpleNamespace(id=999), photo=None, text="", caption=None),
        answer=answer,
    )
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data={"parlay_admin_chat": "42"})
    await parlay_job.on_parlay_button(update, context)  # type: ignore[arg-type]
    assert answered == ["Not allowed here."]
