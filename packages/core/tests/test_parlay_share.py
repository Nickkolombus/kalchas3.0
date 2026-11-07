"""Admin parlay share helpers: Nightly window and leg selection."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from kalchas_core.watchlist.parlay_share import (
    WINDOW_LABEL,
    can_post,
    filter_nightly,
    is_nightly_kickoff,
    nightly_day,
    rebuild_orders,
    select_legs,
    slot_day,
)

GMT3 = timezone(timedelta(hours=3))


def test_nightly_day_before_and_after_seven() -> None:
    early = datetime(2026, 11, 7, 3, 0, tzinfo=GMT3).astimezone(UTC)
    late = datetime(2026, 11, 7, 12, 0, tzinfo=GMT3).astimezone(UTC)
    assert nightly_day(early).isoformat() == "2026-11-07"
    assert nightly_day(late).isoformat() == "2026-11-08"


def test_slot_day_today_tomorrow_nightly() -> None:
    today = date(2026, 11, 7)
    noon = datetime(2026, 11, 7, 12, 0, tzinfo=GMT3).astimezone(UTC)
    assert slot_day("today", today=today, now=noon).isoformat() == "2026-11-07"
    assert slot_day("tomorrow", today=today, now=noon).isoformat() == "2026-11-08"
    assert slot_day("nightly", today=today, now=noon).isoformat() == "2026-11-08"


def test_nightly_kickoff_filter() -> None:
    assert is_nightly_kickoff("2026-11-08T02:30:00+03:00")
    assert is_nightly_kickoff("2026-11-08T00:00:00+03:00")
    assert not is_nightly_kickoff("2026-11-08T07:00:00+03:00")
    assert not is_nightly_kickoff("2026-11-07T21:00:00+03:00")
    legs = [
        {
            "match_id": "1",
            "kickoff": "2026-11-08T02:00:00+03:00",
            "price": 1.5,
            "hit": 7,
            "n": 10,
            "watch": "strong",
            "score": 0.5,
        },
        {
            "match_id": "2",
            "kickoff": "2026-11-08T15:00:00+03:00",
            "price": 1.6,
            "hit": 8,
            "n": 10,
            "watch": "strong",
            "score": 0.6,
        },
    ]
    night = filter_nightly(legs)
    assert [leg["match_id"] for leg in night] == ["1"]
    assert "GMT+3" in WINDOW_LABEL


def test_select_legs_respects_exclude_and_floor() -> None:
    legs = [
        {
            "match_id": "a",
            "kickoff": "2026-11-07T14:00:00+03:00",
            "price": 1.5,
            "hit": 8,
            "n": 10,
            "watch": "strong",
            "score": 0.5,
        },
        {
            "match_id": "b",
            "kickoff": "2026-11-07T15:00:00+03:00",
            "price": 1.7,
            "hit": 7,
            "n": 10,
            "watch": "strong",
            "score": 0.4,
        },
        {
            "match_id": "c",
            "kickoff": "2026-11-07T16:00:00+03:00",
            "price": 1.8,
            "hit": 7,
            "n": 10,
            "watch": "strong",
            "score": 0.3,
        },
        {
            "match_id": "d",
            "kickoff": "2026-11-07T17:00:00+03:00",
            "price": 1.9,
            "hit": 7,
            "n": 10,
            "watch": "look",
            "score": 0.2,
        },
    ]
    orders = rebuild_orders(legs)
    picked = select_legs(legs, orders["balanced"], exclude=["b"])
    assert [leg["match_id"] for leg in picked] == ["a", "c", "d"]
    assert can_post(picked)
    assert not can_post(picked[:2])
