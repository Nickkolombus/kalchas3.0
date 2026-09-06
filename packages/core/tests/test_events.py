"""Goal/card conversion, cleaning, and TSLG."""

from __future__ import annotations

from kalchas_core.events import (
    clean_goal_events,
    compute_tslg_status,
    convert_ssot_events,
    tally_red_cards,
)


def test_convert_ssot_events_maps_side_to_team_names() -> None:
    ssot_events = [
        {
            "event_type": "goal",
            "minute": 23,
            "side": "home",
            "player_name": "A. Davies",
            "detail": "1-0",
        },
        {
            "event_type": "goal",
            "minute": 44,
            "side": "away",
            "player_name": "Almoez Ali",
            "detail": "1-1",
        },
        {
            "event_type": "card",
            "minute": 12,
            "side": "home",
            "player_name": "Eustaqio",
            "detail": "yellow card",
        },
    ]
    goal_events, card_events = convert_ssot_events(
        ssot_events, home_team="Canada", away_team="Qatar"
    )
    assert len(goal_events) == 2
    assert len(card_events) == 1
    assert goal_events[0]["team"] == "Canada"
    assert goal_events[0]["side"] == "home"
    assert goal_events[0]["time"] == 23
    assert goal_events[1]["team"] == "Qatar"
    assert card_events[0]["team"] == "Canada"


def test_convert_ssot_events_without_team_names_keeps_side() -> None:
    goal_events, _ = convert_ssot_events([{"event_type": "goal", "minute": 10, "side": "home"}])
    assert goal_events[0]["team"] == "home"


def test_tally_red_cards() -> None:
    cards = [
        {"team": "Home", "detail": "Red Card"},
        {"team": "Away", "detail": "Second Yellow card / Red"},
        {"team": "Home", "detail": "Yellow Card"},
    ]
    assert tally_red_cards(cards, "Home", "Away") == {"home": 1, "away": 1}


def test_clean_goal_events_dedup_same_side_within_window() -> None:
    raw = [
        {"minute": 16, "side": "home"},
        {"minute": 15, "side": "home"},
        {"minute": 44, "side": "away"},
    ]
    cleaned = clean_goal_events(raw)
    assert len(cleaned) == 2
    assert cleaned[0]["minute"] == 15
    assert cleaned[1]["minute"] == 44


def test_clean_goal_events_cap_by_score() -> None:
    raw = [
        {"minute": 12, "side": "home"},
        {"minute": 23, "side": "home"},
        {"minute": 34, "side": "home"},
        {"minute": 17, "side": "away"},
        {"minute": 29, "side": "away"},
    ]
    cleaned = clean_goal_events(raw, home_score=2, away_score=1)
    assert len([e for e in cleaned if e["side"] == "home"]) == 2
    assert len([e for e in cleaned if e["side"] == "away"]) == 1


def test_clean_goal_events_keeps_sides_independent() -> None:
    cleaned = clean_goal_events([{"minute": 15, "side": "home"}, {"minute": 16, "side": "away"}])
    assert len(cleaned) == 2


def test_tslg_from_goal_events() -> None:
    match = {
        "home_team": "HomeTeam",
        "away_team": "AwayTeam",
        "goal_events": [
            {"time": 20, "team": "HomeTeam", "type": "Goal"},
            {"time": 50, "team": "AwayTeam", "type": "Goal"},
            {"time": 70, "team": "HomeTeam", "type": "Goal"},
        ],
    }
    status = compute_tslg_status(match, minute=75)
    assert status["home_minutes"] == 5
    assert status["away_minutes"] == 25
    assert status["display"] == "5' - 25'"
    assert status["last_goal"] == {"side": "home", "minute": 70, "team": "HomeTeam"}


def test_tslg_scoreless_renders_dash() -> None:
    match = {"home_team": "HomeTeam", "away_team": "AwayTeam", "goal_events": []}
    status = compute_tslg_status(match, minute=36)
    assert status["home_minutes"] is None
    assert status["away_minutes"] is None
    assert status["display"] == "— - —"
    assert status["cooldown_active"] is False


def test_tslg_unknown_timing_with_score_still_dash() -> None:
    match = {
        "home_team": "HomeTeam",
        "away_team": "AwayTeam",
        "home_score": 1,
        "away_score": 0,
        "goal_events": [],
    }
    status = compute_tslg_status(match, minute=11)
    assert status["display"] == "— - —"


def test_tslg_minute_by_minute_fallback() -> None:
    match = {
        "home_team": "HomeTeam",
        "away_team": "AwayTeam",
        "goal_events": [],
        "minute_by_minute": {
            "10": {"score": {"home": 0, "away": 0}},
            "20": {"score": {"home": 1, "away": 0}},
            "50": {"score": {"home": 1, "away": 1}},
            "70": {"score": {"home": 2, "away": 1}},
        },
    }
    status = compute_tslg_status(match, minute=75)
    assert status["home_minutes"] == 5
    assert status["away_minutes"] == 25


def test_tslg_cooldown_active_after_recent_goal() -> None:
    match = {
        "home_team": "HomeTeam",
        "away_team": "AwayTeam",
        "goal_events": [{"time": 32, "team": "HomeTeam", "type": "Goal"}],
    }
    status = compute_tslg_status(match, minute=36, cooldown_minutes=10)
    assert status["home_minutes"] == 4
    assert status["cooldown_active"] is True


def test_tslg_side_only_events() -> None:
    match = {
        "home_team": "Canada",
        "away_team": "Qatar",
        "goal_events": [
            {"time": 12, "side": "home", "team": "home", "type": "Goal"},
            {"time": 44, "side": "home", "team": "home", "type": "Goal"},
            {"time": 52, "side": "away", "team": "away", "type": "Goal"},
            {"time": 64, "side": "home", "team": "home", "type": "Goal"},
        ],
    }
    status = compute_tslg_status(match, minute=64)
    assert status["home_minutes"] == 0
    assert status["away_minutes"] == 12
    assert status["last_goal"] == {"side": "home", "minute": 64, "team": "Canada"}


def test_tslg_caps_phantom_home_event() -> None:
    match = {
        "home_team": "Brunswick Juventus",
        "away_team": "Bulleen",
        "home_score": 0,
        "away_score": 1,
        "current_minute": 17,
        "goal_events": [
            {"minute": 13, "side": "home", "team": "Brunswick Juventus"},
        ],
        "minute_by_minute": {
            "12": {"score": "0-0"},
            "13": {"score": "0-1"},
            "14": {"score": "0-1"},
            "17": {"score": "0-1"},
        },
    }
    status = compute_tslg_status(match)
    assert status["home_minutes"] is None
    assert status["away_minutes"] == 4
    assert status["display"] == "— - 4'"
    assert status["cooldown_active"] is True
    assert status["last_goal"] == {"side": "away", "minute": 13, "team": "Bulleen"}
