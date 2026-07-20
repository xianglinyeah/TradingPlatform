-- Reporting schema for the Java HFT pipeline (paper trading / backtest analytics).
-- Applied via scripts/reporting/apply_schema.ps1 against the Rancher Desktop
-- ClickHouse (localhost:8123, user dev_user).
--
-- Conventions:
--  * Column names mirror the JSONL field names exactly (camelCase) so files
--    import as-is via JSONEachRow; runId/mode are injected by the import script.
--  * JSONL stays the capture source of truth; everything here is derived and
--    can be dropped/rebuilt at any time. Nothing writes here from the hot path.
--  * Money-ish fields (qty/price/fee) are Decimal; md analytics are Float64.

CREATE DATABASE IF NOT EXISTS hft;

CREATE TABLE IF NOT EXISTS hft.sim_fills
(
    runId         LowCardinality(String),
    mode          LowCardinality(String),           -- imbalance | arb
    fillId        UInt64,
    orderId       UInt64,
    tsEpochNanos  Int64,                            -- fill clock = md-stream recvTs
    ts            DateTime64(9, 'UTC') MATERIALIZED fromUnixTimestamp64Nano(tsEpochNanos),
    venue         LowCardinality(String) DEFAULT 'COINBASE',  -- absent in early single-venue files
    product       LowCardinality(String),
    side          LowCardinality(String),           -- BUY | SELL
    requestedQty  Decimal(38, 18),
    filledQty     Decimal(38, 18),
    avgPrice      Decimal(38, 18),
    fee           Decimal(38, 18),
    partial       Bool,
    posAfter      Float64,
    realizedAfter Float64
)
ENGINE = MergeTree
ORDER BY (runId, ts, fillId);

CREATE TABLE IF NOT EXISTS hft.orders
(
    runId        LowCardinality(String),
    mode         LowCardinality(String),
    id           UInt64,
    arbId        Nullable(UInt64),                  -- arb mode: both legs share it
    symbol       Nullable(String),                  -- arb mode: cross-venue symbol (BTC)
    tsEpochNanos Int64,
    ts           DateTime64(9, 'UTC') MATERIALIZED fromUnixTimestamp64Nano(tsEpochNanos),
    venue        LowCardinality(String) DEFAULT 'COINBASE',
    product      LowCardinality(String),
    side         LowCardinality(String),
    qty          Decimal(38, 18),
    price        Decimal(38, 18),                   -- touch price at signal time
    imbalance    Nullable(Float64),                 -- imbalance mode only
    srcPseq      Nullable(Int64),
    exchTs       Nullable(Int64),
    pubTs        Nullable(Int64),
    devBps       Nullable(Float64),                 -- arb mode only
    emaBps       Nullable(Float64)
)
ENGINE = MergeTree
ORDER BY (runId, ts, id);

-- Top-of-book stream exported from the Chronicle md queues (MdTopExporter).
-- One row per best-bid/ask change, not per delta doc.
CREATE TABLE IF NOT EXISTS hft.md_top
(
    venue            LowCardinality(String),
    product          LowCardinality(String),
    pseq             Int64,
    recvTsEpochNanos Int64,                         -- publisher WS receive time
    ts               DateTime64(9, 'UTC') MATERIALIZED fromUnixTimestamp64Nano(recvTsEpochNanos),
    bestBid          Float64,
    bestAsk          Float64,
    bidQty           Float64,                       -- displayed qty at best bid
    askQty           Float64,
    mid              Float64 MATERIALIZED (bestBid + bestAsk) / 2
)
ENGINE = MergeTree
ORDER BY (venue, product, ts);

-- Per-second md flow/latency aggregates from MdTopExporter's stats output
-- (same replay pass as md_top). recvToPub is same-host, skew-free; exchToRecv
-- is signed epoch math including cross-clock skew.
CREATE TABLE IF NOT EXISTS hft.md_stats
(
    venue            LowCardinality(String),
    product          LowCardinality(String),
    tsSec            Int64,
    ts               DateTime('UTC') MATERIALIZED toDateTime(tsSec, 'UTC'),
    docs             UInt32,
    levels           UInt32,
    snapshots        UInt16,
    seqGaps          UInt16,
    recvToPubP50Us   Nullable(Int64),
    recvToPubP99Us   Nullable(Int64),
    recvToPubMaxUs   Nullable(Int64),
    exchToRecvP50Us  Nullable(Int64),
    exchToRecvP99Us  Nullable(Int64)
)
ENGINE = MergeTree
ORDER BY (venue, product, tsSec);

-- End-of-run latency report summaries parsed from reports*/latency-*.txt
-- (import_latency.ps1). One row per run x segment. Values in microseconds,
-- signed — the exch segment includes cross-clock skew.
CREATE TABLE IF NOT EXISTS hft.latency_reports
(
    label    LowCardinality(String),            -- reports dir label (default/arb/arb-bt/okx/...)
    reportTs DateTime64(6, 'UTC'),              -- timestamp in the report header
    segment  LowCardinality(String),            -- e.g. 'pub->consume (cross-process)'
    n        UInt64,
    minUs    Float64,
    p50Us    Float64,
    p99Us    Float64,
    p999Us   Float64,
    maxUs    Float64
)
ENGINE = ReplacingMergeTree
ORDER BY (label, reportTs, segment);

-- ---------------------------------------------------------------------------
-- Derived views (what Grafana queries). Timestamps: sim fills are clocked on
-- md-stream recvTs, which is comparable between live and backtest runs and
-- lines up with md_top.ts. Orders' tsEpochNanos is decision wall-clock — in
-- backtests that is replay-run time, hours away from stream time — so every
-- time join below anchors on the FILL timestamp, never the order's.
-- ---------------------------------------------------------------------------

-- Per-fill cash/position deltas as plain Float64.
CREATE OR REPLACE VIEW hft.v_fills AS
SELECT
    runId, mode, venue, product, ts, fillId, orderId, side, partial,
    toFloat64(filledQty)                                        AS qty,
    toFloat64(avgPrice)                                         AS px,
    toFloat64(fee)                                              AS feeUsd,
    if(side = 'BUY', 1, -1) * toFloat64(filledQty)              AS signedQty,
    -if(side = 'BUY', 1, -1) * toFloat64(filledQty) * toFloat64(avgPrice)
        - toFloat64(fee)                                        AS dCash,
    posAfter, realizedAfter
FROM hft.sim_fills;

-- Run-level equity curve, one point per fill. Equity marks each product at
-- its own latest fill price (cash + pos*px); cross-product totals come from
-- cumulating per-product equity deltas over the whole run — correct even
-- when products trade at interleaved times.
CREATE OR REPLACE VIEW hft.v_equity_curve AS
SELECT
    runId, mode, venue, product, ts, fillId, side, qty, px,
    sum(dEquity) OVER (PARTITION BY runId ORDER BY ts, fillId
                       ROWS UNBOUNDED PRECEDING)                 AS runPnlUsd,
    sum(feeUsd)  OVER (PARTITION BY runId ORDER BY ts, fillId
                       ROWS UNBOUNDED PRECEDING)                 AS runFeesUsd
FROM
(
    SELECT
        *,
        posCum * px + cashCum
            - lagInFrame(posCum * px + cashCum, 1, 0.0)
              OVER (PARTITION BY runId, venue, product ORDER BY ts, fillId
                    ROWS UNBOUNDED PRECEDING)                    AS dEquity
    FROM
    (
        SELECT
            runId, mode, venue, product, ts, fillId, side, qty, px, feeUsd,
            sum(signedQty) OVER (PARTITION BY runId, venue, product
                                 ORDER BY ts, fillId
                                 ROWS UNBOUNDED PRECEDING)       AS posCum,
            sum(dCash)     OVER (PARTITION BY runId, venue, product
                                 ORDER BY ts, fillId
                                 ROWS UNBOUNDED PRECEDING)       AS cashCum
        FROM hft.v_fills
    )
);

-- Per-fill slippage vs the mid at fill (stream) time: side-adjusted, in bps.
-- Positive = paid worse than mid (half-spread + latency drift + book walk).
CREATE OR REPLACE VIEW hft.v_slippage AS
SELECT
    f.runId AS runId, f.mode AS mode, f.venue AS venue, f.product AS product,
    f.ts AS ts, f.fillId AS fillId, f.orderId AS orderId,
    f.side AS side, f.qty AS qty, f.px AS px,
    m.mid AS mid,
    if(f.side = 'BUY', f.px - m.mid, m.mid - f.px) / m.mid * 1e4 AS slipBps,
    (toUnixTimestamp64Nano(f.ts) - toUnixTimestamp64Nano(m.ts)) / 1e6 AS midAgeMs
FROM hft.v_fills AS f
ASOF INNER JOIN hft.md_top AS m
    ON m.venue = f.venue AND m.product = f.product AND m.ts <= f.ts;
