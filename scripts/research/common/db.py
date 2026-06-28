"""DB connection helpers for research scripts.

These clients target the same infrastructure the live services use, but run
from the host (or a developer pod) for ad-hoc vectorized analysis. Both
functions return pandas DataFrames so callers can stay in pandas idioms.

Connection defaults follow the values used across the platform:
  - ClickHouse: HTTP port 8123, db ``market_data``, user ``dev_user``.
  - PostgreSQL: db ``dev`` on ``postgres.infrastructure:5432``.

Defaults can be overridden via environment variables (``CLICKHOUSE_HOST``,
``CLICKHOUSE_PORT``, ``CLICKHOUSE_DATABASE``, ``PG_HOST`` ...) so the same
helpers work against a local docker-compose stack and against k8s port-forwards.
"""
from __future__ import annotations

import os
from typing import Optional

import clickhouse_connect
import pandas as pd
import psycopg2


# --- ClickHouse -----------------------------------------------------------

def _ch_kwargs(**overrides):
    """Build ClickHouse client kwargs from env with sensible defaults."""
    return {
        "host": os.getenv("CLICKHOUSE_HOST", "clickhouse.infrastructure"),
        "port": int(os.getenv("CLICKHOUSE_PORT", "8123")),
        "username": os.getenv("CLICKHOUSE_USER", "dev_user"),
        "password": os.getenv("CLICKHOUSE_PASSWORD", "dev_pass"),
        "database": os.getenv("CLICKHOUSE_DATABASE", "market_data"),
        **overrides,
    }


def query_clickhouse(sql: str, params: Optional[dict] = None) -> pd.DataFrame:
    """Run a SELECT and return the result as a DataFrame.

    Uses the HTTP-based clickhouse-connect client (port 8123). This matches
    the dashboard-service / data-ingestion pattern; nothing here needs the
    native TCP protocol.
    """
    client = clickhouse_connect.get_client(**_ch_kwargs())
    try:
        return client.query_df(sql, parameters=params or {})
    finally:
        client.close()


# --- PostgreSQL -----------------------------------------------------------

def _pg_kwargs(**overrides):
    """Build psycopg2 connect kwargs from env with sensible defaults."""
    return {
        "host": os.getenv("PG_HOST", "postgres.infrastructure"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "dbname": os.getenv("PG_DATABASE", "dev"),
        "user": os.getenv("PG_USER", "dev_user"),
        "password": os.getenv("PG_PASSWORD", "dev_pass"),
        **overrides,
    }


def query_postgres(sql: str, params: Optional[dict] = None) -> pd.DataFrame:
    """Run a SELECT and return the result as a DataFrame.

    Synchronous psycopg2 is plenty for ad-hoc research queries; asyncpg would
    just complicate the call sites without measurable benefit at these row
    counts.
    """
    conn = psycopg2.connect(**_pg_kwargs())
    try:
        return pd.read_sql_query(sql, conn, params=params or ())
    finally:
        conn.close()
