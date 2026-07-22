# Research scripts

Scripts under this directory are **one-off alpha research** — vectorized
pandas/numpy validations run on the host against the live platform's data
sources. They are **not** part of `strategy-engine`, are not deployed to k8s,
and do not share `strategy-engine`'s dependencies.

## Why a separate home

`strategy-engine`'s old `research` mode ran an event-driven `BacktestEngine`
over minute bars. Daily-frequency alpha discovery (which is what these scripts
target) is much better served by vectorized pandas on wide DataFrames than by
per-bar dispatch, so the two toolchains are deliberately kept apart. That
event-driven `BacktestEngine` has been deleted; this directory replaces its
"research" use case with the right tool for the job.

## Running

From the project root (so the `scripts.research.*` import path resolves):

```bash
python -m scripts.research.volume_breakout_alpha
```

The script writes a stdout table and `volume_breakout_alpha_results.csv`.

## Host dependencies

These scripts are run from the host Python, not from any service container.
Install on the host once:

```bash
pip install psycopg2-binary clickhouse-connect pandas scipy
```

## Connection defaults

Helpers in `common/db.py` default to the in-cluster service DNS
(`clickhouse.infrastructure:8123`, `postgres.infrastructure:5432`). When
running from outside the cluster, port-forward those services and override via
environment variables (`CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `PG_HOST`,
`PG_PORT`, ...) — the helpers read them with sensible defaults.

## Schema notes (verified against ingestion code)

- Daily OHLCV: `market_data.kline_daily` in ClickHouse, columns `trade_time`,
  `ts_code`, `open`, `high`, `low`, `close`, `volume`, `amount`. Symbols in
  TS format (`600000.SH`).
- Turnover rate: `fundamentals.daily_basic` in PostgreSQL, column `turnrate`,
  keyed by `(symbol, trade_date)`. The `symbol` column format is normalized
  defensively on load (see `volume_breakout_alpha._normalize_to_ts`).
