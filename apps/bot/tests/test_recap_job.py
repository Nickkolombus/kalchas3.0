"""Weekly recap: drafted on Monday morning, posted only once approved, once per channel."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from kalchas_bot import recap_job
from kalchas_bot.recap_cards import render_recap_cards
from kalchas_bot.recap_job import RecapTargets, draft_due, post_recap, stale_through
from kalchas_core.recap import build_recap
from PIL import Image

LAST_WEEK = date(2026, 10, 26)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def test_draft_window_is_monday_8_to_tuesday_noon():
    assert draft_due(at(2, 7, 59)) is None
    assert draft_due(at(2, 8)) == LAST_WEEK
    assert draft_due(at(3, 11, 59)) == LAST_WEEK
    assert draft_due(at(3, 12)) is None
    assert draft_due(at(5, 9)) is None


def test_drafts_go_stale_after_tuesday_noon():
    assert stale_through(at(3, 11, 59)) == date(2026, 10, 19)
    assert stale_through(at(3, 12)) == LAST_WEEK


TEXTS = {
    "caption": "Head.\n\nEvery signal goes out live.",
    "lesson": "Form travels badly.",
    "x": "x",
}


def _targets() -> RecapTargets:
    return RecapTargets("paid", "free", None, "dtok", None)


@pytest.fixture
def bot() -> Mock:
    bot = Mock()
    bot.send_media_group = AsyncMock(return_value=[Mock(message_id=41)])
    return bot


async def test_posts_only_to_chosen_channels_with_the_lesson(
    bot: Mock, monkeypatch: pytest.MonkeyPatch
):
    album = AsyncMock(return_value=99)
    monkeypatch.setattr(recap_job, "send_discord_album", album)
    channels = {"telegram_paid": False, "telegram_free": True, "discord": True, "x": False}
    log = await post_recap(
        bot, _targets(), TEXTS, channels, [b"a", b"b"], {}, discord={"free_channel_id": "123"}
    )
    assert set(log) == {"telegram_free", "discord"}
    assert log["telegram_free"]["ok"] and log["discord"]["ref"] == "99"
    media = bot.send_media_group.await_args.kwargs["media"]
    assert len(media) == 2
    assert "Form travels badly." in media[0].caption
    assert media[1].caption is None
    assert album.await_args.kwargs["content"].count("Form travels badly.") == 1


async def test_retry_skips_channels_already_posted(bot: Mock, monkeypatch: pytest.MonkeyPatch):
    album = AsyncMock(return_value=None)
    monkeypatch.setattr(recap_job, "send_discord_album", album)
    channels = {"telegram_paid": True, "telegram_free": True, "discord": True, "x": False}
    before = {"telegram_paid": {"ok": True, "ref": "1"}}
    log = await post_recap(
        bot, _targets(), TEXTS, channels, [b"a"], before, discord={"free_channel_id": "1"}
    )
    assert bot.send_media_group.await_count == 1  # free only; paid already went out
    assert bot.send_media_group.await_args.kwargs["chat_id"] == "free"
    assert log["discord"] == {"ok": False, "error": "not configured or rejected"}


async def test_one_channel_failing_does_not_stop_the_others(bot: Mock):
    bot.send_media_group = AsyncMock(side_effect=[RuntimeError("flood"), [Mock(message_id=7)]])
    channels = {"telegram_paid": True, "telegram_free": True}
    log = await post_recap(bot, _targets(), TEXTS, channels, [b"a"], {}, discord={})
    assert log["telegram_paid"]["ok"] is False and "flood" in log["telegram_paid"]["error"]
    assert log["telegram_free"]["ok"] is True


def test_cards_render_as_16_by_9_pngs():
    row = {
        "match_id": "m",
        "minute": 70,
        "strategy_key": "delta_goal",
        "team": "home",
        "value": 1.4,
        "home_team": "Home",
        "away_team": "Away",
        "created_at": datetime(2026, 10, 27, 20, tzinfo=UTC),
        "payload": {"league": "L", "da": {"home": 40, "away": 10}},
        "state": "Confirmed",
        "detail": {"fire_score": "0-0", "settle_score": "1-0", "goal_minute": 74},
    }
    miss = {**row, "match_id": "n", "state": "Expired", "detail": {}}
    data = build_recap([row, miss], week_start=LAST_WEEK)
    texts = {**data.pop("texts"), "lesson": "A lesson."}
    cards = render_recap_cards(data, texts)
    assert len(cards) == 3
    for png in cards:
        from io import BytesIO

        image = Image.open(BytesIO(png))
        assert image.size == (1800, 1012) or image.size == (1800, 1013)


def test_an_empty_week_still_renders_a_cover():
    data = build_recap([], week_start=LAST_WEEK)
    assert len(render_recap_cards(data, data.pop("texts"))) == 1
