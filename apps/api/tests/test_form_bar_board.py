"""The live board's own Form Bar lookup (independent of the scanner's)."""

from __future__ import annotations

from typing import Any

import kalchas_db.panel_cache as panel_cache
import kalchas_football
import pytest
from kalchas_api.team_form import team_form_for_board
from kalchas_football import RateLimitBudgetExceeded

ROWS = [
    {
        "match_id": str(i),
        "match_date": f"2026-10-{20 - i:02d}",
        "match_status": status,
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": hs,
        "match_awayteam_score": "0" if hs else "",
    }
    for i, (status, hs) in enumerate(
        [("Finished", "2"), ("After ET", "1"), ("Postponed", ""), ("Finished", "1")]
    )
]


@pytest.fixture
def saved(monkeypatch) -> dict[str, Any]:
    store: dict[str, Any] = {}
    monkeypatch.setattr(panel_cache, "load_panel_cache", lambda dsn, key, ttl_hours: None)
    monkeypatch.setattr(
        panel_cache, "save_panel_cache", lambda dsn, key, payload: store.update({key: payload})
    )
    return store


def _client_returning(monkeypatch, get) -> None:
    class FakeClient(kalchas_football.FootballAPIClient):
        def __init__(self) -> None:
            super().__init__(api_key="test-key")
            self._get = get  # type: ignore[method-assign]

    monkeypatch.setattr(kalchas_football, "FootballAPIClient", FakeClient)


def test_provider_rows_become_form(monkeypatch, saved) -> None:
    _client_returning(monkeypatch, lambda action, params=None: ROWS)
    form = team_form_for_board("postgres://unused", 10)
    assert form is not None
    assert form.games_played == 3
    assert form.scored_by_game == (2, 1, 1)
    assert saved == {"team_form_v3_10": {"scored": [2, 1, 1], "conceded": [0, 0, 0]}}


def test_an_exhausted_budget_is_not_cached(monkeypatch, saved) -> None:
    def exhausted(action, params=None):
        raise RateLimitBudgetExceeded(30.0)

    _client_returning(monkeypatch, exhausted)
    assert team_form_for_board("postgres://unused", 10) is None
    assert saved == {}


def test_cache_only_reads_never_call_the_provider(monkeypatch, saved) -> None:
    """The match panel promises no provider calls."""

    def must_not_fetch(action, params=None):
        raise AssertionError("provider called from a cache-only read")

    _client_returning(monkeypatch, must_not_fetch)
    assert team_form_for_board("postgres://unused", 10, fetch=False) is None
    assert saved == {}
