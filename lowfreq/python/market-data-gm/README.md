# market-data-gm (Python)

Python rewrite of the C# `market_data_gm` service. Subscribes to GM SDK
real-time bars and publishes them to Kafka topic `market.data` in the same JSON
shape StrategyService already consumes.

## Why Python

The C# version depends on `gmsdk-net-x64` (Windows-only), which blocks
k8s/Linux deployment. The Python `gm` SDK is cross-platform.

## Layout

```
main.py                      Entry point: load config → Kafka → gm.run()
config.py / config.yaml      YAML config (replaces appsettings.json)
requirements.txt             gm, confluent-kafka, pyyaml
services/
    gm_strategy.py           init() / on_bar() / on_error() callbacks
    kafka_producer.py        confluent-kafka wrapper
    market_event.py          MarketDataEvent dataclass + JSON serializer
    symbol_converter.py      SHSE.600000 ↔ 600000.SH
```

## Run

```bash
pip install -r requirements.txt
python main.py config.yaml
```

Consume Kafka to verify:

```bash
kafka-console-consumer --bootstrap-server localhost:9092 \
    --topic market.data --from-beginning
```

## Kafka message JSON (byte-compatible with C# version)

```json
{
  "Symbol": "600000.SH",
  "EventTime": "2026-06-22T09:30:00+08:00",
  "ReplayTime": "2026-06-22T01:30:00Z",
  "Open": 7.19, "High": 7.20, "Low": 7.18, "Close": 7.19,
  "Volume": 10000, "Amount": 719000,
  "SessionId": "gm-realtime-20260622-093015",
  "SequenceNumber": 1,
  "Source": "GM"
}
```

## Differences from C#

| Aspect        | C#                                | Python                              |
|---------------|-----------------------------------|-------------------------------------|
| Config        | `appsettings.json` + DI           | `config.yaml` + dataclass           |
| Logging       | Serilog (file + console)          | `logging.RotatingFileHandler`       |
| Kafka client  | `Confluent.Kafka`                 | `confluent-kafka`                   |
| GM SDK        | `gmsdk-net-x64` (Windows only)    | `gm` (cross-platform)               |
| Callbacks     | Class `Strategy` overrides        | Module-level `init`/`on_bar` funcs  |

## Git history

The original C# source (`GMMarketDataService.cs`, `Program.cs`, `Utils/`,
`appsettings.json`) is preserved in git history at the last commit before
this rewrite.
