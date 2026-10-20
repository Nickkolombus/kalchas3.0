"""Outcome delivery: GOAL reply + tick, miss is reaction only."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from kalchas_bot.delivery import _react_on_fire, _same_minute_groups, _send_outcome, outcome_action
from telegram.error import TelegramError


@pytest.mark.asyncio
async def test_react_falls_back_to_next_emoji() -> None:
    bot = Mock()
    bot.set_message_reaction = AsyncMock(
        side_effect=[TelegramError("REACTION_INVALID"), None]
    )
    await _react_on_fire(bot, "-100", 12, ("😢", "👎"))
    emojis = [
        call.kwargs["reaction"][0].emoji for call in bot.set_message_reaction.await_args_list
    ]
    assert emojis == ["😢", "👎"]


@pytest.mark.asyncio
async def test_confirmed_outcome_replies_and_reacts() -> None:
    bot = Mock()
    bot.send_message = AsyncMock()
    bot.set_message_reaction = AsyncMock()
    await _send_outcome(
        bot,
        "-1001",
        {
            "state": "Confirmed",
            "strategy_key": "rule_of_three",
            "team": "home",
            "home_team": "A",
            "away_team": "B",
            "minute": 67,
            "value": 1.3,
            "telegram_message_id": 9,
            "telegram_free_message_id": 4,
            "detail": {
                "fire_score": "0-2",
                "settle_score": "1-2",
                "goal_minute": 96,
            },
        },
        free_chat_id="-1002",
    )
    assert bot.send_message.await_count == 2
    paid_ids = [
        call.kwargs["message_id"] for call in bot.set_message_reaction.await_args_list
    ]
    assert 9 in paid_ids
    assert 4 in paid_ids
    ticks = [
        call.kwargs["reaction"][0].emoji for call in bot.set_message_reaction.await_args_list
    ]
    assert ticks[0] == "✅"


@pytest.mark.asyncio
async def test_expired_outcome_reacts_without_reply() -> None:
    bot = Mock()
    bot.send_message = AsyncMock()
    bot.set_message_reaction = AsyncMock()
    await _send_outcome(
        bot,
        "-1001",
        {
            "state": "Expired",
            "strategy_key": "rule_of_three",
            "team": "home",
            "home_team": "A",
            "away_team": "B",
            "telegram_message_id": 9,
            "telegram_free_message_id": 4,
            "detail": {"success_window_minutes": 20},
        },
        free_chat_id="-1002",
    )
    bot.send_message.assert_not_called()
    emojis = [
        call.kwargs["reaction"][0].emoji for call in bot.set_message_reaction.await_args_list
    ]
    ids = [call.kwargs["message_id"] for call in bot.set_message_reaction.await_args_list]
    assert emojis == ["😢", "😢"]
    assert ids == [9, 4]


def test_same_minute_rows_share_one_group():
    groups = _same_minute_groups(
        [
            {"match_id": "1", "minute": 82, "id": 1},
            {"match_id": "1", "minute": 81, "id": 2},
            {"match_id": "1", "minute": 82, "id": 3},
        ]
    )
    assert [len(group) for group in groups] == [2, 1]


def test_shared_post_waits_to_cry_while_a_strategy_is_open():
    assert outcome_action(["Expired", None], ["Expired"]) == "wait"
    assert outcome_action(["Expired", "Expired"], ["Expired"]) == "miss"
    assert outcome_action(["Confirmed", "Expired"], ["Expired"]) == "silent"
    assert outcome_action(["Confirmed", "Expired"], ["Confirmed"]) == "goal"
