"""H2H overlay payload and API route."""

from __future__ import annotations

from fastapi.testclient import TestClient
from kalchas_api.app import app
from kalchas_api.h2h import build_h2h_payload


def test_build_h2h_payload_counts_and_timing() -> None:
    fixtures = [
        {
            "match_id": "1",
            "home_team": "Home",
            "away_team": "Away",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_score": 2,
            "away_score": 1,
            "match_date": "2025-01-01",
            "goal_events": [{"minute": 12, "team": "home"}, {"minute": 80, "team": "away"}],
        },
        {
            "match_id": "2",
            "home_team": "Away",
            "away_team": "Home",
            "home_team_id": 2,
            "away_team_id": 1,
            "home_score": 0,
            "away_score": 0,
            "match_date": "2025-02-01",
            "goal_events": [],
        },
        {
            "match_id": "3",
            "home_team": "Home",
            "away_team": "Away",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_score": 3,
            "away_score": 2,
            "match_date": "2025-03-01",
            "goal_events": [
                {"minute": 8, "team": "home"},
                {"minute": 40, "team": "away"},
            ],
        },
        {
            "match_id": "4",
            "home_team": "Home",
            "away_team": "Away",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_score": 1,
            "away_score": 0,
            "match_date": "2025-04-01",
        },
        {
            "match_id": "5",
            "home_team": "Away",
            "away_team": "Home",
            "home_team_id": 2,
            "away_team_id": 1,
            "home_score": 2,
            "away_score": 2,
            "match_date": "2025-05-01",
        },
    ]
    payload = build_h2h_payload(
        fixtures,
        home_team_id=1,
        away_team_id=2,
        home_team="Home",
        away_team="Away",
    )
    assert payload["summary"]["sample"] == 5
    assert payload["summary"]["home_wins"] == 3
    assert payload["summary"]["draws"] == 2
    assert payload["insufficient"] is False
    assert payload["fixtures"][0]["match_date"] == "2025-05-01"
    assert payload["patterns"]["btts"]["count"] == 3
    assert payload["patterns"]["over_2_5"]["count"] == 3
    assert payload["patterns"]["timing"]["sample"] == 2
    assert payload["patterns"]["timing"]["early_goals_15"]["count"] == 2


def test_h2h_endpoint_requires_database(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    res = TestClient(app).get("/api/match/m1/h2h")
    assert res.status_code == 503


def test_h2h_endpoint_from_cache(monkeypatch) -> None:
    import kalchas_db.matches
    import kalchas_db.panel_cache

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.matches,
        "get_match_sync",
        lambda dsn, match_id: {
            "match_id": match_id,
            "home_team": "Home",
            "away_team": "Away",
            "home_team_id": 10,
            "away_team_id": 20,
        },
    )
    monkeypatch.setattr(
        kalchas_db.panel_cache,
        "load_panel_cache",
        lambda dsn, key, ttl_days=7: {
            "home_team": "Old Home",
            "away_team": "Old Away",
            "insufficient": False,
            "reason": None,
            "summary": {"home_wins": 4, "draws": 1, "away_wins": 2, "sample": 7},
            "fixtures": [],
            "patterns": {
                "sample": 7,
                "over_2_5": {"count": 3, "pct": 43},
                "under_2_5": {"count": 4, "pct": 57},
                "btts": {"count": 4, "pct": 57},
                "home_cs": {"count": 2, "pct": 29, "team": "Home"},
                "away_cs": {"count": 1, "pct": 14, "team": "Away"},
                "avg_goals": 2.4,
                "home_goals": 10,
                "away_goals": 7,
                "timing": None,
            },
        },
    )
    body = TestClient(app).get("/api/match/m1/h2h").json()
    assert body["source"] == "cache"
    assert body["data"]["home_team"] == "Home"
    assert body["data"]["summary"]["home_wins"] == 4


def test_h2h_endpoint_fetches_on_cache_miss(monkeypatch) -> None:
    import kalchas_db.matches
    import kalchas_db.panel_cache
    import kalchas_football

    saved: dict = {}

    class _Client:
        def get_head_to_head(self, t1, t2, last=10):
            return [
                {
                    "match_id": str(i),
                    "home_team": "Home",
                    "away_team": "Away",
                    "home_team_id": t1,
                    "away_team_id": t2,
                    "home_score": 1,
                    "away_score": 0,
                    "match_date": f"2025-01-{i:02d}",
                    "goal_events": [],
                }
                for i in range(1, 6)
            ]

        def close(self) -> None:
            return None

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.matches,
        "get_match_sync",
        lambda dsn, match_id: {
            "match_id": match_id,
            "home_team": "Home",
            "away_team": "Away",
            "home_team_id": 10,
            "away_team_id": 20,
        },
    )
    monkeypatch.setattr(kalchas_db.panel_cache, "load_panel_cache", lambda *a, **k: None)
    monkeypatch.setattr(
        kalchas_db.panel_cache,
        "save_panel_cache",
        lambda dsn, key, payload: saved.update({"key": key, "n": payload["summary"]["sample"]}),
    )
    monkeypatch.setattr(kalchas_football, "FootballAPIClient", lambda: _Client())
    body = TestClient(app).get("/api/match/m1/h2h").json()
    assert body["source"] == "api"
    assert body["data"]["summary"]["sample"] == 5
    assert body["data"]["summary"]["home_wins"] == 5
    assert saved["n"] == 5


def test_h2h_endpoint_skips_cache_when_sample_under_five(monkeypatch) -> None:
    import kalchas_db.matches
    import kalchas_db.panel_cache
    import kalchas_football

    saved: dict = {}

    class _Client:
        def get_head_to_head(self, t1, t2, last=10):
            return [
                {
                    "match_id": "1",
                    "home_team": "Home",
                    "away_team": "Away",
                    "home_team_id": t1,
                    "away_team_id": t2,
                    "home_score": 1,
                    "away_score": 0,
                    "match_date": "2025-01-01",
                    "goal_events": [],
                }
            ]

        def close(self) -> None:
            return None

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.matches,
        "get_match_sync",
        lambda dsn, match_id: {
            "match_id": match_id,
            "home_team": "Home",
            "away_team": "Away",
            "home_team_id": 10,
            "away_team_id": 20,
        },
    )
    monkeypatch.setattr(kalchas_db.panel_cache, "load_panel_cache", lambda *a, **k: None)
    monkeypatch.setattr(
        kalchas_db.panel_cache,
        "save_panel_cache",
        lambda dsn, key, payload: saved.update({"n": payload["summary"]["sample"]}),
    )
    monkeypatch.setattr(kalchas_football, "FootballAPIClient", lambda: _Client())
    body = TestClient(app).get("/api/match/m1/h2h").json()
    assert body["source"] == "api"
    assert body["data"]["insufficient"] is True
    assert body["data"]["summary"]["sample"] == 1
    assert saved == {}
