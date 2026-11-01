"""Parsers the pre-match watchlist relies on."""

from __future__ import annotations

from kalchas_football.client import (
    FootballAPIClient,
    odds_markets_from_provider_rows,
    parse_standings_table,
    parse_team_fixtures,
    parse_upcoming_fixtures,
)


def test_parse_team_fixtures_keeps_goal_minutes_and_half_time() -> None:
    rows = parse_team_fixtures(
        [
            {
                "match_id": "9",
                "match_date": "2026-10-31",
                "match_status": "Finished",
                "match_hometeam_id": "10",
                "match_awayteam_id": "20",
                "match_hometeam_name": "Alpha",
                "match_awayteam_name": "Beta",
                "match_hometeam_score": "2",
                "match_awayteam_score": "1",
                "match_hometeam_halftime_score": "1",
                "match_awayteam_halftime_score": "1",
                "league_id": "153",
                "goalscorer": [
                    {"time": "7", "home_scorer": "A", "away_scorer": ""},
                    {"time": "45+3", "home_scorer": "", "away_scorer": "B"},
                    {"time": "90+4", "home_scorer": "C", "away_scorer": ""},
                ],
            },
            {
                "match_id": "10",
                "match_date": "2026-11-05",
                "match_status": "",
                "match_hometeam_id": "10",
                "match_awayteam_id": "30",
                "match_hometeam_score": "",
                "match_awayteam_score": "",
                "match_hometeam_halftime_score": "",
                "match_awayteam_halftime_score": "",
            },
        ]
    )
    played, upcoming = rows
    assert played["home_team"] == "Alpha" and played["league_id"] == 153
    assert (played["home_ht_score"], played["away_ht_score"]) == (1, 1)
    assert played["goal_events"] == [
        {"minute": 7, "team": "home", "side": "home", "half": "1H"},
        {"minute": 48, "team": "away", "side": "away", "half": "1H"},
        {"minute": 94, "team": "home", "side": "home", "half": "2H"},
    ]
    assert upcoming["home_ht_score"] is None and upcoming["goal_events"] == []


def test_parse_upcoming_fixtures_skips_rows_without_teams() -> None:
    rows = parse_upcoming_fixtures(
        [
            {
                "match_id": "812255",
                "match_date": "2026-11-03",
                "match_time": "22:45",
                "match_status": "",
                "match_hometeam_id": "3096",
                "match_awayteam_id": "3097",
                "match_hometeam_name": "Blackburn",
                "match_awayteam_name": "Stoke",
                "team_home_badge": "http://apiv3.apifootball.com/badges/3096.jpg",
                "league_id": "153",
                "league_name": "Championship",
                "country_name": "England",
                "match_round": "14",
            },
            {"match_id": "1", "match_hometeam_id": "", "match_awayteam_id": "2"},
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["home_team"] == "Blackburn" and row["league_id"] == 153
    assert row["home_badge"].startswith("https://")
    assert row["round"] == "14"


def test_odds_markets_take_each_market_from_the_first_bookmaker_that_prices_it() -> None:
    out = odds_markets_from_provider_rows(
        [
            {
                "match_id": "1",
                "odd_1": "2.62",
                "odd_x": "3.1",
                "odd_2": "2.62",
                "o+2.5": "",
                "bts_yes": "1.8",
            },
            {
                "match_id": "1",
                "odd_1": "2.5",
                "odd_x": "3.0",
                "odd_2": "2.7",
                "o+2.5": "1.9",
                "u+2.5": "1.95",
            },
            {"match_id": "2", "odd_1": "1.5", "odd_x": "", "odd_2": "6.0", "bts_yes": "2.1"},
        ]
    )
    assert out == {
        "1": {
            "home": 2.62,
            "draw": 3.1,
            "away": 2.62,
            "btts_yes": 1.8,
            "over_2_5": 1.9,
            "under_2_5": 1.95,
        }
    }


def test_parse_standings_table_orders_rows_with_goal_difference() -> None:
    rows = parse_standings_table(
        [
            {
                "team_id": "20",
                "team_name": "Beta",
                "overall_league_position": "2",
                "overall_league_payed": "13",
                "overall_league_GF": "20",
                "overall_league_GA": "15",
                "overall_league_PTS": "25",
            },
            {
                "team_id": "10",
                "team_name": "Alpha",
                "overall_league_position": "1",
                "overall_league_payed": "13",
                "overall_league_GF": "30",
                "overall_league_GA": "17",
                "overall_league_PTS": "28",
            },
        ]
    )
    assert [r["team"] for r in rows] == ["Alpha", "Beta"]
    assert rows[0] == {
        "position": 1,
        "team_id": 10,
        "team": "Alpha",
        "played": 13,
        "goal_difference": 13,
        "points": 28,
    }


def test_missing_standings_read_as_an_empty_table(monkeypatch) -> None:
    class Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"error": 404, "message": "Standing not found!"}

    client = FootballAPIClient(api_key="test-key")
    monkeypatch.setattr(client._client, "get", lambda *a, **k: Resp())
    assert client.get_standings_table(300) == []
