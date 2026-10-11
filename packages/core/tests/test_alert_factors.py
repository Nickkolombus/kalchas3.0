from kalchas_core.alert_factors import (
    compact_board,
    csv_row,
    factors_from_payload,
    pattern_summary,
)


def test_compact_board_keeps_values_and_fire_flags() -> None:
    board = compact_board(
        {
            "strategy_status": {
                "omega": {
                    "teams": {
                        "home": {"value": 31, "triggered": True},
                        "away": {"value": 4, "triggered": False},
                    }
                },
                "kscore": {
                    "teams": {
                        "home": {"value": 72, "triggered": True},
                        "away": {"value": 11, "triggered": False},
                    },
                    "match": 72,
                },
            }
        }
    )
    assert board["omega"]["home"] == 31
    assert board["omega"]["home_fired"] is True
    assert board["kscore"]["match"] == 72


def test_old_payload_still_exposes_stats_and_odds() -> None:
    factors = factors_from_payload(
        {
            "league": "Serie A",
            "status_short": "1H",
            "tslg": "12' - —",
            "tslg_home": 12,
            "sot": {"home": 3, "away": 1},
            "odds": {"home": 1.7, "draw": 3.6, "away": 5.2, "kickoff": {"home": 1.7, "draw": 3.6, "away": 5.2}},
        },
        strategy="omega",
        team="home",
        minute=38,
        score="0-0",
    )
    assert factors["has_board"] is False
    assert factors["half"] == "1H"
    assert factors["score_state"] == "0-0"
    assert factors["sot"]["home"] == 3
    assert factors["odds_home"] == 1.7
    assert factors["trigger_odds"] == 1.7
    assert factors["odds_bucket"] == "favourite <2"
    assert factors["clock_bucket"] == "31-45"
    assert factors["tslg_bucket"] == "10-19'"


def test_factors_keep_last_10min_window() -> None:
    window = {
        "start": 74,
        "end": 84,
        "sot": {"home": 3, "away": 1},
    }
    factors = factors_from_payload(
        {"last_10min": window, "sot": {"home": 10, "away": 2}},
        strategy="pressure_index",
        team="home",
        minute=84,
        score="1-1",
    )
    assert factors["last_10min"] == window
    assert factors["sot"]["home"] == 10


def test_pattern_summary_hit_rate_by_clock() -> None:
    rows = [
        {
            "state": "Confirmed",
            "factors": {"clock_bucket": "31-45", "half": "1H", "score_state": "0-0"},
        },
        {
            "state": "Expired",
            "factors": {"clock_bucket": "31-45", "half": "1H", "score_state": "0-0"},
        },
        {
            "state": "Confirmed",
            "factors": {"clock_bucket": "76+", "half": "2H", "score_state": "leading"},
        },
        {
            "state": "Monitoring",
            "factors": {"clock_bucket": "31-45"},
        },
    ]
    patterns = {block["title"]: block["rows"] for block in pattern_summary(rows)}
    clock = {row["label"]: row for row in patterns["Clock"]}
    assert clock["31-45"]["n"] == 2
    assert clock["31-45"]["hit_rate"] == 0.5
    assert clock["76+"]["hit_rate"] == 1.0


def test_csv_row_flattens_pairs() -> None:
    row = csv_row(
        {
            "state": "Confirmed",
            "strategy": "omega",
            "team": "home",
            "value": 0.4,
            "minute": 40,
            "score": "0-0",
            "home_team": "A",
            "away_team": "B",
            "league": "L",
            "factors": {
                "sot": {"home": 2, "away": 0},
                "omega": {"home": 31, "away": 2},
                "also_firing": ["delta_5min"],
            },
        }
    )
    assert row["sot_home"] == 2
    assert row["omega_home"] == 31
    assert row["also_firing"] == "delta_5min"
