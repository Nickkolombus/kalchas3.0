"""apifootball.com client unit tests (no network)."""

from __future__ import annotations

from kalchas_football.client import (
    _parse_elapsed,
    live_match_from_event,
    statistics_to_team_dict,
)


def test_parse_elapsed_plain_minute() -> None:
    assert _parse_elapsed("67") == (67, "2H")


def test_parse_elapsed_stoppage() -> None:
    assert _parse_elapsed("45+2") == (47, "1H")


def test_parse_elapsed_half_time() -> None:
    assert _parse_elapsed("Half Time") == (0, "HT")


def test_live_match_from_event() -> None:
    row = {
        "match_id": "123",
        "match_hometeam_name": "Alpha",
        "match_awayteam_name": "Beta",
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": "1",
        "match_awayteam_score": "0",
        "match_status": "55",
        "league_name": "Championship",
    }
    match = live_match_from_event(row)
    assert match is not None
    assert match.match_id == "123"
    assert match.home_team == "Alpha"
    assert match.minute == 55
    assert match.status_short == "2H"
    assert match.home_score == 1


def test_finished_rows_are_dropped_from_live_list(monkeypatch) -> None:
    from kalchas_football.client import FootballAPIClient

    client = FootballAPIClient(api_key="test-key")
    monkeypatch.setattr(
        client,
        "_get",
        lambda action, params=None: [
            {
                "match_id": "1",
                "match_hometeam_name": "A",
                "match_awayteam_name": "B",
                "match_hometeam_id": "1",
                "match_awayteam_id": "2",
                "match_hometeam_score": "1",
                "match_awayteam_score": "0",
                "match_status": "Finished",
                "league_name": "PL",
            },
            {
                "match_id": "2",
                "match_hometeam_name": "C",
                "match_awayteam_name": "D",
                "match_hometeam_id": "3",
                "match_awayteam_id": "4",
                "match_hometeam_score": "0",
                "match_awayteam_score": "0",
                "match_status": "33",
                "league_name": "Championship",
            },
        ],
    )
    live = client.get_live_fixtures()
    assert len(live) == 1
    assert live[0].match_id == "2"
    client.close()


def test_statistics_to_team_dict_maps_aliases() -> None:
    raw = [
        {"type": "On Target", "home": "3", "away": "1"},
        {"type": "Corner Kicks", "home": "5", "away": "2"},
        {"type": "Dangerous Attacks", "home": "20", "away": "8"},
        {"type": "Ball Possession", "home": "58%", "away": "42%"},
    ]
    out = statistics_to_team_dict(raw)
    assert out["home_team"]["on_target"] == 3
    assert out["home_team"]["corners"] == 5
    assert out["away_team"]["dangerous_attacks"] == 8
    assert out["home_team"]["ball_possession"] == 58
