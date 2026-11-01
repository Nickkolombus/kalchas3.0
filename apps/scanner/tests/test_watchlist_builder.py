"""Watchlist builder: what it fetches, caches and stores for a day."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from kalchas_football import RateLimitBudgetExceeded
from kalchas_scanner.watchlist import (
    MemoryCache,
    WatchlistBuilder,
    day_cache_key,
    kickoff_iso,
    match_cache_key,
)


def played(match_id: str, home: int, away: int, hs: int, as_: int, day: int) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "match_date": f"2026-10-{day:02d}",
        "status_short": "FT",
        "home_team_id": home,
        "away_team_id": away,
        "home_team": f"T{home}",
        "away_team": f"T{away}",
        "home_score": hs,
        "away_score": as_,
        "home_ht_score": None,
        "away_ht_score": None,
        "goal_events": [],
    }


def upcoming(match_id: str, home: int, away: int, league_id: int, league: str) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "match_date": "2026-11-03",
        "match_time": "22:45",
        "status_short": "",
        "home_team_id": home,
        "away_team_id": away,
        "home_team": f"T{home}",
        "away_team": f"T{away}",
        "home_badge": None,
        "away_badge": None,
        "league_id": league_id,
        "league_name": league,
        "country_name": "England",
        "league_logo": None,
        "round": "15",
    }


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.cup_budget_spent = False
        # League 1: teams 1 and 2 play ten games each, both teams scoring every time.
        self.league = [played(f"a{i}", 1, 50 + i, 2, 1, 28 - i) for i in range(10)] + [
            played(f"b{i}", 70 + i, 2, 1, 1, 28 - i) for i in range(10)
        ]

    def get_fixtures_on(self, day: str, *, timezone: str) -> list[dict[str, Any]]:
        self.calls.append(("fixtures", day))
        return [
            upcoming("100", 1, 2, 1, "Championship"),
            upcoming("101", 8, 9, 7, "Challenge Cup"),
            upcoming("102", 3, 4, 1, "Championship"),
        ]

    def get_odds_markets_on(self, day: str) -> dict[str, dict[str, float]]:
        # 102 has no price, so it is not on the list.
        return {
            "100": {"home": 1.9, "draw": 3.5, "away": 4.0},
            "101": {"home": 1.5, "draw": 4.0, "away": 6.0},
        }

    def get_league_fixtures(self, league_id: int, *, days_back: int) -> list[dict[str, Any]]:
        self.calls.append(("league", league_id))
        if league_id == 7:
            if self.cup_budget_spent:
                raise RateLimitBudgetExceeded(10)
            return [played("c1", 8, 9, 1, 0, 20)]
        return self.league

    def get_team_fixtures(self, team_id: int, *, days_back: int) -> list[dict[str, Any]]:
        self.calls.append(("team", team_id))
        return [played(f"t{team_id}-{i}", team_id, 200 + i, 3, 2, 28 - i) for i in range(10)]

    def get_standings_table(self, league_id: int) -> list[dict[str, Any]]:
        self.calls.append(("table", league_id))
        return []

    def get_head_to_head(self, a: int, b: int, *, last: int) -> list[dict[str, Any]]:
        self.calls.append(("h2h", (a, b)))
        return []


def build(client: FakeClient, cache: MemoryCache | None = None) -> tuple[dict, MemoryCache]:
    cache = cache or MemoryCache()
    builder = WatchlistBuilder(
        client,  # type: ignore[arg-type]
        cache,
        records=lambda: ({("England", "Championship"): {"confirmed": 30, "settled": 45}}, None),
    )
    doc = builder.build_day(date(2026, 11, 3), now=datetime(2026, 11, 2, 20, tzinfo=UTC))
    assert doc is not None
    return doc, cache


def test_builds_priced_matches_into_day_and_match_rows() -> None:
    doc, cache = build(FakeClient())
    assert [m["match_id"] for m in doc["matches"]] == ["100", "101"]
    assert doc["partial"] is False
    assert cache.rows[day_cache_key("2026-11-03")] == doc

    page = cache.rows[match_cache_key("100")]
    assert page["kickoff"] == "2026-11-03T22:45:00+03:00"
    assert page["points"][0]["key"] == "btts_yes"
    assert page["record"]["league"] == {"confirmed": 30, "settled": 45}
    league = next(lg for lg in doc["leagues"] if lg["key"] == "1:Championship")
    assert league["record"] == {"confirmed": 30, "settled": 45}


def test_cup_teams_with_few_games_fall_back_to_all_competitions() -> None:
    client = FakeClient()
    _, cache = build(client)
    assert ("team", 8) in client.calls and ("team", 9) in client.calls
    assert ("team", 1) not in client.calls
    page = cache.rows[match_cache_key("101")]
    assert page["form"]["home"]["source"] == "all"


def test_rebuild_reuses_cached_reads() -> None:
    client = FakeClient()
    _, cache = build(client)
    first = len(client.calls)
    build(client, cache)
    reads = [c for c in client.calls[first:] if c[0] != "fixtures"]
    assert reads == []


def test_spent_budget_marks_the_day_partial_instead_of_failing() -> None:
    client = FakeClient()
    client.cup_budget_spent = True
    doc, _ = build(client)
    assert doc["partial"] is True
    assert [m["match_id"] for m in doc["matches"]] == ["100"]


def test_kickoff_iso_tolerates_missing_time() -> None:
    assert kickoff_iso({"match_date": "2026-11-03", "match_time": "TBD"}, "+03:00") == (
        "2026-11-03T00:00:00+03:00"
    )
