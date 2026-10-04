"""Admin session and fail-closed writes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from kalchas_api.app import app


def test_admin_login_requires_password_env(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    res = TestClient(app).post("/api/admin/login", json={"password": "x"})
    assert res.status_code == 503


def test_admin_login_sets_cookie(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    bad = client.post("/api/admin/login", json={"password": "nope"})
    assert bad.status_code == 401
    assert client.get("/api/admin/session").json()["ok"] is False
    ok = client.post("/api/admin/login", json={"password": "s3cret"})
    assert ok.status_code == 200
    assert client.get("/api/admin/session").json() == {"ok": True, "configured": True}


def test_admin_config_requires_session(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    client = TestClient(app)
    assert client.get("/api/admin/config").status_code == 401
    client.post("/api/admin/login", json={"password": "s3cret"})
    res = client.get("/api/admin/config")
    assert res.status_code == 503


def test_patch_strategy_rule_requires_admin(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    res = client.patch("/api/strategy-rules/2", json={"team_specific": True})
    assert res.status_code == 401


def test_admin_results_requires_session(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    assert client.get("/api/admin/results").status_code == 401


def test_admin_results_returns_filtered_rows(monkeypatch) -> None:
    from datetime import UTC, datetime

    import kalchas_db.alerts

    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.alerts,
        "list_alert_results_sync",
        lambda dsn, **kwargs: (
            [
                {
                    "id": 11,
                    "match_id": "m1",
                    "strategy_slot": 6,
                    "strategy_key": "omega",
                    "team": "away",
                    "value": 0.2,
                    "minute": 44,
                    "score": "0-0",
                    "home_team": "Home",
                    "away_team": "Away",
                    "created_at": datetime(2026, 10, 1, 20, 0, tzinfo=UTC),
                    "payload": {"league": "CONCACAF", "theta": 22},
                    "state": "Confirmed",
                    "decision": "confirmed",
                    "detail": {
                        "settle_score": "0-1",
                        "settle_minute": 45,
                        "league": "CONCACAF",
                    },
                    "evaluated_at": datetime(2026, 10, 1, 20, 5, tzinfo=UTC),
                    "live": False,
                }
            ],
            {"total": 1, "confirmed": 1, "expired": 0, "monitoring": 0},
        ),
    )
    client = TestClient(app)
    client.post("/api/admin/login", json={"password": "s3cret"})
    res = client.get("/api/admin/results", params={"strategy": "omega", "state": "Confirmed"})
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["confirmed"] == 1
    assert body["summary"]["hit_rate"] == 1.0
    assert body["items"][0]["state"] == "Confirmed"
    assert body["items"][0]["league"] == "CONCACAF"
    assert body["items"][0]["settle_score"] == "0-1"


def test_save_preset_rejects_builtin_name(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    client.post("/api/admin/login", json={"password": "s3cret"})
    res = client.post(
        "/api/admin/weights/preset/save",
        json={
            "strategy": "rule_of_three",
            "name": "Balanced (default)",
            "weights": {"sot_weight": 0.4},
        },
    )
    assert res.status_code == 400
    assert "built-in" in res.json()["detail"]


def test_save_preset_as_stores_and_applies(monkeypatch) -> None:
    import kalchas_db.settings

    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    stored: dict[str, dict] = {}
    monkeypatch.setattr(
        kalchas_db.settings,
        "upsert_saved_preset",
        lambda dsn, strategy, name, payload: stored.setdefault(name, dict(payload)),
    )
    monkeypatch.setattr(
        kalchas_db.settings,
        "list_saved_presets",
        lambda dsn, strategy: list(stored),
    )
    monkeypatch.setattr(kalchas_db.settings, "reset_weights", lambda dsn, strategy, key=None: 0)
    monkeypatch.setattr(
        kalchas_db.settings,
        "upsert_weight",
        lambda dsn, strategy, key, value: None,
    )
    monkeypatch.setattr(
        kalchas_db.settings,
        "replace_strategy_conditions",
        lambda dsn, slot, rows: list(rows),
    )
    monkeypatch.setattr(
        kalchas_db.settings,
        "list_weight_overrides",
        lambda dsn: {"rule_of_three": (stored.get("Night set") or {}).get("weights") or {}},
    )
    client = TestClient(app)
    client.post("/api/admin/login", json={"password": "s3cret"})
    res = client.post(
        "/api/admin/weights/preset/save",
        json={
            "strategy": "rule_of_three",
            "name": "Night set",
            "weights": {"sot_weight": 0.4, "sofft_weight": 0.08},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Night set"
    assert "Night set" in body["saved_presets"]
    assert stored["Night set"]["weights"]["sot_weight"] == 0.4
    assert stored["Night set"]["conditions"] == []


def test_admin_preview_requires_session(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    res = client.post(
        "/api/admin/preview",
        json={"strategy": "rule_of_three", "weights": {"sot_weight": 0.4}},
    )
    assert res.status_code == 401


def test_admin_preview_returns_overlay_cells(monkeypatch) -> None:
    import kalchas_api.preview

    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_api.preview,
        "preview_live_matches",
        lambda dsn, **kwargs: [
            {
                "match_id": "m1",
                "home_team": "Home",
                "away_team": "Away",
                "minute": 20,
                "score": "1-0",
                "hot": 12,
                "strategy": {
                    "home": 1.4,
                    "away": 0.2,
                    "home_triggered": True,
                    "away_triggered": False,
                },
                "kscore": {
                    "home": 55,
                    "away": 40,
                    "home_triggered": False,
                    "away_triggered": False,
                },
                "baseline": {
                    "strategy": {"home": 1.0, "away": 0.2},
                    "kscore": {"home": 50, "away": 40},
                    "hot": 10,
                },
            }
        ],
    )
    client = TestClient(app)
    client.post("/api/admin/login", json={"password": "s3cret"})
    res = client.post(
        "/api/admin/preview",
        json={"strategy": "rule_of_three", "weights": {"sot_weight": 0.4}},
    )
    assert res.status_code == 200
    row = res.json()["matches"][0]
    assert row["strategy"]["home"] == 1.4
    assert row["baseline"]["strategy"]["home"] == 1.0


def test_admin_various_requires_session(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    assert client.get("/api/admin/various").status_code == 401
    assert client.put(
        "/api/admin/various",
        json={
            "ht1_start": 28,
            "ht1_end": 44,
            "ht2_start": 72,
            "ht2_end": 88,
            "include_injury_time": True,
        },
    ).status_code == 401


def test_admin_various_put_saves(monkeypatch) -> None:
    import kalchas_db.settings

    stored: dict = {}

    def _put(dsn, fields):
        stored.update(fields)
        return {
            "ht1_start": 30,
            "ht1_end": 42,
            "ht2_start": 70,
            "ht2_end": 86,
            "include_injury_time": True,
        }

    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(kalchas_db.settings, "upsert_board_settings", _put)
    client = TestClient(app)
    client.post("/api/admin/login", json={"password": "s3cret"})
    res = client.put(
        "/api/admin/various",
        json={
            "ht1_start": 30,
            "ht1_end": 42,
            "ht2_start": 70,
            "ht2_end": 86,
            "include_injury_time": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["various"]["ht1_start"] == 30
    assert res.json()["various"]["include_injury_time"] is True
    assert stored["ht1_start"] == 30


def test_admin_put_conditions_saves(monkeypatch) -> None:
    import kalchas_db.settings

    stored: list = []

    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.settings,
        "replace_strategy_conditions",
        lambda dsn, slot, rows: stored.append((slot, list(rows))) or list(rows),
    )
    client = TestClient(app)
    client.post("/api/admin/login", json={"password": "s3cret"})
    res = client.put(
        "/api/admin/conditions",
        json={
            "strategy": "delta_5min",
            "conditions": [
                {
                    "left_scope": "triggering",
                    "left_metric": "npei",
                    "operator": ">=",
                    "right_kind": "value",
                    "right_value": 50,
                }
            ],
        },
    )
    assert res.status_code == 200
    assert stored[0][0] == 4
    assert stored[0][1][0]["left_metric"] == "npei"
