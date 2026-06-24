![Architecture](architecture.svg)

## Services

| Service | Language | Description |
|---|---|---|
| **data-ingestion** | Python (CronJob) | Daily incremental fetch of A-share kline and fundamentals from GM API. Writes to Parquet, PostgreSQL, and ClickHouse. |
| **market-data-gm** | Python | Subscribes to real-time market data via GM SDK, publishes 1-minute bars to Kafka. |
| **market-data-replay** | C# | Reads historical Parquet files and replays them into Kafka at configurable speed (1x–10000x). |
| **strategy-engine** | Python | Consumes market data from Kafka, runs trading strategies, sends order signals to Execution Service via gRPC. Supports research (local backtest) and live modes. |
| **execution-service** | C# | Order Management System. Receives orders, applies T+1 market rules and risk checks, routes to sim/paper/live execution adapter. |
| **execution-adapter-gm** | Python | Translates gRPC orders to GM SDK calls. Bridges the Execution Service to the broker (paper/live trading). |

## Infrastructure

Kafka, PostgreSQL, ClickHouse, Grafana + Loki + Promtail — all on Kubernetes (Rancher Desktop).
