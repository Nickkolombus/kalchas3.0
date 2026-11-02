"""Watchlist builder: what it fetches, caches, freezes, settles and archives."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from kalchas_football import RateLimitBudgetExceeded
from kalchas_scanner.watchlist import (
    MemoryCache,
    MemoryStore,
    WatchlistBuilder,
    kickoff_iso,
)

DAY = date(2026, 11, 3)
BEFORE = datetime(2026, 11, 2, 20, tzinfo=UTC)
DURING = datetime(2026, 11, 3, 20, tzinfo=UTC)  # 23:00 in +03:00: 100 and 101 kicked off
AFTER = datetime(2026, 11, 4, 3, tzinfo=UTC)


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


def upcoming(
    match_id: str, home: int, away: int, league_id: int, league: str, clock: str = "22:45"
) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "match_date": "2026-11-03",
        "match_time": clock,
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


def result(match_id: str, status: str, h: int | None, a: int | None) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "status_short": status,
        "home_90": h,
        "away_90": a,
        "home_final": h,
        "away_final": a,
        "home_ht": 1 if h else 0,
        "away_ht": 0,
        "home_pens": None,
        "away_pens": None,
        "goals": [],
    }


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.cup_budget_spent = False
        self.priced = {"100", "101"}
        self.results: list[dict[str, Any]] = []
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
        prices = {
            "100": {"home": 1.9, "draw": 3.5, "away": 4.0},
            "101": {"home": 1.5, "draw": 4.0, "away": 6.0},
        }
        return {k: v for k, v in prices.items() if k in self.priced}

    def get_results_on(self, day: str, *, timezone: str) -> list[dict[str, Any]]:
        self.calls.append(("results", day))
        return self.results

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


def builder(client: FakeClient, store: MemoryStore | None = None) -> WatchlistBuilder:
    return WatchlistBuilder(
        client,  # type: ignore[arg-type]
        MemoryCache(),
        store or MemoryStore(),
        records=lambda: ({("England", "Championship"): {"confirmed": 30, "settled": 45}}, None),
    )


def page(b: WatchlistBuilder, match_id: str) -> dict[str, Any]:
    return b.store.pages[match_id][1]  # type: ignore[attr-defined]


def test_builds_priced_matches_into_day_and_match_rows() -> None:
    b = builder(FakeClient())
    doc = b.build_day(DAY, now=BEFORE)
    assert doc is not None
    assert [m["match_id"] for m in doc["matches"]] == ["100", "101"]
    assert doc["partial"] is False
    assert b.store.days["2026-11-03"] == doc  # type: ignore[attr-defined]
    assert doc["summary"]["matches"] == 2

    first = page(b, "100")
    assert first["kickoff"] == "2026-11-03T22:45:00+03:00"
    assert first["points"][0]["key"] == "btts_yes"
    assert first["result"] is None
    assert doc["matches"][0]["tags"][0] == {"label": "Both score", "outcome": None}


def test_cup_teams_with_few_games_fall_back_to_all_competitions() -> None:
    client = FakeClient()
    b = builder(client)
    b.build_day(DAY, now=BEFORE)
    assert ("team", 8) in client.calls and ("team", 9) in client.calls
    assert ("team", 1) not in client.calls
    assert page(b, "101")["form"]["home"]["source"] == "all"


def test_rebuild_reuses_cached_reads() -> None:
    client = FakeClient()
    b = builder(client)
    b.build_day(DAY, now=BEFORE)
    first = len(client.calls)
    b.build_day(DAY, now=BEFORE)
    reads = [c for c in client.calls[first:] if c[0] != "fixtures"]
    assert reads == []


def test_spent_budget_marks_the_day_partial_instead_of_failing() -> None:
    client = FakeClient()
    client.cup_budget_spent = True
    doc = builder(client).build_day(DAY, now=BEFORE)
    assert doc is not None
    assert doc["partial"] is True
    assert [m["match_id"] for m in doc["matches"]] == ["100"]


def test_started_matches_are_frozen_and_stay_listed() -> None:
    client = FakeClient()
    b = builder(client)
    b.build_day(DAY, now=BEFORE)
    before = page(b, "100")
    # During the game the price is gone and the fixture reads live: the page
    # the list showed before kick-off is kept as it was.
    client.priced = set()
    doc = b.build_day(DAY, now=DURING)
    assert doc is not None
    assert [m["match_id"] for m in doc["matches"]] == ["100", "101"]
    assert page(b, "100") is before


def test_a_match_that_loses_its_price_before_kick_off_leaves_the_list() -> None:
    client = FakeClient()
    b = builder(client)
    b.build_day(DAY, now=BEFORE)
    client.priced = {"100"}
    doc = b.build_day(DAY, now=BEFORE)
    assert doc is not None
    assert [m["match_id"] for m in doc["matches"]] == ["100"]
    assert "101" not in b.store.pages  # type: ignore[attr-defined]


def test_nothing_is_added_after_kick_off() -> None:
    doc = builder(FakeClient()).build_day(DAY, now=DURING)
    assert doc is not None
    assert doc["matches"] == []


def test_settling_adds_scores_and_outcomes_with_one_call() -> None:
    client = FakeClient()
    b = builder(client)
    b.build_day(DAY, now=BEFORE)
    client.results = [result("100", "FT", 2, 1), result("101", "PST", None, None)]
    assert b.settle_day(DAY, now=AFTER) == 2
    assert [c for c in client.calls if c[0] == "results"] == [("results", "2026-11-03")]

    settled = page(b, "100")
    assert settled["result"]["label"] == "FT"
    assert settled["points"][0]["outcome"] == "landed"
    assert settled["points"][0]["outcome_note"] == "Both teams scored."

    doc = b.store.days["2026-11-03"]  # type: ignore[attr-defined]
    row = doc["matches"][0]
    assert row["result"] == {
        "status": "finished",
        "label": "FT",
        "home": 2,
        "away": 1,
        "pens": None,
    }
    assert row["outcome"] == "landed"
    assert doc["matches"][1]["result"]["label"] == "Postponed"
    assert doc["summary"]["finished"] == 1 and doc["summary"]["called_off"] == 1


def test_settling_waits_for_the_final_whistle_and_skips_settled_pages() -> None:
    client = FakeClient()
    b = builder(client)
    b.build_day(DAY, now=BEFORE)
    assert b.settle_day(DAY, now=DURING) == 0
    assert ("results", "2026-11-03") not in client.calls

    client.results = [result("100", "2H", 1, 0), result("101", "FT", 0, 0)]
    assert b.settle_day(DAY, now=AFTER) == 1
    client.results = [result("100", "FT", 1, 0)]
    assert b.settle_day(DAY, now=AFTER) == 1
    calls = len(client.calls)
    assert b.settle_day(DAY, now=AFTER) == 0
    assert len(client.calls) == calls


def test_adopt_fills_only_days_the_archive_lacks() -> None:
    client = FakeClient()
    b = builder(client)
    b.build_day(DAY, now=BEFORE)
    old = {**page(b, "100"), "match_id": "900", "day": "2026-11-02"}
    again = {**page(b, "100"), "match_id": "901"}
    assert b.adopt([old, again]) == ["2026-11-02"]
    assert b.store.days["2026-11-02"]["shortlist"] == ["900"]  # type: ignore[attr-defined]
    assert "901" not in b.store.pages  # type: ignore[attr-defined]


def test_kickoff_iso_tolerates_missing_time() -> None:
    assert kickoff_iso({"match_date": "2026-11-03", "match_time": "TBD"}, "+03:00") == (
        "2026-11-03T00:00:00+03:00"
    )


def test_a_match_with_no_result_two_days_on_is_marked_so() -> None:
    client = FakeClient()
    b = builder(client)
    b.build_day(DAY, now=BEFORE)
    client.results = [result("100", "UNK", None, None)]
    assert b.settle_day(DAY, now=AFTER) == 0
    assert b.settle_day(DAY, now=datetime(2026, 11, 6, tzinfo=UTC)) == 2
    assert page(b, "100")["result"] == {"status": "off", "label": "No result"}
    assert page(b, "100")["points"][0]["outcome"] is None
