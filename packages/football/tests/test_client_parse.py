"""apifootball.com client unit tests (no network)."""

from __future__ import annotations

from kalchas_football.client import (
    _parse_elapsed,
    apifootball_badge_url,
    live_match_from_event,
    statistics_to_team_dict,
)


def test_parse_elapsed_plain_minute() -> None:
    assert _parse_elapsed("67") == (67, "2H", "67")


def test_parse_elapsed_stoppage() -> None:
    assert _parse_elapsed("45+2") == (47, "1H", "45+2")
    assert _parse_elapsed("90+3") == (93, "2H", "90+3")
    assert _parse_elapsed("90+") == (90, "2H", "90+")
    assert _parse_elapsed("45+") == (45, "1H", "45+")
    assert _parse_elapsed("90+2'") == (92, "2H", "90+2")


def test_live_match_fills_bare_stoppage_from_event_times() -> None:
    row = {
        "match_id": "1",
        "match_hometeam_name": "Alpha",
        "match_awayteam_name": "Beta",
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": "1",
        "match_awayteam_score": "1",
        "match_status": "90+",
        "goalscorer": [{"time": "90+3", "home_scorer": "X", "away_scorer": ""}],
        "cards": [{"time": "90+2", "home_fault": "Y", "away_fault": "", "card": "yellow card"}],
    }
    match = live_match_from_event(row)
    assert match is not None
    assert match.minute == 93
    assert match.minute_display == "90+3"


def test_live_match_keeps_status_digit_ahead_of_older_event() -> None:
    row = {
        "match_id": "1",
        "match_hometeam_name": "Alpha",
        "match_awayteam_name": "Beta",
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": "0",
        "match_awayteam_score": "0",
        "match_status": "90+4",
        "goalscorer": [{"time": "90+1", "home_scorer": "X", "away_scorer": ""}],
    }
    match = live_match_from_event(row)
    assert match is not None
    assert match.minute == 94
    assert match.minute_display == "90+4"


def test_first_half_stoppage_fills_from_events() -> None:
    row = {
        "match_id": "1",
        "match_hometeam_name": "Alpha",
        "match_awayteam_name": "Beta",
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": "0",
        "match_awayteam_score": "0",
        "match_status": "45+",
        "goalscorer": [{"time": "45+2", "away_scorer": "Z", "home_scorer": ""}],
    }
    match = live_match_from_event(row)
    assert match is not None
    assert match.minute == 47
    assert match.status_short == "1H"
    assert match.minute_display == "45+2"


def test_live_match_fills_stoppage_from_integer_event_minute() -> None:
    row = {
        "match_id": "1",
        "match_hometeam_name": "Alpha",
        "match_awayteam_name": "Beta",
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": "1",
        "match_awayteam_score": "0",
        "match_status": "90+",
        "goalscorer": [{"time": "93", "home_scorer": "X", "away_scorer": ""}],
    }
    match = live_match_from_event(row)
    assert match is not None
    assert match.minute == 93
    assert match.minute_display == "90+3"


def test_first_half_stoppage_ignores_second_half_event_minute() -> None:
    row = {
        "match_id": "1",
        "match_hometeam_name": "Alpha",
        "match_awayteam_name": "Beta",
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": "0",
        "match_awayteam_score": "0",
        "match_status": "45+",
        "goalscorer": [{"time": "64", "home_scorer": "X", "away_scorer": ""}],
    }
    match = live_match_from_event(row)
    assert match is not None
    assert match.minute == 45
    assert match.minute_display == "45+"


def test_comment_elapsed_skips_full_time_and_reads_mm_ss() -> None:
    from kalchas_football import advance_stoppage_clock, comment_elapsed_from_live_comments

    payload = {
        "1": {
            "match_id": "1",
            "live_comments": [
                {"time": "90:31", "text": "attack", "state": ""},
                {"time": "92:11", "text": "goal", "state": ""},
                {"time": "90:00", "text": "Full time", "state": ""},
            ],
        }
    }
    clocks = comment_elapsed_from_live_comments(payload)
    assert clocks["1"] == 92
    elapsed, short, display = advance_stoppage_clock(90, "2H", "90+", comment_elapsed=92)
    assert (elapsed, short, display) == (92, "2H", "90+2")


def test_comment_clock_does_not_rewind_status_digit() -> None:
    from kalchas_football import advance_stoppage_clock

    elapsed, _short, display = advance_stoppage_clock(94, "2H", "90+4", comment_elapsed=92)
    assert elapsed == 94
    assert display == "90+4"


def test_comment_clock_advances_bare_first_half_minute() -> None:
    from kalchas_football import advance_stoppage_clock

    elapsed, short, display = advance_stoppage_clock(45, "1H", "45", comment_elapsed=47)
    assert (elapsed, short, display) == (47, "1H", "45+2")


def test_hold_playing_period_keeps_added_time_in_first_half() -> None:
    from kalchas_football import hold_playing_period, live_match_from_event

    row = {
        "match_id": "1",
        "match_hometeam_name": "Villa",
        "match_awayteam_name": "Palace",
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": "0",
        "match_awayteam_score": "0",
        "match_status": "47",
    }
    incoming = live_match_from_event(row)
    assert incoming is not None
    assert incoming.status_short == "2H"
    held = hold_playing_period(incoming, previous_status="1H")
    assert held.status_short == "1H"
    assert held.minute == 47
    assert held.minute_display == "45+2"


def test_hold_playing_period_allows_second_half_after_ht() -> None:
    from kalchas_football import hold_playing_period, live_match_from_event

    row = {
        "match_id": "1",
        "match_hometeam_name": "Villa",
        "match_awayteam_name": "Palace",
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": "0",
        "match_awayteam_score": "0",
        "match_status": "47",
    }
    incoming = live_match_from_event(row)
    assert incoming is not None
    held = hold_playing_period(incoming, previous_status="HT")
    assert held.status_short == "2H"


def test_parse_elapsed_half_time() -> None:
    assert _parse_elapsed("Half Time") == (0, "HT", "")


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
        "league_id": "152",
    }
    match = live_match_from_event(row)
    assert match is not None
    assert match.match_id == "123"
    assert match.home_team == "Alpha"
    assert match.minute == 55
    assert match.status_short == "2H"
    assert match.minute_display == "55"
    assert match.home_score == 1
    assert match.league_id == 152
    assert match.country_name == ""


def test_live_match_reads_country_from_event() -> None:
    row = {
        "match_id": "123",
        "match_hometeam_name": "Alpha",
        "match_awayteam_name": "Beta",
        "match_hometeam_id": "10",
        "match_awayteam_id": "20",
        "match_hometeam_score": "0",
        "match_awayteam_score": "0",
        "match_status": "12",
        "league_name": "J-League Cup",
        "country_name": "Japan",
        "country_logo": "https://apiv3.apifootball.com/badges/logo_country/3_japan.png",
    }
    match = live_match_from_event(row)
    assert match is not None
    assert match.country_name == "Japan"
    assert "japan" in match.country_logo


def test_live_match_reads_team_badges_and_upgrades_http() -> None:
    row = {
        "match_id": "123",
        "match_hometeam_name": "D. Puerto Montt",
        "match_awayteam_name": "Colo Colo",
        "match_hometeam_id": "2222",
        "match_awayteam_id": "553",
        "match_hometeam_score": "0",
        "match_awayteam_score": "0",
        "match_status": "12",
        "team_home_badge": "https://apiv3.apifootball.com/badges//2222_puerto-montt.jpg",
        "team_away_badge": "https://apiv3.apifootball.com/badges/553_colo-colo.jpg",
    }
    match = live_match_from_event(row)
    assert match is not None
    assert match.home_team_logo == "https://apiv3.apifootball.com/badges/2222_puerto-montt.jpg"
    assert match.away_team_logo.endswith("553_colo-colo.jpg")


def test_badge_url_strips_leading_initials() -> None:
    url = apifootball_badge_url(2222, "D. Puerto Montt")
    assert url == "https://apiv3.apifootball.com/badges/2222_puerto-montt.jpg"
    assert "d-puerto" not in (url or "")


def test_rate_limiter_skips_instead_of_hour_sleep(monkeypatch) -> None:
    from kalchas_football.client import RateLimitBudgetExceeded, RateLimiter

    slept: list[float] = []
    monkeypatch.setattr("kalchas_football.client.time.sleep", slept.append)
    limiter = RateLimiter(requests_per_hour=1)
    limiter.wait()
    try:
        limiter.wait()
    except RateLimitBudgetExceeded as exc:
        assert exc.sleep_for > 3500
    else:
        raise AssertionError("expected RateLimitBudgetExceeded")
    assert slept == []


def test_get_live_fixtures_empty_when_hourly_budget_exhausted(monkeypatch) -> None:
    from kalchas_football.client import FootballAPIClient, RateLimitBudgetExceeded

    client = FootballAPIClient(api_key="test-key")

    def _raise() -> None:
        raise RateLimitBudgetExceeded(3497.6)

    monkeypatch.setattr(client.limiter, "wait", _raise)
    assert client.get_live_fixtures() == []
    client.close()


def test_endpoint_limiters_are_independent() -> None:
    from kalchas_football.client import FootballAPIClient, RateLimitBudgetExceeded

    client = FootballAPIClient(api_key="test-key", requests_per_hour=1)
    client.limiter_for("get_events").wait()
    client.limiter_for("get_statistics").wait()
    try:
        client.limiter_for("get_events").wait()
    except RateLimitBudgetExceeded:
        pass
    else:
        raise AssertionError("get_events bucket should be exhausted")
    client.limiter_for("get_odds").wait()
    client.close()


def test_no_event_found_is_empty_list(monkeypatch) -> None:
    from kalchas_football.client import FootballAPIClient

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"error": 404, "message": "No event found (please check your plan)!"}

    client = FootballAPIClient(api_key="test-key")
    monkeypatch.setattr(client._client, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(client.limiter, "wait", lambda: None)
    assert client.get_live_fixtures() == []
    client.close()


def test_finished_rows_are_kept_in_live_list(monkeypatch) -> None:
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
    assert len(live) == 2
    by_id = {row.match_id: row for row in live}
    assert by_id["1"].status_short == "FT"
    assert by_id["1"].minute == 0
    assert by_id["2"].match_id == "2"
    assert by_id["2"].status_short == "1H"
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


# Order and values from the documented get_events statistics[] example.
_DOC_EVENT_STATS = [
    {"type": "Attacks", "home": "108", "away": "94"},
    {"type": "Dangerous Attacks", "home": "44", "away": "39"},
    {"type": "On Target", "home": "2", "away": "8"},
    {"type": "Off Target", "home": "5", "away": "7"},
    {"type": "Shots Total", "home": "7", "away": "15"},
    {"type": "Shots On Goal", "home": "2", "away": "8"},
    {"type": "Shots Off Goal", "home": "3", "away": "5"},
    {"type": "Shots Blocked", "home": "2", "away": "2"},
    {"type": "Corners", "home": "7", "away": "6"},
    {"type": "Ball Possession", "home": "42%", "away": "58%"},
]


def test_primary_labels_win_over_later_synonyms() -> None:
    out = statistics_to_team_dict(_DOC_EVENT_STATS)
    # "Off Target" (incl. blocked) must not be overwritten by "Shots Off Goal".
    assert out["home_team"]["off_target"] == 5
    assert out["away_team"]["off_target"] == 7
    assert out["home_team"]["on_target"] == 2
    assert out["away_team"]["attacks"] == 94
    assert out["home_team"]["dangerous_attacks"] == 44
    assert out["away_team"]["ball_possession"] == 58


def test_fallback_labels_used_when_primary_absent() -> None:
    raw = [
        {"type": "Shots On Goal", "home": "9", "away": "2"},
        {"type": "Shots Off Goal", "home": "4", "away": "2"},
    ]
    out = statistics_to_team_dict(raw)
    assert out["home_team"]["on_target"] == 9
    assert out["home_team"]["off_target"] == 4


def test_statistics_from_event_reads_embedded_stats() -> None:
    from kalchas_football import statistics_from_event

    out = statistics_from_event({"match_id": "112282", "statistics": _DOC_EVENT_STATS})
    assert out is not None
    assert out["match_id"] == "112282"
    assert out["home_team"]["dangerous_attacks"] == 44


def test_statistics_from_event_none_without_stats() -> None:
    from kalchas_football import statistics_from_event

    assert statistics_from_event({"match_id": "1"}) is None
    assert statistics_from_event({"match_id": "1", "statistics": []}) is None
    assert statistics_from_event({}) is None


def test_lineup_and_substitutions_from_event() -> None:
    from kalchas_football import lineup_from_event, substitutions_from_event

    row = {
        "lineup": {
            "home": {"starting_lineups": [{"lineup_player": "Keeper", "lineup_number": "1"}]}
        },
        "substitutions": {
            "home": [{"time": "63", "substitution": "Starter | Bench"}],
        },
    }
    assert lineup_from_event(row)["home"]["starting_lineups"][0]["lineup_player"] == "Keeper"
    assert substitutions_from_event(row)["home"][0]["substitution"] == "Starter | Bench"
    assert lineup_from_event({}) == {}
    assert substitutions_from_event({"substitutions": []}) == {}


def test_odds_1x2_keeps_first_complete_bookmaker() -> None:
    from kalchas_football import odds_1x2_from_provider_rows

    rows = [
        {
            "match_id": "58819",
            "odd_bookmakers": "bwin",
            "odd_1": "2.10",
            "odd_x": "3.20",
            "odd_2": "3.40",
        },
        {
            "match_id": "58819",
            "odd_bookmakers": "other",
            "odd_1": "9.99",
            "odd_x": "9.99",
            "odd_2": "9.99",
        },
        {"match_id": "7", "odd_1": "", "odd_x": "3", "odd_2": "2"},
        {"match_id": "8", "odd_1": "1.55", "odd_x": "4.0", "odd_2": "6.0"},
    ]
    out = odds_1x2_from_provider_rows(rows)
    assert out["58819"] == {"home": 2.10, "draw": 3.20, "away": 3.40}
    assert "7" not in out
    assert out["8"]["home"] == 1.55


def test_odds_1x2_from_live_comments_match_winner_and_team_names() -> None:
    from kalchas_football import odds_1x2_from_live_comments

    payload = {
        "4593": {
            "match_id": "4593",
            "match_hometeam_name": "Police Commissary",
            "match_awayteam_name": "Phnom Penh Crown",
            "live_odds": [
                {
                    "odd_name": "How many goals will Away Team score?",
                    "type": "No goal",
                    "value": "1.333",
                    "suspended": "No",
                },
                {
                    "odd_name": "Match Winner",
                    "type": "Home",
                    "value": "4.20",
                    "suspended": "No",
                },
                {
                    "odd_name": "Match Winner",
                    "type": "Draw",
                    "value": "3.60",
                    "suspended": "No",
                },
                {
                    "odd_name": "Match Winner",
                    "type": "Away",
                    "value": "1.70",
                    "suspended": "No",
                },
            ],
        },
        "9": {
            "match_id": "9",
            "match_hometeam_name": "Alpha",
            "match_awayteam_name": "Beta",
            "live_odds": [
                {
                    "odd_name": "1X2",
                    "type": "Alpha",
                    "value": "2.05",
                    "suspended": "No",
                },
                {
                    "odd_name": "1X2",
                    "type": "X",
                    "value": "3.10",
                    "suspended": "Yes",
                },
                {
                    "odd_name": "1X2",
                    "type": "Beta",
                    "value": "3.80",
                    "suspended": "No",
                },
            ],
        },
        "11": {
            "match_id": "11",
            "odd_1": "1.90",
            "odd_x": "3.40",
            "odd_2": "4.10",
        },
    }
    out = odds_1x2_from_live_comments(payload)
    assert out["4593"] == {"home": 4.20, "draw": 3.60, "away": 1.70}
    assert out["9"] == {"home": 2.05, "away": 3.80}
    assert out["11"] == {"home": 1.90, "draw": 3.40, "away": 4.10}


def test_merge_odds_records_freezes_kickoff_and_updates_live() -> None:
    from kalchas_football import compose_odds_record, merge_odds_records

    first = compose_odds_record(kickoff={"home": 2.1, "draw": 3.2, "away": 3.4})
    later = compose_odds_record(
        kickoff={"home": 9.9, "draw": 9.9, "away": 9.9},
        live={"home": 1.8, "draw": 3.5, "away": 4.2},
    )
    merged = merge_odds_records(first, later)
    assert merged["home"] == 2.1
    assert merged["kickoff"]["home"] == 2.1
    assert merged["live"] == {"home": 1.8, "draw": 3.5, "away": 4.2}


def test_parse_h2h_meetings_from_provider_shape() -> None:
    from kalchas_football.client import parse_h2h_meetings

    rows = parse_h2h_meetings(
        {
            "firstTeam_VS_secondTeam": [
                {
                    "match_id": "1",
                    "match_hometeam_id": "10",
                    "match_awayteam_id": "20",
                    "match_hometeam_name": "Alpha",
                    "match_awayteam_name": "Beta",
                    "match_hometeam_score": "2",
                    "match_awayteam_score": "1",
                    "match_date": "2025-03-01",
                    "league_name": "PL",
                    "goalscorer": [
                        {"time": "12", "home_scorer": "A"},
                        {"time": "80", "away_scorer": "B"},
                    ],
                }
            ]
        }
    )
    assert rows[0]["home_score"] == 2
    assert rows[0]["away_score"] == 1
    assert rows[0]["goal_events"] == [
        {"minute": 12, "team": "home", "side": "home"},
        {"minute": 80, "team": "away", "side": "away"},
    ]


def test_get_head_to_head_uses_last_slice(monkeypatch) -> None:
    from kalchas_football.client import FootballAPIClient

    client = FootballAPIClient(api_key="test-key")
    monkeypatch.setattr(
        client,
        "_get",
        lambda action, params=None: {
            "firstTeam_VS_secondTeam": [
                {
                    "match_id": str(i),
                    "match_hometeam_id": "10",
                    "match_awayteam_id": "20",
                    "match_hometeam_name": "A",
                    "match_awayteam_name": "B",
                    "match_hometeam_score": "1",
                    "match_awayteam_score": "0",
                    "match_date": f"2024-01-{i:02d}",
                }
                for i in range(1, 13)
            ]
        },
    )
    meetings = client.get_head_to_head(10, 20, last=10)
    assert len(meetings) == 10
    assert meetings[0]["match_id"] == "12"
    assert meetings[-1]["match_id"] == "3"
    client.close()
