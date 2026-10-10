"""Public /tips.csv and admin tips feed."""

from __future__ import annotations

from fastapi.testclient import TestClient
from kalchas_api.app import app
from kalchas_api.tips import market_for, render_csv, rows_from_alerts


def test_first_half_over_current_total() -> None:
    market, selection = market_for("0-0", 18)
    assert market == "FIRST_HALF_GOALS_05"
    assert selection == "Over 0.5 Goals"


def test_second_half_uses_full_game_market() -> None:
    market, selection = market_for("1-1", 62)
    assert market == "OVER_UNDER_25"
    assert selection == "Over 2.5 Goals"


def test_one_row_per_match_collects_strategies() -> None:
    rows = rows_from_alerts(
        [
            {
                "match_id": "m1",
                "home_team": "Twente",
                "away_team": "Sittard",
                "score": "0-0",
                "minute": 22,
                "strategy_key": "delta_5min",
                "created_at": "2026-10-10T20:00:00+00:00",
            },
            {
                "match_id": "m1",
                "home_team": "Twente",
                "away_team": "Sittard",
                "score": "0-0",
                "minute": 23,
                "strategy_key": "pressure_index",
                "created_at": "2026-10-10T20:00:10+00:00",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["event_name"] == "Twente v Sittard"
    assert rows[0]["strategies"] == ["delta_5min", "pressure_index"]
    assert rows[0]["correlation_method"] == "passthrough"


def test_csv_header_matches_bfbot() -> None:
    body = render_csv(
        [
            {
                "event_name": "Twente v Sittard",
                "market_type": "FIRST_HALF_GOALS_05",
                "selection_name": "Over 0.5 Goals",
            }
        ]
    )
    lines = body.strip().splitlines()
    assert lines[0] == "Provider,EventName,MarketType,SelectionName,BetType"
    assert lines[1] == "Kalchas,Twente v Sittard,FIRST_HALF_GOALS_05,Over 0.5 Goals,BACK"


def test_empty_csv_is_header_only() -> None:
    body = render_csv([])
    assert body.strip() == "Provider,EventName,MarketType,SelectionName,BetType"


def test_tips_csv_renders_live_rows(monkeypatch) -> None:
    import kalchas_api.tips as tips_mod

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        "kalchas_db.tips_export.get_settings_sync",
        lambda dsn: {"alert_window_seconds": 30},
    )
    monkeypatch.setattr(
        "kalchas_db.tips_export.list_open_alerts_in_window_sync",
        lambda dsn, window_seconds: [
            {
                "match_id": "m1",
                "home_team": "Twente",
                "away_team": "Sittard",
                "score": "0-0",
                "minute": 22,
                "strategy_key": "delta_5min",
                "created_at": "2026-10-10T20:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr("kalchas_db.tips_export.record_log_rows_sync", lambda dsn, rows: None)
    monkeypatch.setattr(
        "kalchas_db.tips_export.record_poll_sync",
        lambda dsn, row_count, user_agent: None,
    )
    res = TestClient(app).get("/tips.csv")
    assert res.status_code == 200
    assert "Kalchas,Twente v Sittard,FIRST_HALF_GOALS_05,Over 0.5 Goals,BACK" in res.text
    assert tips_mod.PROVIDER == "Kalchas"


def test_tips_csv_is_public(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    res = TestClient(app).get("/tips.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.text.strip().startswith("Provider,EventName,MarketType,SelectionName,BetType")


def test_tips_window_accepts_half_hour() -> None:
    from kalchas_api.tips import TipsWindowIn
    from kalchas_db.tips_export import DEFAULT_WINDOW_SECONDS, MAX_WINDOW_SECONDS

    assert TipsWindowIn(alert_window_seconds=1800).alert_window_seconds == 1800
    assert DEFAULT_WINDOW_SECONDS == 1800
    assert MAX_WINDOW_SECONDS == 3600


def test_admin_tips_requires_session(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    assert client.get("/api/admin/tips").status_code == 401
    client.post("/api/admin/login", json={"password": "s3cret"})
    res = client.get("/api/admin/tips")
    assert res.status_code == 503
