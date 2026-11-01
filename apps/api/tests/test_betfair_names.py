"""Betfair name mapping for the BFbot feed."""

from __future__ import annotations

import httpx
from kalchas_api import betfair_names
from kalchas_api.betfair_names import (
    Fixture,
    correlate,
    match_fixture,
    normalize_name,
    parse_fixtures,
)
from kalchas_api.tips import rows_from_alerts

FIXTURES = [
    Fixture("Man Utd", "Chelsea"),
    Fixture("Estudiantes", "Central Cordoba"),
    Fixture("Boyaca Patriotas", "Alianza Petrolera"),
    Fixture("Charleston Battery", "Louisville City"),
]


def test_normalize_handles_known_aliases() -> None:
    assert normalize_name("Manchester United") == "man utd"
    assert normalize_name("Paris Saint-Germain") == "paris st-g"
    assert normalize_name("Atlético Mineiro") == "atletico mineiro"


def test_exact_match_returns_betfair_spelling() -> None:
    found = match_fixture("Manchester United", "Chelsea", FIXTURES)
    assert found is not None
    assert (found.home, found.away) == ("Man Utd", "Chelsea")
    assert found.method == "gist_exact"
    assert found.fuzzy_applied is False


def test_reversed_order_is_put_back_in_betfair_order() -> None:
    found = match_fixture("Chelsea", "Man United", FIXTURES)
    assert found is not None
    assert (found.home, found.away) == ("Chelsea", "Man Utd")


def test_fuzzy_match_sets_flag() -> None:
    found = match_fixture("Central Cordoba SDE", "Estudiantes L.P.", FIXTURES)
    assert found is not None
    assert (found.home, found.away) == ("Central Cordoba", "Estudiantes")
    assert found.method == "gist_fuzzy"
    assert found.fuzzy_applied is True


def test_short_api_name_matches_longer_betfair_name() -> None:
    found = match_fixture("Patriotas", "Alianza Petrolera", FIXTURES)
    assert found is not None
    assert found.home == "Boyaca Patriotas"


def test_one_shared_word_is_not_enough() -> None:
    fixtures = [Fixture("Paris FC", "Lyon")]
    assert match_fixture("Paris Saint-Germain", "Marseille", fixtures) is None


def test_no_match_falls_back_to_api_names() -> None:
    found = correlate("Unknown Town", "Nowhere Rovers", FIXTURES)
    assert (found.home, found.away, found.method) == ("Unknown Town", "Nowhere Rovers", "none")
    assert found.fuzzy_applied is False


def test_parse_fixtures_skips_rows_without_teams() -> None:
    content = (
        "EventId,EventName,Home,Away,Country,OpenDate,MarketCount\n"
        "1,Mexico v South Africa,Mexico,South Africa,,2026-06-11T19:00:00.000Z,7\n"
        "2,FIFA World Cup,,,,2026-06-28T20:00:00.000Z,8\n"
    )
    fixtures = parse_fixtures(content)
    assert fixtures == [Fixture("Mexico", "South Africa", "2026-06-11T19:00:00.000Z")]


def test_rows_use_betfair_names_when_fixtures_given() -> None:
    rows = rows_from_alerts(
        [
            {
                "match_id": "m1",
                "home_team": "Manchester United",
                "away_team": "Chelsea",
                "score": "0-0",
                "minute": 30,
                "strategy_key": "delta_goal",
                "created_at": "2026-10-10T20:00:00+00:00",
            }
        ],
        FIXTURES,
    )
    assert rows[0]["event_name"] == "Man Utd v Chelsea"
    assert rows[0]["api_home"] == "Manchester United"
    assert rows[0]["correlation_method"] == "gist_exact"


def test_failed_refresh_keeps_last_good_list(monkeypatch) -> None:
    monkeypatch.setattr(
        betfair_names, "_cache", {"at": 0.0, "fixtures": [], "ok": False, "error": None}
    )
    good = "Home,Away,OpenDate\nMan Utd,Chelsea,2026-11-01T15:00:00.000Z\n"
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, text=good)
        return httpx.Response(403, text="<html>blocked</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert len(betfair_names.get_fixtures(client=client)) == 1
    betfair_names._cache["at"] = 0.0  # expire
    assert len(betfair_names.get_fixtures(client=client)) == 1
    assert betfair_names._cache["ok"] is False


def test_womens_and_youth_sides_never_map_to_senior_teams() -> None:
    fixtures = [Fixture("Necaxa", "Santos Laguna"), Fixture("Las Palmas", "Atletico Central")]
    assert match_fixture("Necaxa W", "Santos Laguna W", fixtures) is None
    assert match_fixture("Las Palmas B", "Atletico Central", fixtures) is None
    assert match_fixture("Necaxa U19", "Santos Laguna U19", fixtures) is None
    womens = [Fixture("Necaxa W", "Santos Laguna W")]
    found = match_fixture("Necaxa Women", "Santos Laguna W", womens)
    assert found is not None
    assert found.home == "Necaxa W"


def test_one_similar_team_is_not_enough() -> None:
    fixtures = [Fixture("Kocaelispor", "Eyupspor")]
    assert match_fixture("Kocaelispor", "Rizespor", fixtures) is None
