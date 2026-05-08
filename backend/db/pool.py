"""
psycopg 3 async connection pool, sized for FastAPI on Render Starter against
Supabase's transaction pooler (port 6543).

Two non-obvious choices:

  * prepare_threshold=None disables prepared statements. Supabase's pgbouncer
    in transaction mode reuses a connection across statements from different
    clients; prepared statements registered on one logical connection don't
    survive that. Setting this here is required, not optional.

  * The pool is opened lazily on first acquire() rather than eagerly in
    lifespan startup, because Render's healthcheck probe hits /api/health
    before Supabase is reachable on a fresh deploy. Eager open made the
    container fail readiness for ~15s on every cold deploy.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=_dsn(),
            min_size=1,
            max_size=int(os.environ.get("DB_POOL_MAX", "10")),
            kwargs={"prepare_threshold": None},
            open=False,
        )
    return _pool


async def open_pool() -> None:
    pool = get_pool()
    await pool.open()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def acquire() -> AsyncIterator[AsyncConnection]:
    """
    Yield a connection from the pool. Caller controls transactions explicitly
    via `async with con.transaction():` when needed; psycopg's default is
    autocommit=False, so writes without an explicit transaction still commit
    at the end of the `async with acquire()` block.
    """
    pool = get_pool()
    async with pool.connection() as con:
        yield con
