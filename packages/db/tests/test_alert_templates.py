"""Bot-side reads of admin alert templates (migration 0035)."""

from __future__ import annotations

from typing import Any

import pytest
from kalchas_db.alert_templates import fetch_active_templates, record_fallback


class _Conn:
    def __init__(self, rows: list[dict[str, Any]] | None = None, fail: bool = False) -> None:
        self.rows = rows or []
        self.fail = fail
        self.executed: list[tuple[Any, ...]] = []

    async def fetch(self, _sql: str) -> list[dict[str, Any]]:
        if self.fail:
            raise RuntimeError('relation "alert_templates" does not exist')
        return self.rows

    async def execute(self, _sql: str, *args: Any) -> None:
        self.executed.append(args)


@pytest.mark.asyncio
async def test_active_templates_keyed_by_strategy_channel_and_kind() -> None:
    conn = _Conn(
        [
            {"strategy": "default", "channel": "paid", "kind": "alert", "body": "{home}"},
            {"strategy": "delta_5min", "channel": "x", "kind": "miss", "body": "{team}"},
            {"strategy": "default", "channel": "free", "kind": "goal", "body": "   "},
        ]
    )
    assert await fetch_active_templates(conn) == {  # type: ignore[arg-type]
        ("default", "paid", "alert"): "{home}",
        ("delta_5min", "x", "miss"): "{team}",
    }


@pytest.mark.asyncio
async def test_missing_table_means_no_templates() -> None:
    assert await fetch_active_templates(_Conn(fail=True)) == {}  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_fallback_reason_is_capped() -> None:
    conn = _Conn()
    await record_fallback(conn, "kscore", "paid", "alert", "x" * 900)  # type: ignore[arg-type]
    assert conn.executed[0][:3] == ("kscore", "paid", "alert")
    assert len(conn.executed[0][3]) == 500
