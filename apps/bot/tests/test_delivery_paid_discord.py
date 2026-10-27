"""Paid-channel send: cross-posts to Discord on a new send, not on an edit."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from kalchas_bot.delivery import _deliver_group

DISCORD_SETTINGS = {
    "free_channel_id": None,
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


def _patch_db(monkeypatch: pytest.MonkeyPatch, *, siblings: list[object]) -> None:
    monkeypatch.setattr("kalchas_db.alerts.sent_same_minute", AsyncMock(return_value=siblings))
    monkeypatch.setattr("kalchas_db.alerts.mark_sent", AsyncMock())
    monkeypatch.setattr("kalchas_db.alerts.mark_discord_sent", AsyncMock())
    monkeypatch.setattr("kalchas_db.alerts.attach_free_message", AsyncMock())


def _patch_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_payload(*_args: object, **_kwargs: object) -> tuple[None, str, str]:
        return None, "caption", "fallback"

    monkeypatch.setattr("kalchas_bot.delivery._alert_payload", fake_payload)


@pytest.mark.asyncio
async def test_new_send_cross_posts_to_discord(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db(monkeypatch, siblings=[])
    _patch_payload(monkeypatch)
    sent: list[str] = []

    async def fake_send_alert(*_args: object, **_kwargs: object) -> int:
        return 99

    discord_posts: list[str] = []

    async def fake_send_discord_message(token: str, channel_id: str, **_kwargs: object) -> int:
        discord_posts.append(channel_id)
        return 55

    monkeypatch.setattr("kalchas_bot.delivery._send_alert", fake_send_alert)
    monkeypatch.setattr("kalchas_bot.delivery.send_discord_message", fake_send_discord_message)

    await _deliver_group(
        bot=object(),  # type: ignore[arg-type]
        pool=FakePool(),
        chat_id="-100",
        group=[{"id": 1, "match_id": "m1", "minute": 10}],
        free_chat_id=None,
        unlimited_until=None,
        discord_bot_token="tok",
        discord_settings=DISCORD_SETTINGS,
    )
    assert sent == []
    assert discord_posts == ["111"]


@pytest.mark.asyncio
async def test_edit_does_not_create_a_new_discord_post(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db(
        monkeypatch,
        siblings=[{"telegram_message_id": 42, "discord_message_id": 77}],
    )
    _patch_payload(monkeypatch)

    async def fake_edit_posted(*_args: object, **_kwargs: object) -> None:
        return None

    discord_edits: list[int] = []

    async def fake_edit_discord_message(
        token: str, channel_id: str, message_id: int, **_kwargs: object
    ) -> None:
        discord_edits.append(message_id)

    monkeypatch.setattr("kalchas_bot.delivery._edit_posted", fake_edit_posted)
    monkeypatch.setattr("kalchas_bot.delivery.edit_discord_message", fake_edit_discord_message)

    await _deliver_group(
        bot=object(),  # type: ignore[arg-type]
        pool=FakePool(),
        chat_id="-100",
        group=[{"id": 1, "match_id": "m1", "minute": 10}],
        free_chat_id=None,
        unlimited_until=None,
        discord_bot_token="tok",
        discord_settings=DISCORD_SETTINGS,
    )
    assert discord_edits == [77]


@pytest.mark.asyncio
async def test_no_bot_token_skips_cross_post(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db(monkeypatch, siblings=[])
    _patch_payload(monkeypatch)

    async def fake_send_alert(*_args: object, **_kwargs: object) -> int:
        return 99

    posted: list[str] = []

    async def fake_send_discord_message(token: str, channel_id: str, **_kwargs: object) -> int:
        posted.append(channel_id)
        return 55

    monkeypatch.setattr("kalchas_bot.delivery._send_alert", fake_send_alert)
    monkeypatch.setattr("kalchas_bot.delivery.send_discord_message", fake_send_discord_message)

    await _deliver_group(
        bot=object(),  # type: ignore[arg-type]
        pool=FakePool(),
        chat_id="-100",
        group=[{"id": 1, "match_id": "m1", "minute": 10}],
        free_chat_id=None,
        unlimited_until=None,
        discord_bot_token=None,
        discord_settings=DISCORD_SETTINGS,
    )
    assert posted == []
