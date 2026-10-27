"""Free-channel send: gathering vs 60-minute slot, including a busy gate."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from kalchas_bot.delivery import _try_send_free_fire

CUTOFF = "2026-10-12"
MON = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
FRI = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)

DISCORD_SETTINGS = {
    "free_channel_id": "999",
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


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: datetime,
    unlimited_until: str | None = CUTOFF,
    discord_bot_token: str | None = None,
) -> tuple[tuple[int | None, int | None] | None, list[int], list[str]]:
    sent: list[int] = []
    discord_posts: list[str] = []

    async def fake_send(*_args: object, **_kwargs: object) -> int:
        sent.append(1)
        return 99

    async def fake_discord_send(token: str, channel_id: str, **_kwargs: object) -> int:
        discord_posts.append(channel_id)
        return 55

    monkeypatch.setattr("kalchas_bot.delivery._send_alert", fake_send)
    monkeypatch.setattr("kalchas_bot.delivery.send_discord_message", fake_discord_send)
    monkeypatch.setattr("kalchas_db.alerts.mark_free_sent", AsyncMock())
    monkeypatch.setattr("kalchas_db.alerts.mark_discord_free_sent", AsyncMock())
    monkeypatch.setattr("kalchas_db.alerts.unlock_free_gate", AsyncMock())
    result = await _try_send_free_fire(
        bot=object(),  # type: ignore[arg-type]
        pool=FakePool(),
        alert_id=1,
        free_chat_id="-100",
        photo_bytes=None,
        caption="c",
        fallback="f",
        unlimited_until=unlimited_until,
        discord_bot_token=discord_bot_token,
        discord_settings=DISCORD_SETTINGS,
        now=now,
    )
    return result, sent, discord_posts


@pytest.mark.asyncio
async def test_gathering_still_posts_every_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.alerts.lock_free_gate", AsyncMock())
    monkeypatch.setattr("kalchas_db.alerts.last_free_sent_at", AsyncMock())
    result, sent, discord_posts = await _run(
        monkeypatch, now=FRI, unlimited_until=None, discord_bot_token="tok"
    )
    assert result == (99, 55)
    assert sent == [1]
    assert discord_posts == ["999"]


@pytest.mark.asyncio
async def test_no_discord_token_skips_cross_post(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.alerts.lock_free_gate", AsyncMock())
    monkeypatch.setattr("kalchas_db.alerts.last_free_sent_at", AsyncMock())
    result, sent, discord_posts = await _run(monkeypatch, now=FRI, unlimited_until=None)
    assert result == (99, None)
    assert sent == [1]
    assert discord_posts == []


@pytest.mark.asyncio
async def test_weekend_skips_without_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.alerts.lock_free_gate", AsyncMock())
    monkeypatch.setattr("kalchas_db.alerts.last_free_sent_at", AsyncMock())
    result, sent, discord_posts = await _run(
        monkeypatch, now=FRI, unlimited_until=CUTOFF, discord_bot_token="tok"
    )
    assert result is None
    assert sent == []
    assert discord_posts == []


@pytest.mark.asyncio
async def test_cooldown_blocks_second_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.alerts.lock_free_gate", AsyncMock(return_value=True))
    monkeypatch.setattr("kalchas_db.alerts.last_free_sent_at", AsyncMock(return_value=MON))
    result, sent, discord_posts = await _run(monkeypatch, now=MON)
    assert result is None
    assert sent == []
    assert discord_posts == []


@pytest.mark.asyncio
async def test_cooldown_elapsed_posts_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.alerts.lock_free_gate", AsyncMock(return_value=True))
    monkeypatch.setattr("kalchas_db.alerts.last_free_sent_at", AsyncMock(return_value=None))
    result, sent, discord_posts = await _run(monkeypatch, now=MON, discord_bot_token="tok")
    assert result == (99, 55)
    assert sent == [1]
    assert discord_posts == ["999"]


@pytest.mark.asyncio
async def test_busy_gate_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kalchas_db.alerts.lock_free_gate", AsyncMock(return_value=False))
    monkeypatch.setattr("kalchas_db.alerts.last_free_sent_at", AsyncMock(return_value=None))
    result, sent, discord_posts = await _run(monkeypatch, now=MON)
    assert result is None
    assert sent == []
    assert discord_posts == []
