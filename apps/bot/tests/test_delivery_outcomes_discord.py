"""Outcome delivery mirrors to Discord: goal replies + reacts, miss just reacts."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from kalchas_bot.delivery import _deliver_outcomes

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
    def __init__(self, conn: object | None = None) -> None:
        self.conn = conn or object()

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


def _confirmed_row() -> dict[str, object]:
    return {
        "alert_id": 1,
        "state": "Confirmed",
        "strategy_key": "rule_of_three",
        "team": "home",
        "home_team": "A",
        "away_team": "B",
        "minute": 67,
        "value": 1.3,
        "telegram_message_id": 9,
        "telegram_free_message_id": 4,
        "discord_message_id": 77,
        "discord_free_message_id": 88,
        "detail": {"fire_score": "0-2", "settle_score": "1-2", "goal_minute": 96},
    }


def _expired_row() -> dict[str, object]:
    return {
        "alert_id": 1,
        "state": "Expired",
        "strategy_key": "rule_of_three",
        "team": "home",
        "home_team": "A",
        "away_team": "B",
        "minute": 67,
        "value": 1.3,
        "telegram_message_id": 9,
        "telegram_free_message_id": 4,
        "discord_message_id": 77,
        "discord_free_message_id": 88,
        "detail": {"success_window_minutes": 20},
    }


@pytest.mark.asyncio
async def test_goal_replies_and_reacts_on_both_discord_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kalchas_db.alerts.message_alert_states", AsyncMock(return_value=[{"state": "Confirmed"}])
    )
    monkeypatch.setattr("kalchas_db.alerts.mark_outcome_sent", AsyncMock())

    replies: list[tuple[str, int]] = []
    reacts: list[tuple[str, int, str]] = []

    async def fake_reply(
        token: str, channel_id: str, *, text: str, reply_to_message_id: int
    ) -> int:
        replies.append((channel_id, reply_to_message_id))
        return 1

    async def fake_react(token: str, channel_id: str, message_id: int, emoji: str) -> None:
        reacts.append((channel_id, message_id, emoji))

    monkeypatch.setattr("kalchas_bot.delivery.reply_discord_message", fake_reply)
    monkeypatch.setattr("kalchas_bot.delivery.react_discord_message", fake_react)

    bot = Mock()
    bot.send_message = AsyncMock()
    bot.set_message_reaction = AsyncMock()

    await _deliver_outcomes(
        bot,
        FakePool(),
        "-1001",
        [_confirmed_row()],
        free_chat_id="-1002",
        discord_bot_token="tok",
        discord_settings=DISCORD_SETTINGS,
    )

    assert replies == [("111", 77), ("222", 88)]
    assert reacts == [("111", 77, "✅"), ("222", 88, "✅")]


@pytest.mark.asyncio
async def test_miss_only_reacts_on_discord(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kalchas_db.alerts.message_alert_states", AsyncMock(return_value=[{"state": "Expired"}])
    )
    monkeypatch.setattr("kalchas_db.alerts.mark_outcome_sent", AsyncMock())

    replies: list[tuple[str, int]] = []
    reacts: list[tuple[str, int, str]] = []

    async def fake_reply(
        token: str, channel_id: str, *, text: str, reply_to_message_id: int
    ) -> int:
        replies.append((channel_id, reply_to_message_id))
        return 1

    async def fake_react(token: str, channel_id: str, message_id: int, emoji: str) -> None:
        reacts.append((channel_id, message_id, emoji))

    monkeypatch.setattr("kalchas_bot.delivery.reply_discord_message", fake_reply)
    monkeypatch.setattr("kalchas_bot.delivery.react_discord_message", fake_react)

    bot = Mock()
    bot.send_message = AsyncMock()
    bot.set_message_reaction = AsyncMock()

    await _deliver_outcomes(
        bot,
        FakePool(),
        "-1001",
        [_expired_row()],
        free_chat_id="-1002",
        discord_bot_token="tok",
        discord_settings=DISCORD_SETTINGS,
    )

    assert replies == []
    assert reacts == [("111", 77, "😢"), ("222", 88, "😢")]


@pytest.mark.asyncio
async def test_no_bot_token_skips_discord_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kalchas_db.alerts.message_alert_states", AsyncMock(return_value=[{"state": "Confirmed"}])
    )
    monkeypatch.setattr("kalchas_db.alerts.mark_outcome_sent", AsyncMock())

    reacts: list[tuple[str, int, str]] = []

    async def fake_react(token: str, channel_id: str, message_id: int, emoji: str) -> None:
        reacts.append((channel_id, message_id, emoji))

    monkeypatch.setattr("kalchas_bot.delivery.react_discord_message", fake_react)

    bot = Mock()
    bot.send_message = AsyncMock()
    bot.set_message_reaction = AsyncMock()

    await _deliver_outcomes(
        bot,
        FakePool(),
        "-1001",
        [_confirmed_row()],
        free_chat_id="-1002",
        discord_bot_token=None,
        discord_settings=DISCORD_SETTINGS,
    )

    assert reacts == []
