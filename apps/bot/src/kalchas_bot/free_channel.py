"""When a fire may also post to the free Telegram channel.

Gathering (no end date, or now still before it): every paid fire also goes free.
After that: Mon-Thu GMT only, and at most one free fire per rolling 60 minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

WEEKEND_GMT = {4, 5, 6}  # Friday, Saturday, Sunday
FREE_COOLDOWN = timedelta(minutes=60)


def parse_unlimited_until(raw: str | None) -> datetime | None:
    """None means gathering is still open. A date is inclusive through that GMT day."""
    text = (raw or "").strip()
    if not text:
        return None
    if len(text) <= 10:
        day = datetime.fromisoformat(text).date()
        return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def gathering_open(now: datetime, unlimited_until: str | None) -> bool:
    cutoff = parse_unlimited_until(unlimited_until)
    if cutoff is None:
        return True
    return _utc(now) < cutoff


def allow_free_fire(
    *,
    now: datetime,
    unlimited_until: str | None,
    last_free_at: datetime | None,
) -> bool:
    if gathering_open(now, unlimited_until):
        return True
    clock = _utc(now)
    if clock.weekday() in WEEKEND_GMT:
        return False
    if last_free_at is None:
        return True
    return clock - _utc(last_free_at) >= FREE_COOLDOWN


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
