"""ClickHouse client wrapper using clickhouse-connect.

ClickHouse holds k-line bars in two tables under the configured database:

  kline_1min(trade_time DateTime, ts_code String, open, close, high, low,
             volume UInt64, amount Float64)
  kline_daily(...same columns, daily granularity)

Both tables are written by data-ingestion. We only ever SELECT here -
Dashboard.Service is read-only against ClickHouse.

clickhouse-connect is synchronous; we wrap calls in run_in_executor so
FastAPI handlers stay async-friendly. The volume of K-line data we
return is bounded by the date range the user picks, so blocking the
executor briefly is acceptable.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from ..config.settings import settings

logger = logging.getLogger("dashboard_service.db.clickhouse")


class ClickHouse:
    """Lazy-managed ClickHouse HTTP client.

    clickhouse-connect clients are cheap to create and not thread-safe
    across shared use; we keep one per process and serialize access via
    the executor (CH queries are short).
    """

    def __init__(self) -> None:
        self._client: Optional[Client] = None

    def start(self) -> None:
        if self._client is not None:
            return
        self._client = clickhouse_connect.get_client(
            host=settings.ch_host,
            port=settings.ch_port,
            username=settings.ch_user,
            password=settings.ch_password,
            database=settings.ch_database,
            connect_timeout=10,
            send_receive_timeout=30,
        )
        logger.info("ClickHouse client ready (%s:%s/%s)",
                    settings.ch_host, settings.ch_port, settings.ch_database)

    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def client(self) -> Client:
        if self._client is None:
            raise RuntimeError("ClickHouse client not started")
        return self._client

    async def query(self, sql: str, parameters: Optional[dict] = None) -> Any:
        """Run a SELECT in a worker thread and return the result rows.

        Each row is returned as a dict (clickhouse-connect `query_result`
        named results when `as_=True` is not used; we convert manually).
        """
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None, lambda: self.client.query(sql, parameters=parameters)
        )
        cols = res.column_names
        return [dict(zip(cols, row)) for row in res.result_rows]


clickhouse_client = ClickHouse()
