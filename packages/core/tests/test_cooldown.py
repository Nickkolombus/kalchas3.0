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


def test_omega_ignores_value_delta_bypass() -> None:
    book = CooldownBook()
    d1 = book.decide("1", 6, 40, 0.8, team="home")
    book.confirm(d1.cooldown_key)
    d2 = book.decide("1", 6, 42, 2.6, team="home")
    assert not d2.can_send
    assert d2.blocked_by == "STILL_SURGING"


def test_omega_rearms_only_after_the_surge_drops() -> None:
    book = CooldownBook()
    d1 = book.decide("1", 6, 40, 0.80, team="home")
    book.confirm(d1.cooldown_key)
    assert not book.decide("1", 6, 50, 0.70, team="home").can_send
    assert book.decide("1", 6, 50, 0.70, team="home").blocked_by == "STILL_SURGING"
    cooled = book.decide("1", 6, 56, 0.30, team="home")
    assert cooled.can_send
    book.confirm(cooled.cooldown_key)
    assert not book.decide("1", 6, 58, 0.75, team="home").can_send


def test_delta5_same_surge_does_not_refire_on_tiny_increase() -> None:
    book = CooldownBook()
    first = book.decide("1", 4, 75, 7.0, team="home")
    assert first.can_send
    book.confirm(first.cooldown_key)
    second = book.decide("1", 4, 76, 8.0, team="home")
    assert not second.can_send
    assert second.blocked_by == "STILL_SURGING"


def test_team_stack_blocks_k_after_component_alert() -> None:
    book = CooldownBook()
    first = book.decide("1", 4, 75, 8.0, team="home")
    assert first.can_send
    book.confirm(first.cooldown_key)
    stacked = book.decide("1", 7, 75, 60.0, team="home")
    assert not stacked.can_send
    assert stacked.blocked_by == "TEAM_STACK"
    other_side = book.decide("1", 7, 75, 60.0, team="away")
    assert other_side.can_send
    omega = book.decide("1", 6, 75, 0.9, team="home")
    assert omega.can_send


def test_team_stack_clears_after_window() -> None:
    book = CooldownBook()
    first = book.decide("1", 4, 70, 8.0, team="home")
    book.confirm(first.cooldown_key)
    assert not book.decide("1", 7, 79, 62.0, team="home").can_send
    later = book.decide("1", 7, 80, 62.0, team="home")
    assert later.can_send


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
