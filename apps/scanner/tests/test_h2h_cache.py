"""Alert-time H2H shares the match panel's cache row.

An alert that fetches H2H must leave the full panel payload behind, so the
board's H2H tab reads it instead of calling get_H2H again, and the reverse.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from kalchas_db import panel_cache
from kalchas_scanner.loop import Scanner

HOME, AWAY = 11, 22


def _meeting(i: int, home: int, away: int, hs: int, aws: int) -> dict:
    return {
        "match_id": str(i),
        "home_team": "Home FC" if home == HOME else "Away FC",
        "away_team": "Away FC" if away == AWAY else "Home FC",
        "home_team_id": home,
        "away_team_id": away,
        "home_score": hs,
        "away_score": aws,
        "match_date": f"2026-0{i}-01",
    }


# Home FC: 3 wins, 1 draw, 2 losses; 9 goals for, 6 against over 6 meetings.
MEETINGS = [
    _meeting(1, HOME, AWAY, 2, 0),
    _meeting(2, AWAY, HOME, 1, 2),
    _meeting(3, HOME, AWAY, 1, 1),
    _meeting(4, AWAY, HOME, 2, 1),
    _meeting(5, HOME, AWAY, 2, 0),
    _meeting(6, AWAY, HOME, 2, 1),
]


class _Client:
    def __init__(self) -> None:
        self.calls = 0

    def get_head_to_head(self, team1: int, team2: int, *, last: int) -> list[dict]:
        self.calls += 1
        return MEETINGS


@pytest.fixture
def store(monkeypatch) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(panel_cache, "load_panel_cache", lambda dsn, key, **_: rows.get(key))
    monkeypatch.setattr(
        panel_cache, "save_panel_cache", lambda dsn, key, payload: rows.__setitem__(key, payload)
    )
    return rows


def _match() -> SimpleNamespace:
    return SimpleNamespace(
        match_id="m1",
        home_team="Home FC",
        away_team="Away FC",
        home_team_id=HOME,
        away_team_id=AWAY,
    )


def test_alert_fetch_fills_the_panel_cache(store) -> None:
    client = _Client()
    snippet = Scanner(client=client)._h2h_for_alert(_match())

    assert client.calls == 1
    assert snippet == {
        "sample": 6,
        "home_avg": 1.5,
        "away_avg": 1.0,
        "home_wins": 3,
        "draws": 1,
        "away_wins": 2,
    }
    row = store[panel_cache.pair_cache_key("h2h", HOME, AWAY)]
    assert row["summary"] == {"home_wins": 3, "draws": 1, "away_wins": 2, "sample": 6}
    assert len(row["fixtures"]) == 6
    assert "over_2_5" in row["patterns"]


def test_a_cached_panel_row_costs_no_fetch(store) -> None:
    Scanner(client=_Client())._h2h_for_alert(_match())
    client = _Client()

    again = Scanner(client=client)._h2h_for_alert(_match())

    assert client.calls == 0
    assert again is not None and again["home_wins"] == 3


def test_reverse_fixture_reads_the_cached_row_from_its_own_home_side(store) -> None:
    Scanner(client=_Client())._h2h_for_alert(_match())
    reverse = SimpleNamespace(
        match_id="m2",
        home_team="Away FC",
        away_team="Home FC",
        home_team_id=AWAY,
        away_team_id=HOME,
    )
    client = _Client()

    snippet = Scanner(client=client)._h2h_for_alert(reverse)

    assert client.calls == 0
    assert snippet == {
        "sample": 6,
        "home_avg": 1.0,
        "away_avg": 1.5,
        "home_wins": 2,
        "draws": 1,
        "away_wins": 3,
    }


def test_thin_samples_are_not_cached(store) -> None:
    client = _Client()
    client.get_head_to_head = lambda *a, **k: MEETINGS[:3]  # type: ignore[method-assign]

    assert Scanner(client=client)._h2h_for_alert(_match()) is None
    assert store == {}
