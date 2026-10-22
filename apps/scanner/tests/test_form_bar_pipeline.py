"""Form Bar's team-form pipeline, provider rows to bar reading.

The unit tests on each piece all passed while the pieces together dropped
every fixture (raw ``"Finished"`` never matched the ``FT`` status filter), so
these drive the real client parser, the scanner's cache and the strategy in
one go.
"""

from __future__ import annotations

from typing import Any

import pytest
from kalchas_core.strategies.delta_goal import evaluate
from kalchas_football import FootballAPIClient, RateLimitBudgetExceeded
from kalchas_scanner import loop
from kalchas_scanner.loop import TEAM_FORM_CACHE_HOURS, TEAM_FORM_RETRY_SEC, Scanner

TEAM = 10


def _row(match_id: str, date: str, status: str, home: int, away: int, hs: str, aws: str) -> dict:
    return {
        "match_id": match_id,
        "match_date": date,
        "match_status": status,
        "match_hometeam_id": str(home),
        "match_awayteam_id": str(away),
        "match_hometeam_score": hs,
        "match_awayteam_score": aws,
    }


# apifootball's own get_events shape and status text. Five played -- TEAM
# scored 2, 1, 3, 1, 2 (newest first; median 2) and conceded 1, 1, 0, 0, 2 --
# plus postponed / cancelled / not-yet-played rows that must not count as 0-0.
PROVIDER_ROWS = [
    _row("1", "2026-10-20", "Finished", TEAM, 20, "2", "1"),
    _row("2", "2026-10-17", "After Pen.", 30, TEAM, "1", "1"),
    _row("3", "2026-10-14", "Postponed", TEAM, 60, "", ""),
    _row("4", "2026-10-10", "Finished", 40, TEAM, "0", "3"),
    _row("5", "2026-10-25", "", TEAM, 70, "", ""),
    _row("6", "2026-10-05", "Finished", TEAM, 50, "1", "0"),
    _row("7", "2026-10-01", "Cancelled", 80, TEAM, "", ""),
    _row("8", "2026-09-28", "Finished", TEAM, 90, "2", "2"),
]


class _Provider:
    """Stands in for apifootball behind the real client's `_get`."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls = 0
        self.budget_exhausted = False

    def get(self, action: str, params: dict[str, Any] | None = None) -> list[dict]:
        self.calls += 1
        if self.budget_exhausted:
            raise RateLimitBudgetExceeded(30.0)
        return self.rows


@pytest.fixture
def provider(monkeypatch) -> _Provider:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    return _Provider(PROVIDER_ROWS)


@pytest.fixture
def scanner(provider, monkeypatch):
    client = FootballAPIClient(api_key="test-key")
    monkeypatch.setattr(client, "_get", provider.get)
    yield Scanner(client=client)
    client.close()


@pytest.fixture
def clock(monkeypatch) -> list[float]:
    now = [1000.0]
    monkeypatch.setattr(loop.time, "monotonic", lambda: now[0])
    return now


def test_provider_rows_become_a_real_form_bar_reading(scanner) -> None:
    form = scanner._team_form_for(TEAM)

    assert form is not None, "played fixtures were dropped -- Form Bar would read N/A"
    assert form.scored_by_game == (2, 1, 3, 1, 2)
    assert form.conceded_by_game == (1, 1, 0, 0, 2)

    # No opponent form: expected goals fall back to TEAM's own median, 2.
    result = evaluate(60, home_score=0, home_recent_form=form)
    assert result.home.has_form
    assert result.home.expected_goals == 2.0
    assert result.home.gap == pytest.approx(1.33, abs=0.01)


def test_a_team_with_too_few_played_fixtures_reads_na(provider, scanner) -> None:
    provider.rows = PROVIDER_ROWS[:3]  # one Finished + one After Pen. + one Postponed
    form = scanner._team_form_for(TEAM)
    assert form is not None and form.games_played == 2
    assert not evaluate(60, home_recent_form=form).home.has_form


def test_an_exhausted_budget_is_retried_not_remembered_as_no_form(provider, scanner, clock) -> None:
    provider.budget_exhausted = True
    assert scanner._team_form_for(TEAM) is None
    assert scanner._team_form_for(TEAM) is None
    assert provider.calls == 1, "a failed fetch should back off, not retry every tick"

    provider.budget_exhausted = False
    clock[0] += TEAM_FORM_RETRY_SEC + 1
    form = scanner._team_form_for(TEAM)
    assert form is not None and form.games_played == 5


def test_the_in_process_cache_expires(provider, scanner, clock) -> None:
    assert scanner._team_form_for(TEAM) is not None
    clock[0] += 3600
    scanner._team_form_for(TEAM)
    assert provider.calls == 1

    provider.rows = PROVIDER_ROWS[:1]
    clock[0] += TEAM_FORM_CACHE_HOURS * 3600
    refreshed = scanner._team_form_for(TEAM)
    assert refreshed is not None and refreshed.games_played == 1
    assert provider.calls == 2
