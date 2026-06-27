"""Dashboard.Service - unified backtest control + data browsing API.

This service is the SOLE entry point for Dashboard.Web. It owns:
  - read-only data queries against ClickHouse (klines) and PostgreSQL
    (fundamentals, runs, orders)
  - backtest orchestration: strict-order coordination between
    strategy-engine (register config) and market-data-replay (start),
    see marketdata-replay-strategy-engine-spec.md section 4
  - historical run queries for the results / compare pages

Configuration is environment-driven for K8s, with safe local defaults.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config.settings import settings
from .db.postgres import postgres_pool
from .db.clickhouse import clickhouse_client
from .clients import strategy_engine_client, marketdata_replay_client
from .routers import kline, fundamentals, backtest, strategies, symbols


logger = logging.getLogger("dashboard_service")


def _setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="[%(levelname).3s] %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown of DB pools and HTTP clients."""
    _setup_logging()
    logger.info("Dashboard.Service starting up")
    await postgres_pool.start()
    clickhouse_client.start()
    await strategy_engine_client.start()
    await marketdata_replay_client.start()
    try:
        yield
    finally:
        await marketdata_replay_client.stop()
        await strategy_engine_client.stop()
        await postgres_pool.stop()
        clickhouse_client.stop()
        logger.info("Dashboard.Service shut down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dashboard.Service",
        version="1.0.0",
        description="Unified backtest control + data browsing API for Dashboard.Web",
        lifespan=lifespan,
    )

    # Permissive CORS for local dev. In production, restrict via env.
    allowed = settings.cors_allowed_origins
    if allowed:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in allowed.split(",") if o.strip()],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(kline.router, prefix="/api")
    app.include_router(fundamentals.router, prefix="/api")
    app.include_router(backtest.router, prefix="/api")
    app.include_router(strategies.router, prefix="/api")
    app.include_router(symbols.router, prefix="/api")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "dashboard_service.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )
