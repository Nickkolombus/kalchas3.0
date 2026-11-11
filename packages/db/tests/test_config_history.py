"""Strategy config history: every admin save leaves a before/after row.

The unit tests run everywhere. The Postgres tests run only when
``KALCHAS_TEST_DATABASE_URL`` points at a disposable database: they migrate it to
head and write real config rows.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from kalchas_db import settings
from kalchas_db.settings import config_fingerprints, record_config_change


class _FakeConn:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, _stmt: Any, params: dict[str, Any]) -> None:
        self.calls.append(params)


def test_record_config_change_skips_noop() -> None:
    conn = _FakeConn()
    assert not record_config_change(
        conn,  # type: ignore[arg-type]
        kind="threshold",
        slot=4,
        before={"threshold": 3.0},
        after={"threshold": 3.0},
    )
    assert conn.calls == []


def test_record_config_change_writes_before_and_after() -> None:
    conn = _FakeConn()
    assert record_config_change(
        conn,  # type: ignore[arg-type]
        kind="weights",
        strategy_key="delta_5min",
        before={},
        after={"sot_weight": 0.4},
    )
    (row,) = conn.calls
    assert row["slot"] == 4
    assert row["strategy_key"] == "delta_5min"
    assert row["kind"] == "weights"
    assert json.loads(row["before"]) == {}
    assert json.loads(row["after"]) == {"sot_weight": 0.4}


def test_record_config_change_first_value_has_null_before() -> None:
    conn = _FakeConn()
    record_config_change(
        conn,  # type: ignore[arg-type]
        kind="threshold",
        slot=7,
        before=None,
        after={"threshold": 60.0},
    )
    assert conn.calls[0]["before"] is None
    assert conn.calls[0]["strategy_key"] == "kscore"


def _bundle() -> dict[str, Any]:
    return {
        "thresholds": {1: 1.0, 4: 3.0},
        "weights": {"delta_5min": {"sot_weight": 0.4}},
        "rules": [
            {"strategy_slot": 1, "enabled": True, "cooldown_minutes": 10},
            {"strategy_slot": 4, "enabled": True, "cooldown_minutes": 10},
        ],
        "conditions": {4: [{"left_metric": "npei", "operator": ">=", "right_value": 50.0}]},
    }


def test_config_fingerprints_are_stable_and_per_slot() -> None:
    base = config_fingerprints(_bundle())
    assert set(base) == set(settings.KEY_BY_SLOT)
    assert all(len(v) == 10 for v in base.values())
    assert config_fingerprints(_bundle()) == base

    changed = _bundle()
    changed["thresholds"][4] = 3.5
    after = config_fingerprints(changed)
    assert after[4] != base[4]
    assert after[1] == base[1]

    changed = _bundle()
    changed["conditions"][4][0]["right_value"] = 55.0
    assert config_fingerprints(changed)[4] != base[4]


# --- Postgres -----------------------------------------------------------------

TEST_DSN = os.environ.get("KALCHAS_TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DSN, reason="KALCHAS_TEST_DATABASE_URL not set")


@pytest.fixture
def dsn(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    assert TEST_DSN
    from alembic import command
    from alembic.config import Config
    from kalchas_db import sync
    from sqlalchemy import text

    root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("script_location", str(root / "packages/db/alembic"))
    command.upgrade(cfg, "head")

    monkeypatch.setattr(sync, "_engine", None)
    eng = sync.sync_engine(TEST_DSN)
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE strategy_config_history"))
    yield TEST_DSN
    eng.dispose()


def _history(dsn: str) -> list[dict[str, Any]]:
    return list(reversed(settings.list_config_history(dsn)))


@pg
def test_threshold_save_records_before_and_after(dsn: str) -> None:
    current = settings.list_thresholds(dsn)[4]
    settings.upsert_thresholds(dsn, {4: current + 0.5, 1: settings.list_thresholds(dsn)[1]})
    rows = _history(dsn)
    assert len(rows) == 1  # slot 1 was rewritten unchanged: no row
    row = rows[0]
    assert (row["kind"], row["strategy_slot"], row["strategy_key"]) == (
        "threshold",
        4,
        "delta_5min",
    )
    assert row["before"] == {"threshold": current}
    assert row["after"] == {"threshold": current + 0.5}
    assert row["changed_at"] is not None


@pg
def test_rule_update_records_changed_rule(dsn: str) -> None:
    rule = next(r for r in settings.list_admin_rules(dsn) if r["strategy_slot"] == 7)
    fields = dict(rule)
    fields["cooldown_minutes"] = int(rule["cooldown_minutes"]) + 5
    fields["max_fire_minute"] = 80
    settings.update_admin_rule(dsn, 7, fields)
    (row,) = _history(dsn)
    assert row["kind"] == "rule"
    assert row["before"]["cooldown_minutes"] == rule["cooldown_minutes"]
    assert row["after"]["cooldown_minutes"] == rule["cooldown_minutes"] + 5
    assert row["after"]["max_fire_minute"] == 80

    settings.update_admin_rule(dsn, 7, fields)  # same values again
    assert len(_history(dsn)) == 1


@pg
def test_team_specific_patch_records_rule_change(dsn: str) -> None:
    from kalchas_db.rules import set_team_specific

    rule = next(r for r in settings.list_admin_rules(dsn) if r["strategy_slot"] == 2)
    set_team_specific(dsn, 2, not rule["team_specific"])
    (row,) = _history(dsn)
    assert row["kind"] == "rule"
    assert row["before"] == {"team_specific": rule["team_specific"]}
    assert row["after"] == {"team_specific": not rule["team_specific"]}


@pg
def test_conditions_replace_records_old_and_new_lists(dsn: str) -> None:
    first = [
        {"left_scope": "triggering", "left_metric": "npei", "operator": ">=", "right_value": 50}
    ]
    settings.replace_strategy_conditions(dsn, 4, [])
    settings.replace_strategy_conditions(dsn, 4, first)
    second = [{**first[0], "right_value": 60}]
    stored = settings.replace_strategy_conditions(dsn, 4, second)
    assert stored[0]["right_value"] == 60.0
    rows = [r for r in _history(dsn) if r["kind"] == "conditions"]
    assert rows[-1]["before"][0]["right_value"] == 50.0
    assert rows[-1]["after"][0]["right_value"] == 60.0
    assert rows[-2]["before"] == []


@pg
def test_weight_upsert_reset_and_replace_each_record_one_row(dsn: str) -> None:
    settings.reset_weights(dsn, "delta_5min")
    before_count = len(_history(dsn))

    settings.upsert_weight(dsn, "delta_5min", "sot_weight", 0.4)
    settings.replace_weights(dsn, "delta_5min", {"sot_weight": 0.5, "sofft_weight": 0.1})
    settings.reset_weights(dsn, "delta_5min", "sofft_weight")
    rows = _history(dsn)[before_count:]
    assert [r["kind"] for r in rows] == ["weights"] * 3
    assert rows[0]["before"] == {} and rows[0]["after"] == {"sot_weight": 0.4}
    assert rows[1]["after"] == {"sot_weight": 0.5, "sofft_weight": 0.1}
    assert rows[2]["after"] == {"sot_weight": 0.5}
    assert all(r["strategy_slot"] == 4 for r in rows)
