"""Delivery with admin templates: right text per place, built-in text when Telegram says no."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from kalchas_bot import delivery
from kalchas_bot.delivery import _deliver_group, _deliver_outcomes, _send_alert
from telegram.error import BadRequest

DISCORD_SETTINGS = {
    "free_channel_id": "222",
    "paid_channel_id": "111",
    "free_enabled": True,
    "paid_enabled": True,
}


class _Acquire:
    def __init__(self, conn: object) -> None:
        self.conn = conn

    async def __aenter__(self) -> object:
        return self.conn

    async def __aexit__(self, *args: object) -> bool:
        return False


class FakePool:
    def __init__(self) -> None:
        self.conn = object()

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


def _alert_row() -> dict[str, Any]:
    return {
        "id": 1,
        "match_id": "m1",
        "strategy_slot": 1,
        "strategy_key": "delta_5min",
        "team": "home",
        "value": 8.4,
        "minute": 10,
        "score": "0-0",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "payload": {"league": "Premier League"},
    }


@pytest.mark.asyncio
async def test_each_place_gets_its_own_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.alerts.sent_same_minute", AsyncMock(return_value=[]))
    for name in ("mark_sent", "mark_discord_sent", "mark_free_sent", "mark_discord_free_sent"):
        monkeypatch.setattr(f"kalchas_db.alerts.{name}", AsyncMock())
    monkeypatch.setattr("kalchas_bot.delivery.render_alert_photo", lambda _row: None)
    monkeypatch.setattr("kalchas_bot.delivery.gathering_open", lambda *_a: True)

    telegram: list[tuple[str, str]] = []

    async def fake_send(
        _bot: object, chat_id: str, _photo: object, caption: str, _fallback: str, **_kw: object
    ) -> int:
        telegram.append((chat_id, caption))
        return 5

    discord: list[tuple[str, str]] = []

    async def fake_discord(_token: str, channel_id: str, *, caption: str, **_kw: object) -> int:
        discord.append((channel_id, caption))
        return 6

    monkeypatch.setattr("kalchas_bot.delivery._send_alert", fake_send)
    monkeypatch.setattr("kalchas_bot.delivery.send_discord_message", fake_discord)

    await _deliver_group(
        bot=object(),  # type: ignore[arg-type]
        pool=FakePool(),
        chat_id="paid",
        group=[_alert_row()],
        free_chat_id="free",
        unlimited_until=None,
        discord_bot_token="tok",
        discord_settings=DISCORD_SETTINGS,
        templates={("free", "alert"): "FREE {home}", ("discord", "alert"): "DC {away}"},
    )

    paid_caption = dict(telegram)["paid"]
    assert paid_caption.startswith("<b>Arsenal</b> vs Chelsea")
    assert dict(telegram)["free"] == "FREE Arsenal"
    assert discord == [("111", "DC Chelsea"), ("222", "DC Chelsea")]


@pytest.mark.asyncio
async def test_rejected_template_is_resent_with_built_in_text() -> None:
    bot = Mock()
    sent = Mock(message_id=12)
    bot.send_photo = AsyncMock(side_effect=[BadRequest("Can't parse entities"), sent])
    rejected: list[tuple[str, str, str]] = []
    retry = delivery._Retry("BUILT", "BUILT+score", "paid", "alert", rejected)

    message_id = await _send_alert(bot, "-1", b"png", "MINE", "MINE+score", retry=retry)

    assert message_id == 12
    assert bot.send_photo.await_args_list[1].kwargs["caption"] == "BUILT"
    assert rejected and rejected[0][:2] == ("paid", "alert")


@pytest.mark.asyncio
async def test_without_a_template_a_rejection_still_raises() -> None:
    bot = Mock()
    bot.send_photo = AsyncMock(side_effect=BadRequest("Can't parse entities"))
    with pytest.raises(BadRequest):
        await _send_alert(bot, "-1", b"png", "C", "F")


@pytest.mark.asyncio
async def test_fallbacks_are_recorded_once_per_template(monkeypatch: pytest.MonkeyPatch) -> None:
    record = AsyncMock()
    monkeypatch.setattr("kalchas_db.alert_templates.record_fallback", record)
    await delivery._record_fallbacks(
        FakePool(), [("paid", "alert", "a"), ("paid", "alert", "b"), ("free", "goal", "c")]
    )
    assert [call.args[1:3] for call in record.await_args_list] == [
        ("paid", "alert"),
        ("free", "goal"),
    ]


@pytest.mark.asyncio
async def test_recording_a_fallback_never_breaks_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kalchas_db.alert_templates.record_fallback", AsyncMock(side_effect=RuntimeError("db"))
    )
    await delivery._record_fallbacks(FakePool(), [("paid", "alert", "a")])


@pytest.mark.asyncio
async def test_goal_reply_uses_the_free_template_on_free_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kalchas_db.alerts.message_alert_states", AsyncMock(return_value=[{"state": "Confirmed"}])
    )
    monkeypatch.setattr("kalchas_db.alerts.mark_outcome_sent", AsyncMock())
    bot = Mock()
    bot.send_message = AsyncMock()
    bot.set_message_reaction = AsyncMock()
    row = {
        **_alert_row(),
        "alert_id": 1,
        "state": "Confirmed",
        "telegram_message_id": 9,
        "telegram_free_message_id": 4,
        "detail": {"goal_minute": 12, "fire_score": "0-0", "settle_score": "1-0"},
    }

    await _deliver_outcomes(
        bot,
        FakePool(),
        "paid",
        [row],
        free_chat_id="free",
        templates={("free", "goal"): "Goal for {home} at {goal_minute}"},
    )

    texts = {
        call.kwargs["chat_id"]: call.kwargs["text"] for call in bot.send_message.await_args_list
    }
    assert texts["free"] == "Goal for Arsenal at 12′"
    assert "GOAL at 12′" in texts["paid"]
