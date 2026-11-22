"""After a restart the scanner rebuilds its cooldown memory from recent alerts.

Without it every deploy forgot who had alerted, so a once-per-half strategy
could fire again in the same half.
"""

from __future__ import annotations

from typing import Any

import kalchas_db.alerts as alerts_db
import kalchas_db.settings as settings_db
import pytest
from kalchas_core.cooldown import CooldownBook, CooldownRules
from kalchas_scanner.loop import Scanner


def _bundle(dsn: str) -> dict[str, Any]:
    return {
        "rules": [
            {
                "strategy_slot": 7,
                "strategy_name": "K-Index",
                "success_window_minutes": 20,
                "expiration_buffer_minutes": 2,
                "infinite_ttl": False,
                "team_specific": True,
                "expire_at_half_end": True,
                "max_fire_minute": 85,
                "max_fire_minute_1h": None,
                "enabled": True,
                "cooldown_minutes": 10,
                "cooldown_bypass_delta": 5.0,
                "once_per_half": True,
            }
        ]
    }


@pytest.fixture
def recent(monkeypatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(settings_db, "load_runtime_bundle", _bundle)
    monkeypatch.setattr(settings_db, "config_fingerprints", lambda bundle: {})
    monkeypatch.setattr(settings_db, "get_board_settings", lambda dsn: {})
    monkeypatch.setattr(
        alerts_db, "list_recent_alerts_for_cooldown_sync", lambda dsn, hours: list(rows)
    )
    return rows


def test_restart_remembers_an_alert_from_this_half(recent) -> None:
    recent.append(
        {
            "match_id": "m1",
            "strategy_slot": 7,
            "team": "home",
            "value": 56.0,
            "minute": 20,
            "status_short": "1H",
            "created_at": None,
        }
    )
    scanner = Scanner(client=object())
    scanner._refresh_tuning()

    assert scanner.cooldown.rules_for(7).once_per_half
    again = scanner.cooldown.decide("m1", 7, 35, 70.0, team="home", first_half=True)
    assert again.blocked_by == "S7_ONCE_PER_HALF"
    assert scanner.cooldown.decide("m1", 7, 55, 60.0, team="home", first_half=False).can_send
    assert scanner.cooldown.decide("m1", 7, 36, 60.0, team="away", first_half=True).can_send


def test_half_time_alert_counts_as_first_half(recent) -> None:
    recent.append(
        {
            "match_id": "m2",
            "strategy_slot": 7,
            "team": "away",
            "value": 55.0,
            "minute": 47,
            "status_short": "HT",
            "created_at": None,
        }
    )
    scanner = Scanner(client=object())
    scanner._refresh_tuning()
    assert not scanner.cooldown.decide("m2", 7, 48, 60.0, team="away", first_half=True).can_send
    assert scanner.cooldown.decide("m2", 7, 52, 60.0, team="away", first_half=False).can_send


def test_seeds_once_and_retries_after_a_failure(recent, monkeypatch) -> None:
    calls = {"n": 0}

    def flaky(dsn: str, hours: int) -> list[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db down")
        return []

    monkeypatch.setattr(alerts_db, "list_recent_alerts_for_cooldown_sync", flaky)
    scanner = Scanner(client=object())
    scanner._refresh_tuning()
    assert not scanner._cooldown_seeded
    scanner._tuning_at = 0.0
    scanner._refresh_tuning()
    assert scanner._cooldown_seeded
    scanner._tuning_at = 0.0
    scanner._refresh_tuning()
    assert calls["n"] == 2


def test_latest_alert_wins() -> None:
    book = CooldownBook(rules={1: CooldownRules(strategy_slot=1, base_cooldown_minutes=10)})
    book.seed("m", 1, team="home", minute=20, value=1.0, first_half=True)
    book.seed("m", 1, team="home", minute=40, value=1.2, first_half=True)
    blocked = book.decide("m", 1, 45, 1.2, team="home", first_half=True)
    assert blocked.blocked_by == "S1_COOLDOWN"
    assert blocked.next_allowed_minute == 50
