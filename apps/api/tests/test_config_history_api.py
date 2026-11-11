"""Admin saves land in strategy_config_history (needs a disposable Postgres).

Runs only when ``KALCHAS_TEST_DATABASE_URL`` is set; the database is migrated to
head and its config rows are rewritten.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from kalchas_api.app import app

TEST_DSN = os.environ.get("KALCHAS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="KALCHAS_TEST_DATABASE_URL not set")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    assert TEST_DSN
    from alembic import command
    from alembic.config import Config
    from kalchas_db import sync
    from sqlalchemy import text

    root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("script_location", str(root / "packages/db/alembic"))
    command.upgrade(cfg, "head")

    monkeypatch.setattr(sync, "_engine", None)
    eng = sync.sync_engine(TEST_DSN)
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE strategy_config_history"))
    c = TestClient(app)
    c.post("/api/admin/login", json={"password": "s3cret"})
    yield c
    eng.dispose()


def test_threshold_save_in_admin_writes_history_row(client: TestClient) -> None:
    from kalchas_db.settings import list_admin_rules, list_config_history, list_thresholds

    assert TEST_DSN
    old = list_thresholds(TEST_DSN)[4]
    rule = next(r for r in list_admin_rules(TEST_DSN) if r["strategy_slot"] == 4)
    item = {
        "slot": 4,
        "threshold": old + 1,
        "cooldown_minutes": rule["cooldown_minutes"],
        "cooldown_bypass_delta": rule["cooldown_bypass_delta"],
        "enabled": rule["enabled"],
        "max_fire_minute": rule["max_fire_minute"],
        "max_fire_minute_1h": rule["max_fire_minute_1h"],
    }
    res = client.put("/api/admin/thresholds", json={"items": [item]})
    assert res.status_code == 200

    rows = list_config_history(TEST_DSN, slot=4)
    assert [r["kind"] for r in rows] == ["threshold"]  # rule fields unchanged: no rule row
    assert rows[0]["before"] == {"threshold": old}
    assert rows[0]["after"] == {"threshold": old + 1}


def test_conditions_save_in_admin_writes_history_row(client: TestClient) -> None:
    from kalchas_db.settings import list_config_history

    assert TEST_DSN
    condition = {
        "left_scope": "triggering",
        "left_metric": "npei",
        "operator": ">=",
        "right_kind": "value",
        "right_value": 50,
    }
    for value in (50, 65):
        res = client.put(
            "/api/admin/conditions",
            json={"strategy": "delta_5min", "conditions": [{**condition, "right_value": value}]},
        )
        assert res.status_code == 200

    latest = list_config_history(TEST_DSN, slot=4)[0]
    assert latest["kind"] == "conditions"
    assert latest["strategy_key"] == "delta_5min"
    assert latest["before"][0]["right_value"] == 50.0
    assert latest["after"][0]["right_value"] == 65.0
