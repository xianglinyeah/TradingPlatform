"""PostgreSQL pool wrapper using asyncpg.

Lazy-init on first start() call. The pool is shared across all routers
because handlers run on the asyncio event loop that FastAPI owns.

Schema notes (we do NOT own these tables - we read):
  - execution_service.orders(session_id, symbol, side, quantity,
        avg_fill_price, commission, status, filled_at, ...)
  - execution_service.trades(...)
  - fundamentals.daily_valuation(symbol, trade_date, pe_ttm, pb_lyr, ...)
  - public.kline_min_metadata(symbol, trade_date, status)

We DO own one table:
  - dashboard.runs - parameters + status of each backtest run, written
    by the orchestration endpoint and queried by the history endpoint.
    Created on startup via migrate().
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

from ..config.settings import settings

logger = logging.getLogger("dashboard_service.db.postgres")


class PostgresPool:
    """Thin wrapper around an asyncpg.Pool.

    The pool is created lazily so the app can boot in test/CI envs
    that do not have a database.
    """

    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None

    async def start(self) -> None:
        if self._pool is not None:
            return
        dsn = (
            f"postgresql://{settings.pg_user}:{settings.pg_password}"
            f"@{settings.pg_host}:{settings.pg_port}/{settings.pg_database}"
        )
        self._pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=settings.pg_pool_min,
            max_size=settings.pg_pool_max,
            command_timeout=30,
        )
        await self._migrate()
        logger.info("Postgres pool ready (%s:%s/%s)",
                    settings.pg_host, settings.pg_port, settings.pg_database)

    async def stop(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Postgres pool not started")
        return self._pool

    async def _migrate(self) -> None:
        """Create dashboard.runs if missing. Idempotent."""
        async with self._pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS dashboard;")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard.runs (
                    run_id           VARCHAR PRIMARY KEY,
                    strategy_name    VARCHAR NOT NULL,
                    strategy_params  JSONB   NOT NULL DEFAULT '{}'::jsonb,
                    symbols          TEXT[]  NOT NULL DEFAULT '{}',
                    start_date       VARCHAR,
                    end_date         VARCHAR,
                    speed            DOUBLE PRECISION,
                    replay_session_id VARCHAR,
                    status           VARCHAR NOT NULL DEFAULT 'pending',
                    total_pnl        DOUBLE PRECISION,
                    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                    error_message    TEXT
                );
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dashboard_runs_created_at "
                "ON dashboard.runs(created_at DESC);"
            )

    async def fetch(self, sql: str, *args: Any) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql, *args)

    async def fetchrow(self, sql: str, *args: Any) -> Optional[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql, *args)

    async def execute(self, sql: str, *args: Any) -> str:
        async with self._pool.acquire() as conn:
            return await conn.execute(sql, *args)


postgres_pool = PostgresPool()
