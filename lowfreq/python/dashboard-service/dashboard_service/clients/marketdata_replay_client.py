"""HTTP client for market-data-replay's REST API.

MarketData.Replay is the C# service at lowfreq/dotnet/market-data-replay/. Its
endpoints (note the /api/Replay prefix and path-style session ids):

    POST   /api/Replay/start                 -> creates session, returns SessionId
    GET    /api/Replay/status/{id}
    POST   /api/Replay/stop/{id}
    POST   /api/Replay/pause/{id}
    POST   /api/Replay/resume/{id}

We map these to a Pythonic surface used by the orchestration router.

CRITICAL ORDERING (spec section 4): we MUST register the strategy
config in strategy-engine BEFORE calling /start here, otherwise the
first batch of Kafka bars will arrive at strategy-engine without a
matching run_id and be silently dropped.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config.settings import settings

logger = logging.getLogger("dashboard_service.clients.marketdata_replay")


class MarketDataReplayClient:
    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.marketdata_replay_url,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.marketdata_replay_url,
                timeout=httpx.Timeout(15.0, connect=5.0),
            )
        return self._client

    async def start_replay(
        self,
        symbols: Optional[list[str]] = None,
        start_time: str = "",
        end_time: str = "",
        speed_factor: float = 1000.0,
        universe_id: Optional[str] = None,
    ) -> dict:
        """POST /api/Replay/start.

        market-data-replay generates the SessionId server-side; we
        return it so the orchestrator can use it as the run_id
        (per the ADR: run_id == SessionId).

        Either `symbols` (explicit list) or `universe_id` (resolved
        point-in-time by the replay service from market_ref) must be
        provided. When both are passed, Symbols wins.
        """
        body: dict[str, Any] = {
            "Symbols": symbols or [],
            "StartTime": start_time,
            "EndTime": end_time,
            "SpeedFactor": speed_factor,
        }
        if universe_id:
            body["UniverseId"] = universe_id
        # The C# controller uses PascalCase JSON by default.
        resp = await self.client.post("/api/Replay/start", json=body)
        resp.raise_for_status()
        return resp.json()

    async def get_status(self, session_id: str) -> dict:
        resp = await self.client.get(f"/api/Replay/status/{session_id}")
        resp.raise_for_status()
        return resp.json()

    async def stop_replay(self, session_id: str) -> dict:
        resp = await self.client.post(f"/api/Replay/stop/{session_id}")
        resp.raise_for_status()
        return resp.json()

    async def pause_replay(self, session_id: str) -> dict:
        resp = await self.client.post(f"/api/Replay/pause/{session_id}")
        resp.raise_for_status()
        return resp.json()

    async def resume_replay(self, session_id: str) -> dict:
        resp = await self.client.post(f"/api/Replay/resume/{session_id}")
        resp.raise_for_status()
        return resp.json()


marketdata_replay_client = MarketDataReplayClient()
