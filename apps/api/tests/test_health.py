"""API health smoke test (no live server required)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from kalchas_api.app import app
from kalchas_api.runtime import BoardTuning
from kalchas_core.runner import DEFAULT_THRESHOLDS
from kalchas_core.weights import WeightSet


def _stub_tuning(monkeypatch) -> None:
    import kalchas_api.runtime

    monkeypatch.setattr(
        kalchas_api.runtime,
        "load_board_tuning",
        lambda: BoardTuning(WeightSet.defaults(), dict(DEFAULT_THRESHOLDS), {}),
    )


def test_health() -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "npei" in body["strategies"] or "rule_of_three" in body["strategies"]


def test_default_weights() -> None:
    client = TestClient(app)
    res = client.get("/api/weights/defaults")
    assert res.status_code == 200
    assert "npei" in res.json()["strategies"]


def test_live_empty_without_database(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    client = TestClient(app)
    res = client.get("/api/live")
    assert res.status_code == 200
    body = res.json()
    assert body["matches"] == []
    assert body["source"] == "empty"
    assert body["sweet_spot"] == {
        "ht1_start": 28,
        "ht1_end": 44,
        "ht2_start": 72,
        "ht2_end": 88,
        "include_injury_time": False,
    }


def test_scanner_status_unconfigured_without_database(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    client = TestClient(app)
    res = client.get("/api/scanner-status")
    assert res.status_code == 200
    assert res.json() == {
        "state": "unconfigured",
        "mode": "unconfigured",
        "connected": False,
        "messages_received": 0,
        "reconnects": 0,
        "last_message_at": None,
        "last_http_poll_at": None,
        "updated_at": None,
    }


def test_scanner_status_hides_provider_error_from_public_payload(monkeypatch) -> None:
    import kalchas_db.scanner_status

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.scanner_status,
        "get_scanner_status_sync",
        lambda dsn: {
            "mode": "http_fallback",
            "connected": False,
            "messages_received": 40,
            "reconnects": 6,
            "last_message_at": None,
            "last_http_poll_at": None,
            "last_error": "apifootball.com error: Please make the payment for your account!",
            "updated_at": None,
        },
    )
    body = TestClient(app).get("/api/scanner-status").json()
    assert body["state"] == "paused"
    assert "payment" not in str(body).lower()
    assert "apifootball" not in str(body).lower()


def test_scanner_status_idle_when_disconnected_without_error(monkeypatch) -> None:
    import kalchas_db.scanner_status

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.scanner_status,
        "get_scanner_status_sync",
        lambda dsn: {
            "mode": "http_fallback",
            "connected": False,
            "messages_received": 1,
            "reconnects": 0,
            "last_message_at": None,
            "last_http_poll_at": None,
            "last_error": None,
            "updated_at": None,
        },
    )
    assert TestClient(app).get("/api/scanner-status").json()["state"] == "idle"


def test_live_includes_events_cards_and_recent_alerts(monkeypatch) -> None:
    import kalchas_db.alerts
    import kalchas_db.matches

    _stub_tuning(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.matches,
        "list_live_matches_sync",
        lambda dsn: [
            {
                "match_id": "m1",
                "home_team": "Home",
                "away_team": "Away",
                "minute": 36,
                "home_score": 1,
                "away_score": 0,
                "league_name": "League",
                "status_short": "1H",
                "minute_display": "45+",
                "home_team_id": 1,
                "away_team_id": 2,
                "home_stats": {"shots_on_target": 2},
                "away_stats": {"shots_on_target": 1},
            }
        ],
    )
    monkeypatch.setattr(kalchas_db.matches, "load_match_history_sync", lambda dsn, mid: {})
    monkeypatch.setattr(
        kalchas_db.matches,
        "load_match_histories_sync",
        lambda dsn, ids: {str(i): {} for i in ids},
    )
    monkeypatch.setattr(
        kalchas_db.matches,
        "load_match_events_sync",
        lambda dsn, mid: [
            {
                "event_type": "goal",
                "minute": 12,
                "side": "home",
                "team": "Home",
                "player_name": "Scorer",
                "detail": "Normal Goal",
            },
            {
                "event_type": "card",
                "minute": 30,
                "side": "away",
                "team": "Away",
                "player_name": "Booked",
                "detail": "Yellow Card",
            },
        ],
    )
    monkeypatch.setattr(
        kalchas_db.matches,
        "load_match_events_for_ids_sync",
        lambda dsn, ids: {
            str(i): [
                {
                    "event_type": "goal",
                    "minute": 12,
                    "side": "home",
                    "team": "Home",
                    "player_name": "Scorer",
                    "detail": "Normal Goal",
                },
                {
                    "event_type": "card",
                    "minute": 30,
                    "side": "away",
                    "team": "Away",
                    "player_name": "Booked",
                    "detail": "Yellow Card",
                },
            ]
            if str(i) == "m1"
            else []
            for i in ids
        },
    )
    monkeypatch.setattr(kalchas_db.matches, "get_match_sync", lambda dsn, mid: None)
    monkeypatch.setattr(kalchas_db.matches, "get_matches_sync", lambda dsn, ids: {})
    import kalchas_db.rules

    monkeypatch.setattr(kalchas_db.rules, "list_strategy_rules", lambda dsn: [])
    monkeypatch.setattr(
        kalchas_db.alerts,
        "list_recent_alerts_sync",
        lambda dsn: [
            {
                "id": 7,
                "match_id": "m1",
                "strategy_key": "pressure_index",
                "team": "home",
                "value": 64.5,
                "minute": 35,
                "score": "1-0",
                "home_team": "Home",
                "away_team": "Away",
                "delivery_status": "sent",
                "strategy_slot": 2,
                "created_at": datetime.now(UTC),
                "payload": {
                    "odds": {
                        "kickoff": {"home": 1.29, "draw": 6.0, "away": 11.0},
                        "home": 1.29,
                        "draw": 6.0,
                        "away": 11.0,
                    }
                },
            }
        ],
    )
    body = TestClient(app).get("/api/live").json()
    match = body["matches"][0]
    assert match["last_goal"] == {"minute": 12, "side": "home", "team": "Home"}
    assert match["minute_display"] == "45+"
    assert match["stat_lines"]["yellow_cards"] == {"home": 0, "away": 1}
    assert body["recent_alerts"][0]["strategy"] == "pressure_index"
    assert body["recent_alerts"][0]["state"] == "Monitoring"
    assert body["recent_alerts"][0]["score"] == "1-0"
    assert body["recent_alerts"][0]["current_score"] == "1-0"
    assert body["recent_alerts"][0]["minute"] == 35
    assert body["recent_alerts"][0]["current_minute"] == 36
    assert body["recent_alerts"][0]["kickoff_home"] == 1.29
    assert body["recent_alerts"][0]["kickoff_away"] == 11.0
    assert "delivery_status" not in body["recent_alerts"][0]
    assert "failed" not in str(body["recent_alerts"]).lower()


def test_live_drops_finished_matches(monkeypatch) -> None:
    import kalchas_db.alerts
    import kalchas_db.matches
    import kalchas_db.rules

    _stub_tuning(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.matches,
        "list_live_matches_sync",
        lambda dsn: [
            {
                "match_id": "done",
                "home_team": "Home",
                "away_team": "Away",
                "minute": 90,
                "home_score": 1,
                "away_score": 0,
                "league_name": "League",
                "status_short": "FT",
            },
            {
                "match_id": "live",
                "home_team": "A",
                "away_team": "B",
                "minute": 36,
                "home_score": 0,
                "away_score": 0,
                "league_name": "League",
                "status_short": "1H",
            },
        ],
    )
    monkeypatch.setattr(kalchas_db.matches, "load_match_history_sync", lambda dsn, mid: {})
    monkeypatch.setattr(
        kalchas_db.matches, "load_match_histories_sync", lambda dsn, ids: {str(i): {} for i in ids}
    )
    monkeypatch.setattr(kalchas_db.matches, "load_match_events_sync", lambda dsn, mid: [])
    monkeypatch.setattr(
        kalchas_db.matches,
        "load_match_events_for_ids_sync",
        lambda dsn, ids: {str(i): [] for i in ids},
    )
    monkeypatch.setattr(kalchas_db.matches, "get_match_sync", lambda dsn, mid: None)
    monkeypatch.setattr(kalchas_db.matches, "get_matches_sync", lambda dsn, ids: {})
    monkeypatch.setattr(kalchas_db.alerts, "list_recent_alerts_sync", lambda dsn: [])
    monkeypatch.setattr(kalchas_db.rules, "list_strategy_rules", lambda dsn: [])
    body = TestClient(app).get("/api/live").json()
    assert [row["match_id"] for row in body["matches"]] == ["live"]


def test_live_hides_telegram_failure_and_exposes_odds_country(monkeypatch) -> None:
    import kalchas_db.alerts
    import kalchas_db.matches

    _stub_tuning(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.matches,
        "list_live_matches_sync",
        lambda dsn: [
            {
                "match_id": "m1",
                "home_team": "Home",
                "away_team": "Away",
                "minute": 36,
                "home_score": 0,
                "away_score": 0,
                "league_name": "J-League Cup",
                "status_short": "1H",
                "home_team_id": 1,
                "away_team_id": 2,
                "country_name": "Japan",
                "country_logo": "https://apiv3.apifootball.com/badges/logo_country/3_japan.png",
                "odds": {"home": 2.1, "draw": 3.2, "away": 3.4},
                "home_stats": {},
                "away_stats": {},
            }
        ],
    )
    monkeypatch.setattr(kalchas_db.matches, "load_match_history_sync", lambda dsn, mid: {})
    monkeypatch.setattr(
        kalchas_db.matches, "load_match_histories_sync", lambda dsn, ids: {str(i): {} for i in ids}
    )
    monkeypatch.setattr(kalchas_db.matches, "load_match_events_sync", lambda dsn, mid: [])
    monkeypatch.setattr(
        kalchas_db.matches,
        "load_match_events_for_ids_sync",
        lambda dsn, ids: {str(i): [] for i in ids},
    )
    monkeypatch.setattr(kalchas_db.matches, "get_match_sync", lambda dsn, mid: None)
    monkeypatch.setattr(kalchas_db.matches, "get_matches_sync", lambda dsn, ids: {})
    import kalchas_db.rules

    monkeypatch.setattr(kalchas_db.rules, "list_strategy_rules", lambda dsn: [])
    monkeypatch.setattr(
        kalchas_db.alerts,
        "list_recent_alerts_sync",
        lambda dsn: [
            {
                "id": 8,
                "match_id": "m1",
                "strategy_key": "delta_5min",
                "team": "away",
                "value": 5.0,
                "minute": 34,
                "score": "0-0",
                "home_team": "Home",
                "away_team": "Away",
                "delivery_status": "failed",
                "strategy_slot": 4,
                "created_at": datetime.now(UTC),
            }
        ],
    )
    body = TestClient(app).get("/api/live").json()
    alert = body["recent_alerts"][0]
    assert alert["state"] == "Monitoring"
    assert "delivery_status" not in alert
    assert "failed" not in str(body).lower()
    match = body["matches"][0]
    assert match["country_logo"].endswith("japan.png")
    assert match["odds"]["home"] == 2.1
    assert match["odds"]["kickoff"] == {"home": 2.1, "draw": 3.2, "away": 3.4}
    assert match["odds"]["live"] is None


def _stub_live(
    monkeypatch,
    *,
    match: dict,
    events: list[dict],
    alerts: list[dict],
) -> None:
    import kalchas_db.alerts
    import kalchas_db.matches
    import kalchas_db.rules

    _stub_tuning(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(kalchas_db.matches, "list_live_matches_sync", lambda dsn: [match])
    monkeypatch.setattr(kalchas_db.matches, "load_match_history_sync", lambda dsn, mid: {})
    monkeypatch.setattr(
        kalchas_db.matches, "load_match_histories_sync", lambda dsn, ids: {str(i): {} for i in ids}
    )
    monkeypatch.setattr(kalchas_db.matches, "load_match_events_sync", lambda dsn, mid: events)
    monkeypatch.setattr(
        kalchas_db.matches,
        "load_match_events_for_ids_sync",
        lambda dsn, ids: {
            str(i): list(events) if str(i) == str(match["match_id"]) else [] for i in ids
        },
    )
    monkeypatch.setattr(kalchas_db.matches, "get_match_sync", lambda dsn, mid: None)
    monkeypatch.setattr(kalchas_db.matches, "get_matches_sync", lambda dsn, ids: {})
    monkeypatch.setattr(kalchas_db.alerts, "list_recent_alerts_sync", lambda dsn: alerts)
    monkeypatch.setattr(kalchas_db.rules, "list_strategy_rules", lambda dsn: [])


def test_live_confirms_ht_score_change_without_events(monkeypatch) -> None:
    _stub_live(
        monkeypatch,
        match={
            "match_id": "m1",
            "home_team": "United States Virgin Islands",
            "away_team": "Saint Martin",
            "minute": 0,
            "home_score": 0,
            "away_score": 1,
            "league_name": "CONCACAF",
            "status_short": "HT",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_stats": {},
            "away_stats": {},
        },
        events=[],
        alerts=[
            {
                "id": 11,
                "match_id": "m1",
                "strategy_key": "omega",
                "strategy_slot": 6,
                "team": "away",
                "value": 0.2,
                "minute": 44,
                "score": "0-0",
                "home_team": "United States Virgin Islands",
                "away_team": "Saint Martin",
                "delivery_status": "sent",
                "created_at": datetime.now(UTC),
            },
            {
                "id": 12,
                "match_id": "m1",
                "strategy_key": "delta_5min",
                "strategy_slot": 4,
                "team": "away",
                "value": 3.1,
                "minute": 44,
                "score": "0-0",
                "home_team": "United States Virgin Islands",
                "away_team": "Saint Martin",
                "delivery_status": "sent",
                "created_at": datetime.now(UTC),
            },
        ],
    )
    body = TestClient(app).get("/api/live").json()
    alerts = body["recent_alerts"]
    assert [row["state"] for row in alerts] == ["Confirmed", "Confirmed"]
    assert alerts[0]["current_status"] == "HT"
    assert alerts[0]["current_minute"] == 0
    assert alerts[0]["current_score"] == "0-1"


def test_live_confirms_goal_inside_success_window(monkeypatch) -> None:
    _stub_live(
        monkeypatch,
        match={
            "match_id": "m1",
            "home_team": "Lesotho",
            "away_team": "Morocco",
            "minute": 28,
            "home_score": 0,
            "away_score": 1,
            "league_name": "Africa Cup",
            "status_short": "1H",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_stats": {},
            "away_stats": {},
        },
        events=[
            {
                "event_type": "goal",
                "minute": 27,
                "side": "away",
                "team": "Morocco",
                "player_name": "Scorer",
                "detail": "Normal Goal",
            }
        ],
        alerts=[
            {
                "id": 9,
                "match_id": "m1",
                "strategy_key": "delta_5min",
                "strategy_slot": 4,
                "team": "away",
                "value": 7.0,
                "minute": 20,
                "score": "0-0",
                "home_team": "Lesotho",
                "away_team": "Morocco",
                "delivery_status": "failed",
                "created_at": datetime.now(UTC),
            }
        ],
    )
    body = TestClient(app).get("/api/live").json()
    assert body["recent_alerts"][0]["state"] == "Confirmed"
    assert body["recent_alerts"][0]["kind"] == "confirmed"
    assert body["recent_alerts"][0]["scoring_side"] == "away"
    assert body["recent_alerts"][0]["goal_minute"] == 27
    assert "delivery_status" not in body["recent_alerts"][0]
    assert "failed" not in str(body["recent_alerts"]).lower()


def test_live_expires_when_window_closes_without_goal(monkeypatch) -> None:
    _stub_live(
        monkeypatch,
        match={
            "match_id": "m1",
            "home_team": "Home",
            "away_team": "Away",
            "minute": 50,
            "home_score": 0,
            "away_score": 0,
            "league_name": "League",
            "status_short": "2H",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_stats": {},
            "away_stats": {},
        },
        events=[],
        alerts=[
            {
                "id": 10,
                "match_id": "m1",
                "strategy_key": "delta_5min",
                "strategy_slot": 4,
                "team": "away",
                "value": 2.9,
                "minute": 20,
                "score": "0-0",
                "home_team": "Home",
                "away_team": "Away",
                "delivery_status": "sent",
                "created_at": datetime.now(UTC),
            }
        ],
    )
    body = TestClient(app).get("/api/live").json()
    assert body["recent_alerts"][0]["state"] == "Expired"
    assert body["recent_alerts"][0]["kind"] == "no_goal"


def test_live_vanished_match_alert_expires(monkeypatch) -> None:
    _stub_live(
        monkeypatch,
        match={
            "match_id": "live",
            "home_team": "A",
            "away_team": "B",
            "minute": 20,
            "home_score": 0,
            "away_score": 0,
            "league_name": "League",
            "status_short": "1H",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_stats": {},
            "away_stats": {},
        },
        events=[],
        alerts=[
            {
                "id": 21,
                "match_id": "gone",
                "strategy_key": "delta_5min",
                "strategy_slot": 4,
                "team": "away",
                "value": 7.0,
                "minute": 48,
                "score": "1-0",
                "home_team": "Inca",
                "away_team": "Aruba",
                "delivery_status": "sent",
                "created_at": datetime.now(UTC) - timedelta(minutes=519),
            }
        ],
    )
    body = TestClient(app).get("/api/live").json()
    assert body["recent_alerts"][0]["state"] == "Expired"
    assert body["recent_alerts"][0]["kind"] == "no_goal"


def test_live_brief_coverage_gap_stays_monitoring(monkeypatch) -> None:
    _stub_live(
        monkeypatch,
        match={
            "match_id": "live",
            "home_team": "A",
            "away_team": "B",
            "minute": 20,
            "home_score": 0,
            "away_score": 0,
            "league_name": "League",
            "status_short": "1H",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_stats": {},
            "away_stats": {},
        },
        events=[],
        alerts=[
            {
                "id": 23,
                "match_id": "blip",
                "strategy_key": "delta_5min",
                "strategy_slot": 4,
                "team": "away",
                "value": 7.0,
                "minute": 48,
                "score": "1-0",
                "home_team": "Inca",
                "away_team": "Aruba",
                "delivery_status": "sent",
                "created_at": datetime.now(UTC) - timedelta(minutes=5),
            }
        ],
    )
    body = TestClient(app).get("/api/live").json()
    assert body["recent_alerts"][0]["state"] == "Monitoring"
    assert body["recent_alerts"][0]["kind"] == "monitoring"


def test_live_frozen_clock_alert_expires(monkeypatch) -> None:
    _stub_live(
        monkeypatch,
        match={
            "match_id": "m1",
            "home_team": "Bucaramanga",
            "away_team": "Junior",
            "minute": 70,
            "home_score": 3,
            "away_score": 1,
            "league_name": "League",
            "status_short": "2H",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_stats": {},
            "away_stats": {},
        },
        events=[],
        alerts=[
            {
                "id": 22,
                "match_id": "m1",
                "strategy_key": "omega",
                "strategy_slot": 6,
                "team": "away",
                "value": 0.2,
                "minute": 70,
                "score": "3-1",
                "home_team": "Bucaramanga",
                "away_team": "Junior",
                "delivery_status": "sent",
                "created_at": datetime.now(UTC) - timedelta(minutes=612),
            }
        ],
    )
    body = TestClient(app).get("/api/live").json()
    assert body["recent_alerts"][0]["state"] == "Expired"
    assert body["recent_alerts"][0]["kind"] == "no_goal"


def test_live_omega_stays_monitoring_on_opponent_goal(monkeypatch) -> None:
    _stub_live(
        monkeypatch,
        match={
            "match_id": "m1",
            "home_team": "Lesotho",
            "away_team": "Morocco",
            "minute": 28,
            "home_score": 0,
            "away_score": 1,
            "league_name": "Africa Cup",
            "status_short": "1H",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_stats": {},
            "away_stats": {},
        },
        events=[
            {
                "event_type": "goal",
                "minute": 27,
                "side": "away",
                "team": "Morocco",
                "player_name": "Scorer",
                "detail": "Normal Goal",
            }
        ],
        alerts=[
            {
                "id": 11,
                "match_id": "m1",
                "strategy_key": "omega",
                "strategy_slot": 6,
                "team": "home",
                "value": 0.2,
                "minute": 20,
                "score": "0-0",
                "home_team": "Lesotho",
                "away_team": "Morocco",
                "delivery_status": "sent",
                "created_at": datetime.now(UTC),
            }
        ],
    )
    body = TestClient(app).get("/api/live").json()
    assert body["recent_alerts"][0]["state"] == "Monitoring"
    assert body["recent_alerts"][0]["value"] == 8  # stored 0.2 ω → θ° at k_scale 1.5


def test_recent_omega_alert_display_is_degrees() -> None:
    from kalchas_api.app import _recent_alert_display_value
    from kalchas_core.weights import WeightSet

    weights = WeightSet.defaults()
    assert _recent_alert_display_value("omega", 0.5, weights) == 18
    assert _recent_alert_display_value("pressure_index", 64.5, weights) == 64.5


def test_strategy_rules_defaults() -> None:
    client = TestClient(app)
    res = client.get("/api/strategy-rules")
    assert res.status_code == 200
    by_slot = {r["strategy_slot"]: r for r in res.json()["rules"]}
    assert by_slot[2]["team_specific"] is False
    assert by_slot[3]["team_specific"] is False
    assert by_slot[4]["team_specific"] is False
    assert by_slot[1]["team_specific"] is True


def test_match_panel_unavailable_without_database(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    res = TestClient(app).get("/api/match/m1/panel")
    assert res.status_code == 503


def test_match_panel_from_persisted_live_row(monkeypatch) -> None:
    import kalchas_api.panel as panel_mod

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        panel_mod,
        "build_match_panel",
        lambda dsn, match_id: {
            "match_id": match_id,
            "home_team": "Home",
            "away_team": "Away",
            "home_team_id": 10,
            "away_team_id": 20,
            "minute": 67,
            "score": "1-0",
            "league": "Championship",
            "status_short": "2H",
            "stat_lines": {"dangerous_attacks": {"home": 18, "away": 9}},
            "strategy_status": {
                "omega": {
                    "teams": {
                        "home": {"value": 12, "triggered": False},
                        "away": {"value": 4, "triggered": False},
                    },
                    "threshold": 0,
                }
            },
            "events": [
                {
                    "event_type": "goal",
                    "minute": 12,
                    "side": "home",
                    "team": "Home",
                    "player_name": "Scorer",
                    "detail": "Normal Goal",
                }
            ],
            "substitutions": [
                {
                    "minute": 63,
                    "side": "home",
                    "player_out": "S. Benrahma",
                    "player_in": "M. Cornet",
                }
            ],
            "timeline": [
                {
                    "minute": 30,
                    "dangerous_attacks": {"home": 10, "away": 4},
                    "attacks": {"home": 20, "away": 12},
                    "shots_on_target": {"home": 2, "away": 1},
                    "possession": {"home": 55, "away": 45},
                    "rule_of_three": {"home": 0.4, "away": 0.1},
                    "omega": {"home": 8, "away": 2},
                    "kscore": 41,
                }
            ],
            "lineup": {
                "home": {
                    "starting": [{"player": "Keeper", "number": "1", "position": "1"}],
                    "substitutes": [],
                    "coach": "Coach",
                },
                "away": {"starting": [], "substitutes": [], "coach": None},
            },
        },
    )
    body = TestClient(app).get("/api/match/m1/panel").json()
    assert body["score"] == "1-0"
    assert body["substitutions"][0]["player_in"] == "M. Cornet"
    assert body["lineup"]["home"]["starting"][0]["player"] == "Keeper"
    assert body["timeline"][0]["omega"]["home"] == 8
    assert body["home_team_logo"].endswith("10_home.jpg")
    assert "get_lineups" not in str(body)


def test_flatten_substitutions_splits_out_and_in() -> None:
    from kalchas_api.panel import flatten_substitutions

    rows = flatten_substitutions(
        {
            "home": [{"time": "63", "substitution": "S. Benrahma | M. Cornet"}],
            "away": [{"time": "64'", "substitution": "J. Murphy | J. Willock"}],
        }
    )
    assert rows[0] == {
        "minute": 63,
        "side": "home",
        "player_out": "S. Benrahma",
        "player_in": "M. Cornet",
    }
    assert rows[1]["player_in"] == "J. Willock"


def test_live_reconstructed_logo_strips_leading_initials(monkeypatch) -> None:
    _stub_live(
        monkeypatch,
        match={
            "match_id": "860018",
            "home_team": "D. Puerto Montt",
            "away_team": "Colo Colo",
            "minute": 12,
            "home_score": 0,
            "away_score": 0,
            "league_name": "Chile Cup",
            "status_short": "1H",
            "home_team_id": 2222,
            "away_team_id": 553,
            "home_stats": {},
            "away_stats": {},
        },
        events=[],
        alerts=[],
    )
    match = TestClient(app).get("/api/live").json()["matches"][0]
    assert match["home_team_logo"].endswith("2222_puerto-montt.jpg")
    assert "d-puerto" not in match["home_team_logo"]
    assert match["away_team_logo"].endswith("553_colo-colo.jpg")


def test_live_prefers_persisted_team_badge_url(monkeypatch) -> None:
    persisted = "https://apiv3.apifootball.com/badges//2222_puerto-montt.jpg"
    _stub_live(
        monkeypatch,
        match={
            "match_id": "860018",
            "home_team": "D. Puerto Montt",
            "away_team": "Colo Colo",
            "minute": 20,
            "home_score": 0,
            "away_score": 0,
            "league_name": "Chile Cup",
            "status_short": "1H",
            "home_team_id": 2222,
            "away_team_id": 553,
            "home_team_logo": persisted,
            "home_stats": {},
            "away_stats": {},
        },
        events=[],
        alerts=[],
    )
    match = TestClient(app).get("/api/live").json()["matches"][0]
    assert match["home_team_logo"] == "https://apiv3.apifootball.com/badges/2222_puerto-montt.jpg"


def test_patch_team_specific_requires_admin() -> None:
    client = TestClient(app)
    res = client.patch("/api/strategy-rules/2", json={"team_specific": True})
    assert res.status_code in {401, 503}
