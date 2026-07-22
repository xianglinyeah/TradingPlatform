"""Application settings - environment-driven with safe defaults.

All values can be overridden by env vars, which is how K8s injects them
via configmaps/secrets. The defaults point at the in-cluster service
DNS names so a `kubectl port-forward` from local dev also works once
the relevant env vars are set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    # --- HTTP server ---
    host: str = field(default_factory=lambda: _env("DASHBOARD_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("DASHBOARD_PORT", "8080")))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    # Comma-separated origin list. Empty disables CORS middleware.
    cors_allowed_origins: str = field(
        default_factory=lambda: _env(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://localhost:3000",
        )
    )

    # --- PostgreSQL (fundamentals, runs, orders) ---
    pg_host: str = field(default_factory=lambda: _env("PG_HOST", "postgres.infrastructure"))
    pg_port: int = field(default_factory=lambda: int(_env("PG_PORT", "5432")))
    pg_database: str = field(default_factory=lambda: _env("PG_DATABASE", "dev"))
    pg_user: str = field(default_factory=lambda: _env("PG_USER", "dev_user"))
    pg_password: str = field(default_factory=lambda: _env("PG_PASSWORD", "dev_pass"))
    pg_pool_min: int = field(default_factory=lambda: int(_env("PG_POOL_MIN", "2")))
    pg_pool_max: int = field(default_factory=lambda: int(_env("PG_POOL_MAX", "10")))

    # --- ClickHouse (kline bars) ---
    ch_host: str = field(default_factory=lambda: _env("CH_HOST", "clickhouse.infrastructure"))
    ch_port: int = field(default_factory=lambda: int(_env("CH_PORT", "8123")))
    ch_database: str = field(default_factory=lambda: _env("CH_DATABASE", "market_data"))
    ch_user: str = field(default_factory=lambda: _env("CH_USER", "default"))
    ch_password: str = field(default_factory=lambda: _env("CH_PASSWORD", ""))

    # --- Downstream services ---
    strategy_engine_url: str = field(
        default_factory=lambda: _env(
            "STRATEGY_ENGINE_URL", "http://strategy-engine:8080"
        )
    )
    marketdata_replay_url: str = field(
        default_factory=lambda: _env(
            "MARKETDATA_REPLAY_URL", "http://market-data-replay:8080"
        )
    )

    # --- Backtest orchestration ---
    # How long to keep a run row marked 'running' before giving up on it
    # during status polling (seconds).
    backtest_status_poll_timeout_s: int = field(
        default_factory=lambda: int(_env("BACKTEST_POLL_TIMEOUT_S", "3600"))
    )


settings = Settings()
