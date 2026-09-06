"""Single asyncpg pool for all Kalchas services."""

from __future__ import annotations

import os
from typing import Any

import asyncpg

_pool: asyncpg.Pool | None = None


def database_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    # SQLAlchemy/Alembic accept postgresql://; asyncpg wants postgresql:// or postgres://
    return url


async def create_pool(
    dsn: str | None = None,
    *,
    min_size: int = 1,
    max_size: int = 5,
) -> asyncpg.Pool:
    """Create (or replace) the process-wide pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
    _pool = await asyncpg.create_pool(
        dsn or database_url(),
        min_size=min_size,
        max_size=max_size,
    )
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("create_pool() has not been called")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    return await get_pool().fetch(query, *args)


async def execute(query: str, *args: Any) -> str:
    return await get_pool().execute(query, *args)
