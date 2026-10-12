"""Free-channel gathering window and weekday / cooldown throttle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kalchas_bot.free_channel import allow_free_fire, gathering_open, parse_unlimited_until

MON = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)  # Monday
FRI = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)  # Friday


def test_unset_until_stays_in_gathering():
    assert gathering_open(FRI, None) is True
    assert gathering_open(FRI, "") is True
    assert allow_free_fire(now=FRI, unlimited_until=None, last_free_at=FRI) is True


def test_date_only_is_inclusive_through_that_gmt_day():
    assert parse_unlimited_until("2026-10-12") == datetime(2026, 10, 13, tzinfo=UTC)
    assert gathering_open(datetime(2026, 10, 12, 23, 0, tzinfo=UTC), "2026-10-12") is True
    assert gathering_open(datetime(2026, 10, 13, 0, 0, tzinfo=UTC), "2026-10-12") is False


def test_after_cutoff_skips_fri_sat_sun_gmt():
    assert allow_free_fire(now=FRI, unlimited_until="2026-10-01", last_free_at=None) is False
    sat = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
    sun = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    assert allow_free_fire(now=sat, unlimited_until="2026-10-01", last_free_at=None) is False
    assert allow_free_fire(now=sun, unlimited_until="2026-10-01", last_free_at=None) is False
    assert allow_free_fire(now=MON, unlimited_until="2026-10-01", last_free_at=None) is True


def test_rolling_60_minutes_on_weekdays_after_cutoff():
    last = MON
    assert (
        allow_free_fire(
            now=MON + timedelta(minutes=59),
            unlimited_until="2026-10-01",
            last_free_at=last,
        )
        is False
    )
    assert (
        allow_free_fire(
            now=MON + timedelta(minutes=60),
            unlimited_until="2026-10-01",
            last_free_at=last,
        )
        is True
    )
