"""X gets free-channel fires only, and outcomes reply under the alert tweet."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from kalchas_bot.delivery import _deliver_group, _deliver_outcomes
from kalchas_bot.twitter_channel import TwitterCredentials

TWITTER = TwitterCredentials("k", "ks", "t", "ts")


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


def _fire(alert_id: int) -> dict[str, object]:
    return {
        "id": alert_id,
        "match_id": "555",
        "strategy_slot": alert_id,
        "strategy_key": "rule_of_three",
        "team": "home",
        "value": 1.3,
        "minute": 67,
        "score": "0-1",
        "home_team": "A",
        "away_team": "B",
        "payload": {"league": "L"},
    }


def _patch_group(
    monkeypatch: pytest.MonkeyPatch,
    *,
    free_result: tuple[int | None, int | None] | None,
) -> tuple[list[dict[str, object]], AsyncMock]:
    tweets: list[dict[str, object]] = []

    async def fake_tweet(creds: TwitterCredentials, **kwargs: object) -> str:
        tweets.append(kwargs)
        return "t1"

    async def fake_payload(*_args: object, **_kwargs: object) -> tuple[bytes, str, str]:
        return b"png", "<b>A</b> vs B · 67′", "fallback"

    mark_twitter = AsyncMock()
    monkeypatch.setattr("kalchas_bot.delivery.post_alert_tweet", fake_tweet)
    monkeypatch.setattr("kalchas_bot.delivery._alert_payload", fake_payload)
    monkeypatch.setattr("kalchas_bot.delivery._send_alert", AsyncMock(return_value=10))
    monkeypatch.setattr(
        "kalchas_bot.delivery._try_send_free_fire", AsyncMock(return_value=free_result)
    )
    monkeypatch.setattr("kalchas_db.alerts.sent_same_minute", AsyncMock(return_value=[]))
    monkeypatch.setattr("kalchas_db.alerts.mark_sent", AsyncMock())
    monkeypatch.setattr("kalchas_db.alerts.attach_free_message", AsyncMock())
    monkeypatch.setattr("kalchas_db.alerts.mark_twitter_sent", mark_twitter)
    return tweets, mark_twitter


@pytest.mark.asyncio
async def test_free_fire_tweets_once_and_marks_every_row(monkeypatch: pytest.MonkeyPatch) -> None:
    tweets, mark_twitter = _patch_group(monkeypatch, free_result=(20, None))
    await _deliver_group(
        Mock(),
        FakePool(),
        "-1001",
        [_fire(1), _fire(2)],
        free_chat_id="-1002",
        unlimited_until=None,
        twitter=TWITTER,
    )
    assert len(tweets) == 1
    assert tweets[0]["match_id"] == "555"
    assert tweets[0]["photo_bytes"] == b"png"
    assert [call.args[1:] for call in mark_twitter.await_args_list] == [(1, "t1"), (2, "t1")]


@pytest.mark.asyncio
async def test_gate_closed_means_no_tweet(monkeypatch: pytest.MonkeyPatch) -> None:
    tweets, mark_twitter = _patch_group(monkeypatch, free_result=None)
    await _deliver_group(
        Mock(),
        FakePool(),
        "-1001",
        [_fire(1)],
        free_chat_id="-1002",
        unlimited_until=None,
        twitter=TWITTER,
    )
    assert tweets == []
    mark_twitter.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_credentials_means_no_tweet(monkeypatch: pytest.MonkeyPatch) -> None:
    tweets, _ = _patch_group(monkeypatch, free_result=(20, None))
    await _deliver_group(
        Mock(),
        FakePool(),
        "-1001",
        [_fire(1)],
        free_chat_id="-1002",
        unlimited_until=None,
        twitter=None,
    )
    assert tweets == []


def _outcome(state: str, tweet_id: str | None) -> dict[str, object]:
    return {
        "alert_id": 1,
        "state": state,
        "strategy_key": "rule_of_three",
        "team": "home",
        "home_team": "A",
        "away_team": "B",
        "minute": 67,
        "value": 1.3,
        "telegram_message_id": 9,
        "telegram_free_message_id": 4,
        "twitter_tweet_id": tweet_id,
        "detail": {
            "fire_score": "0-1",
            "settle_score": "1-1",
            "goal_minute": 71,
            "success_window_minutes": 20,
        },
    }


async def _run_outcome(
    monkeypatch: pytest.MonkeyPatch, row: dict[str, object]
) -> list[tuple[str, str]]:
    monkeypatch.setattr(
        "kalchas_db.alerts.message_alert_states",
        AsyncMock(return_value=[{"state": row["state"]}]),
    )
    monkeypatch.setattr("kalchas_db.alerts.mark_outcome_sent", AsyncMock())
    replies: list[tuple[str, str]] = []

    async def fake_reply(creds: TwitterCredentials, text: str, reply_to: str) -> str:
        replies.append((text, reply_to))
        return "r1"

    monkeypatch.setattr("kalchas_bot.delivery.reply_tweet", fake_reply)
    bot = Mock()
    bot.send_message = AsyncMock()
    bot.set_message_reaction = AsyncMock()
    await _deliver_outcomes(bot, FakePool(), "-1001", [row], free_chat_id="-1002", twitter=TWITTER)
    return replies


@pytest.mark.asyncio
async def test_goal_replies_under_the_tweet(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = await _run_outcome(monkeypatch, _outcome("Confirmed", "t1"))
    assert len(replies) == 1
    text, reply_to = replies[0]
    assert reply_to == "t1"
    assert text.startswith("✅ ")
    assert "GOAL at 71′" in text


@pytest.mark.asyncio
async def test_miss_replies_under_the_tweet(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = await _run_outcome(monkeypatch, _outcome("Expired", "t1"))
    assert len(replies) == 1
    text, reply_to = replies[0]
    assert reply_to == "t1"
    assert text.startswith("❌ No goal arrived within 20′")


@pytest.mark.asyncio
async def test_paid_only_fire_has_no_tweet_to_reply_to(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await _run_outcome(monkeypatch, _outcome("Confirmed", None)) == []
