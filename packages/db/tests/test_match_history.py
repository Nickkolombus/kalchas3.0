"""Stale-match cleanup keeps a copy of each match in `match_history`.

The unit tests run everywhere. The Postgres tests run only when
``KALCHAS_TEST_DATABASE_URL`` points at a disposable database.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from kalchas_db import matches
from sqlalchemy.exc import ProgrammingError


class _Result:
    rowcount = 3


class _Nested:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeConn:
    def __init__(self, fail_on: Any = None) -> None:
        self.statements: list[Any] = []
        self.fail_on = fail_on

    def begin_nested(self) -> _Nested:
        return _Nested()

    def execute(self, stmt: Any, _params: dict[str, Any]) -> _Result:
        if stmt is self.fail_on:
            raise ProgrammingError(
                "INSERT", {}, Exception('relation "match_history" does not exist')
            )
        self.statements.append(stmt)
        return _Result()


class _FakeEngine:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    def begin(self) -> Any:
        conn = self.conn

        class _Ctx:
            def __enter__(self) -> _FakeConn:
                return conn

            def __exit__(self, *exc: object) -> bool:
                return False

        return _Ctx()


def _run(monkeypatch: pytest.MonkeyPatch, conn: _FakeConn, **kwargs: Any) -> int:
    monkeypatch.setattr(matches, "sync_engine", lambda _dsn: _FakeEngine(conn))
    return matches.delete_stale_matches_sync("postgresql://x", **kwargs)


def test_cleanup_archives_then_prunes_then_deletes(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    assert _run(monkeypatch, conn) == 3
    assert conn.statements == [
        matches.ARCHIVE_STALE_MATCHES,
        matches.PRUNE_MATCH_HISTORY,
        matches.DELETE_STALE_MATCHES,
    ]


def test_cleanup_without_history_only_deletes(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    _run(monkeypatch, conn, history_days=0)
    assert conn.statements == [matches.DELETE_STALE_MATCHES]


def test_archive_failure_still_cleans_live_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(fail_on=matches.ARCHIVE_STALE_MATCHES)
    assert _run(monkeypatch, conn) == 3
    assert conn.statements == [matches.DELETE_STALE_MATCHES]


def test_archive_and_delete_use_the_same_cutoff() -> None:
    cutoff = "updated_at < NOW() - make_interval(mins => :max_age_minutes)"
    assert cutoff in matches.DELETE_STALE_MATCHES.text
    assert f"m.{cutoff}" in matches.ARCHIVE_STALE_MATCHES.text


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
        conn.execute(text("TRUNCATE match_history"))
        conn.execute(text("DELETE FROM matches WHERE match_id LIKE 'hist-%'"))
    yield TEST_DSN
    eng.dispose()


def _seed(dsn: str, match_id: str, *, hours_ago: int, minutes: int) -> None:
    from kalchas_db.sync import sync_engine
    from sqlalchemy import text

    with sync_engine(dsn).begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO matches (match_id, home_team, away_team, status_short,
                    home_score, away_score, minute, odds, updated_at)
                VALUES (:id, 'Home', 'Away', 'FT', 1, 0, 90,
                    '{"kickoff": {"home": 2.1, "draw": 3.3, "away": 3.6}}'::jsonb,
                    NOW() - make_interval(hours => :h))
                """
            ),
            {"id": match_id, "h": hours_ago},
        )
        for minute in range(minutes):
            conn.execute(
                text(
                    """
                    INSERT INTO match_minutes
                        (match_id, minute, home_stats, away_stats, home_goals, away_goals)
                    VALUES (:id, :m, CAST(:h AS jsonb), '{"shots_on_target": 0}'::jsonb,
                        :g, 0)
                    """
                ),
                {
                    "id": match_id,
                    "m": minute,
                    "h": json.dumps({"shots_on_target": minute // 10}),
                    "g": 1 if minute >= 30 else 0,
                },
            )


def _history(dsn: str) -> dict[str, dict[str, Any]]:
    from kalchas_db.sync import sync_engine
    from sqlalchemy import text

    with sync_engine(dsn).connect() as conn:
        rows = conn.execute(text("SELECT * FROM match_history")).mappings().all()
    return {row["match_id"]: dict(row) for row in rows}


@pg
def test_stale_match_is_archived_with_its_minutes(dsn: str) -> None:
    _seed(dsn, "hist-old", hours_ago=8, minutes=40)
    _seed(dsn, "hist-empty", hours_ago=8, minutes=0)
    _seed(dsn, "hist-live", hours_ago=1, minutes=20)

    deleted = matches.delete_stale_matches_sync(dsn, max_age_minutes=360)

    assert deleted == 2
    history = _history(dsn)
    assert set(history) == {"hist-old"}  # live match kept live, empty one not archived
    row = history["hist-old"]
    assert [m["minute"] for m in row["minutes"]] == list(range(40))
    assert row["minutes"][35]["home"] == {"shots_on_target": 3}
    assert row["minutes"][35]["home_goals"] == 1
    assert row["odds"]["kickoff"]["draw"] == 3.3
    assert matches.get_matches_sync(dsn, ["hist-old", "hist-live"]).keys() == {"hist-live"}


@pg
def test_history_older_than_retention_is_pruned(dsn: str) -> None:
    from kalchas_db.sync import sync_engine
    from sqlalchemy import text

    _seed(dsn, "hist-old", hours_ago=8, minutes=5)
    matches.delete_stale_matches_sync(dsn, max_age_minutes=360)
    with sync_engine(dsn).begin() as conn:
        conn.execute(text("UPDATE match_history SET archived_at = NOW() - INTERVAL '61 days'"))
    matches.delete_stale_matches_sync(dsn, max_age_minutes=360, history_days=60)
    assert _history(dsn) == {}
