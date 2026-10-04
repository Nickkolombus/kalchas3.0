"""Admin live-preview recomputes board cells from in-progress weights."""

from __future__ import annotations

from kalchas_api.preview import preview_live_matches
from kalchas_api.runtime import BoardTuning
from kalchas_core.weights import WeightSet


def _minute(*, home: dict | None = None, away: dict | None = None) -> dict:
    h = home or {}
    a = away or {}
    keys = (
        "attacks",
        "dangerous_attacks",
        "shots_on_target",
        "shots_off_target",
        "corners",
        "fouls",
        "possession",
    )
    return {stat: {"home": h.get(stat, 0), "away": a.get(stat, 0)} for stat in keys}


def test_preview_overlay_moves_urg_and_k(monkeypatch) -> None:
    history = {
        "10": _minute(),
        "20": _minute(
            home={
                "shots_on_target": 8,
                "shots_off_target": 6,
                "corners": 5,
                "dangerous_attacks": 20,
                "attacks": 40,
                "possession": 58,
            },
            away={"possession": 42},
        ),
    }
    row = {
        "match_id": "m1",
        "home_team": "Home",
        "away_team": "Away",
        "minute": 20,
        "home_score": 1,
        "away_score": 0,
        "league_name": "Test",
        "status_short": "1H",
        "odds": {},
    }

    import kalchas_api.runtime
    import kalchas_db.matches

    monkeypatch.setattr(
        kalchas_api.runtime,
        "load_board_tuning",
        lambda: BoardTuning(WeightSet.defaults(), {1: 1.0, 7: 60.0}, {}),
    )
    monkeypatch.setattr(kalchas_db.matches, "list_live_matches_sync", lambda dsn: [row])
    monkeypatch.setattr(kalchas_db.matches, "load_match_history_sync", lambda dsn, mid: history)
    monkeypatch.setattr(kalchas_db.matches, "load_match_events_sync", lambda dsn, mid: [])
    monkeypatch.setattr(kalchas_db.matches, "get_match_sync", lambda dsn, mid: None)

    baseline = preview_live_matches(
        "postgresql://unused",
        strategy_key="rule_of_three",
        overlay={},
    )
    boosted = preview_live_matches(
        "postgresql://unused",
        strategy_key="rule_of_three",
        overlay={"sot_weight": 0.5},
    )
    assert baseline and boosted
    assert boosted[0]["strategy"]["home"] != baseline[0]["strategy"]["home"]
    assert boosted[0]["baseline"]["strategy"]["home"] == baseline[0]["strategy"]["home"]
