# Dashboard.Service

Unified REST API gateway for Dashboard.Web. Owns:

- **Read-only data queries** against ClickHouse (K-line bars) and PostgreSQL (fundamentals, runs, orders).
- **Backtest orchestration**: coordinates `strategy-engine` and `market-data-replay` to start a replay run.
- **Historical run results**: aggregates Execution.Service orders into summaries, PnL curves, trade tables.

Front-end (Dashboard.Web) talks ONLY to this service. It never touches Kafka, ClickHouse, or PostgreSQL directly.

## Architecture

See [`docs/temp/dashboard-service-spec.md`](../../docs/temp/dashboard-service-spec.md) and [`docs/temp/marketdata-replay-strategy-engine-spec.md`](../../docs/temp/marketdata-replay-strategy-engine-spec.md) for the full design.

```
Dashboard.Web  --REST-->  Dashboard.Service  --+--> ClickHouse (klines)
                                               +--> PostgreSQL (fundamentals, runs, orders)
                                               +--> strategy-engine /runs/{run_id}/config, /strategies
                                               +--> market-data-replay /api/Replay/start|status|stop
```

## API surface

| Endpoint | Purpose |
|----------|---------|
| `GET /api/kline/{symbol}` | K-line bars (interval 1m/1d) |
| `GET /api/fundamentals/{symbol}` | PE/PB/div-yield/turnover history |
| `GET /api/symbols` | Symbol search typeahead |
| `GET /api/strategies` | Strategy metadata (proxied to strategy-engine) |
| `POST /api/backtest/run` | Trigger a backtest; orchestrates register-config -> start-replay |
| `GET /api/backtest/{run_id}/status` | Live status (proxied to market-data-replay) |
| `POST /api/backtest/{run_id}/stop` | Stop a running backtest |
| `GET /api/backtest/runs` | Historical runs list |
| `GET /api/backtest/{run_id}/results` | Summary + PnL curve + trades |
| `GET /api/backtest/compare?run_ids=a,b` | Side-by-side comparison |

## Critical ordering invariant

When triggering a backtest, the orchestration endpoint MUST register the strategy config in strategy-engine BEFORE the first Kafka bar arrives. See `dashboard_service/routers/backtest.py` for details on how we use market-data-replay's RESET control message to safely interleave the two calls.

## Configuration

All configuration is environment-driven; defaults point at in-cluster K8s service DNS.

| Env var | Default | Purpose |
|---------|---------|---------|
| `DASHBOARD_HOST` | `0.0.0.0` | HTTP bind host |
| `DASHBOARD_PORT` | `8080` | HTTP bind port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated origin list |
| `PG_HOST` / `PG_PORT` / `PG_DATABASE` / `PG_USER` / `PG_PASSWORD` | `postgres.infrastructure` / `5432` / `dev` / `dev_user` / `dev_pass` | PostgreSQL connection |
| `CH_HOST` / `CH_PORT` / `CH_DATABASE` / `CH_USER` / `CH_PASSWORD` | `clickhouse.infrastructure` / `8123` / `market_data` / `default` / (empty) | ClickHouse connection |
| `STRATEGY_ENGINE_URL` | `http://strategy-engine:8080` | strategy-engine base URL |
| `MARKETDATA_REPLAY_URL` | `http://market-data-replay:8080` | market-data-replay base URL |

## Local development

```bash
cd src/dashboard-service
pip install -r requirements.txt

# Set env vars to point at port-forwarded services, then:
python -m dashboard_service.main
# or
uvicorn dashboard_service.main:app --reload --port 8080
```

OpenAPI docs at `http://localhost:8080/docs`.
