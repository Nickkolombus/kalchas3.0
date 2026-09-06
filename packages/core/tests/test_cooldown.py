"""CooldownBook unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from kalchas_core.cooldown import CooldownBook, cooldown_key, normalize_match_id


def test_string_and_int_match_ids_equivalent() -> None:
    book = CooldownBook()
    d1 = book.decide("12345", 1, 45, 2.5, team="home")
    assert d1.can_send
    book.confirm(d1.cooldown_key)
    d2 = book.decide(12345, 1, 46, 2.6, team="home")
    assert not d2.can_send
    assert d2.blocked_by == "S1_COOLDOWN"


def test_none_match_id() -> None:
    assert normalize_match_id(None) == "unknown"
    book = CooldownBook()
    d = book.decide(None, 2, 60, 85.0)
    assert d.can_send
    assert "unknown" in d.cooldown_key


def test_tslg_global_mute() -> None:
    book = CooldownBook(goal_cooldown_minutes=10)
    d = book.decide(
        "1",
        1,
        50,
        3.0,
        team="home",
        goal_events=[{"minute": 45, "side": "away"}],
    )
    assert not d.can_send
    assert d.blocked_by == "TSLG_GLOBAL_MUTE"


def test_red_card_mute() -> None:
    book = CooldownBook()
    d = book.decide("1", 1, 40, 2.0, team="home", red_cards={"home": 1})
    assert not d.can_send
    assert d.blocked_by == "RED_CARD_MUTE"


def test_value_delta_bypass() -> None:
    fixed = datetime(2026, 1, 1, 12, 0, 0)
    book = CooldownBook(_clock=lambda: fixed)
    d1 = book.decide("1", 1, 40, 1.0, team="home")
    book.confirm(d1.cooldown_key)
    # Within cooldown, small increase — blocked
    d2 = book.decide("1", 1, 45, 1.2, team="home")
    assert not d2.can_send
    # Large enough bypass for slot 1 (0.5)
    d3 = book.decide("1", 1, 45, 1.6, team="home")
    assert d3.can_send


def test_same_minute_block() -> None:
    book = CooldownBook()
    d1 = book.decide("1", 2, 50, 80.0, team="away")
    book.confirm(d1.cooldown_key)
    d2 = book.decide("1", 2, 50, 90.0, team="away")
    assert not d2.can_send
    assert d2.blocked_by == "SAME_MINUTE"


def test_rollback_clears_reservation() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0)
    book = CooldownBook(_clock=lambda: now, reservation_seconds=30)
    d = book.decide("1", 4, 30, 5.0, team="home")
    assert d.can_send
    key = cooldown_key("1", 4, "home")
    # Still reserved
    d2 = book.decide("1", 4, 31, 5.0, team="home")
    assert d2.blocked_by == "RESERVATION"
    book.rollback(key)
    d3 = book.decide("1", 4, 31, 5.0, team="home")
    assert d3.can_send


def test_reservation_expires() -> None:
    start = datetime(2026, 1, 1, 12, 0, 0)
    clock = {"t": start}

    def now() -> datetime:
        return clock["t"]

    book = CooldownBook(_clock=now, reservation_seconds=5)
    d = book.decide("1", 2, 20, 70.0, team="home")
    book.confirm(d.cooldown_key)  # clear reservation but keep state
    clock["t"] = start + timedelta(seconds=1)
    # confirmed — not reserved; still in cooldown window
    d2 = book.decide("1", 2, 21, 71.0, team="home")
    assert d2.blocked_by == "S2_COOLDOWN"
