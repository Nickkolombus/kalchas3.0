"""Scanner enrich adapters for apifootball.com."""

from __future__ import annotations

from kalchas_scanner.enrich import api_events_to_ssot, api_statistics_to_list


def test_statistics_dict_passes_through() -> None:
    payload = {
        "home_team": {"on_target": 2, "corners": 1},
        "away_team": {"on_target": 0, "corners": 0},
    }
    assert api_statistics_to_list(payload) is payload


def test_events_from_match_row() -> None:
    row = {
        "match_hometeam_name": "Home",
        "match_awayteam_name": "Away",
        "match_hometeam_id": 1,
        "match_awayteam_id": 2,
        "goalscorer": [
            {"time": "12", "home_scorer": "A", "away_scorer": "", "score": "1 - 0"},
            {"time": "45+1", "home_scorer": "", "away_scorer": "B", "score": "1 - 1"},
        ],
        "cards": [
            {"time": "30", "home_fault": "C", "card": "yellow card"},
            {"time": "70", "away_fault": "D", "card": "red card"},
        ],
    }
    events = api_events_to_ssot(row, 1, 2)
    goals = [e for e in events if e["event_type"] == "goal"]
    cards = [e for e in events if e["event_type"] == "card"]
    assert len(goals) == 2
    assert goals[0]["side"] == "home" and goals[0]["minute"] == 12
    assert goals[1]["side"] == "away" and goals[1]["minute"] == 46
    assert cards[1]["detail"] == "Red Card"
