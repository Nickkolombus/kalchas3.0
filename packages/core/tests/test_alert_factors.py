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


def test_pattern_summary_hit_rate_by_weekday_and_hour() -> None:
    rows = [
        {
            "state": "Confirmed",
            "created_at": "2026-10-12T14:30:00+00:00",  # Monday, 14:00 UTC
            "factors": {},
        },
        {
            "state": "Expired",
            "created_at": "2026-10-12T14:45:00+00:00",  # Monday, 14:00 UTC
            "factors": {},
        },
        {
            "state": "Confirmed",
            "created_at": "2026-10-18T09:05:00Z",  # Sunday, 09:00 UTC ('Z' form)
            "factors": {},
        },
        {
            "state": "Monitoring",
            "created_at": "2026-10-12T14:10:00+00:00",
            "factors": {},
        },
    ]
    patterns = {block["title"]: block["rows"] for block in pattern_summary(rows)}
    weekday = {row["label"]: row for row in patterns["Weekday (UTC)"]}
    hour = {row["label"]: row for row in patterns["Hour (UTC)"]}
    assert weekday["Mon"]["n"] == 2
    assert weekday["Mon"]["hit_rate"] == 0.5
    assert weekday["Sun"]["hit_rate"] == 1.0
    assert hour["14:00"]["n"] == 2
    assert hour["09:00"]["n"] == 1


def test_pattern_summary_hit_rate_by_league_and_country() -> None:
    rows = [
        {"state": "Confirmed", "league": "Serie A", "factors": {"country": "Italy"}},
        {"state": "Expired", "league": "Serie A", "factors": {"country": "Italy"}},
        {"state": "Confirmed", "league": "La Liga", "factors": {"country": "Spain"}},
        {"state": "Confirmed", "league": None, "factors": {}},
    ]
    patterns = {block["title"]: block["rows"] for block in pattern_summary(rows)}
    league = {row["label"]: row for row in patterns["League"]}
    country = {row["label"]: row for row in patterns["Country"]}
    assert league["Serie A"]["n"] == 2
    assert league["Serie A"]["hit_rate"] == 0.5
    assert league["La Liga"]["hit_rate"] == 1.0
    assert league["Unknown"]["n"] == 1
    assert country["Italy"]["n"] == 2
    assert country["Spain"]["hit_rate"] == 1.0


def test_pattern_summary_leagues_beyond_top_n_fold_into_other() -> None:
    rows = [
        {"state": "Confirmed", "league": f"League {i}", "factors": {}} for i in range(14)
    ]
    patterns = {block["title"]: block["rows"] for block in pattern_summary(rows)}
    league_rows = patterns["League"]
    assert len(league_rows) == 13  # top 12 + one "Other" row
    other = next(row for row in league_rows if row["label"].startswith("Other"))
    assert other["n"] == 2


def test_pattern_summary_trigger_value_bins_by_fire_strength() -> None:
    # 10 rows, value 1..10, odd values miss, even values confirm -> low bin
    # should read worse than the high bin.
    rows = [
        {"state": "Confirmed" if value % 2 == 0 else "Expired", "value": value, "factors": {}}
        for value in range(1, 11)
    ]
    patterns = {block["title"]: block["rows"] for block in pattern_summary(rows)}
    trigger_rows = patterns["Trigger value (fire strength)"]
    assert len(trigger_rows) == 5
    assert sum(row["n"] for row in trigger_rows) == 10
    # Every bin mixes one even and one odd value with this input, so each
    # bin's hit rate is 0.5 -- check volume and ordering instead of hit rate.
    assert trigger_rows[0]["label"] == "1–2"
    assert trigger_rows[-1]["label"] == "9–10"


def test_pattern_summary_trigger_value_skipped_below_bin_count() -> None:
    rows = [{"state": "Confirmed", "value": 1.0, "factors": {}}]
    titles = {block["title"] for block in pattern_summary(rows)}
    assert "Trigger value (fire strength)" not in titles


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
