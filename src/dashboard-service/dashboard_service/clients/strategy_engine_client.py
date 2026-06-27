"""HTTP client for strategy-engine's run-control API.

Wraps the endpoints exposed by strategy_engine.src.run.api_server:

    POST   /runs/{run_id}/config
    GET    /strategies
    GET    /runs/{run_id}
    DELETE /runs/{run_id}

We share one httpx.AsyncClient across the process - that lets HTTP/1.1
keep-alive do its job and bounds the connection count.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config.settings import settings

logger = logging.getLogger("dashboard_service.clients.strategy_engine")


class StrategyEngineClient:
    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        # one shared client; timeouts generous because Kafka processing
        # can briefly delay the FastAPI worker on the strategy-engine side.
        self._client = httpx.AsyncClient(
            base_url=settings.strategy_engine_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            # Lazy init for tests that didn't call start().
            self._client = httpx.AsyncClient(
                base_url=settings.strategy_engine_url,
                timeout=httpx.Timeout(10.0, connect=5.0),
            )
        return self._client

    async def register_run(
        self,
        run_id: str,
        strategy_name: str,
        params: dict,
        symbols: Optional[list[str]] = None,
        exclude_symbols: Optional[list[str]] = None,
    ) -> dict:
        body: dict[str, Any] = {"strategy_name": strategy_name, "params": params}
        if symbols is not None:
            body["symbols"] = symbols
        if exclude_symbols is not None:
            body["exclude_symbols"] = exclude_symbols
        resp = await self.client.post(f"/runs/{run_id}/config", json=body)
        resp.raise_for_status()
        return resp.json()

    async def delete_run(self, run_id: str) -> None:
        resp = await self.client.delete(f"/runs/{run_id}")
        # 404 is fine - run may already be cleaned up.
        if resp.status_code not in (200, 404):
            resp.raise_for_status()

    async def list_strategies(self) -> dict:
        resp = await self.client.get("/strategies")
        resp.raise_for_status()
        return resp.json()

    async def get_run(self, run_id: str) -> Optional[dict]:
        resp = await self.client.get(f"/runs/{run_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


strategy_engine_client = StrategyEngineClient()
