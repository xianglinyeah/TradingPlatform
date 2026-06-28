-- sec_master table: instrument classification source for execution-service.
--
-- Populated by data-ingestion's sec_master_sync mode (calls the GM SDK's
-- get_symbol_infos). execution-service reads this to pick the right
-- IMarketRule (T+1 stock vs T+0 convertible bond vs ETF rules) and to
-- compute board-aware price-limit bands (§4) for the SimExecutionAdapter.
--
-- Idempotent: safe to run on every migration. Lives in market_ref (the
-- existing reference-data schema already used by universe_*).

CREATE SCHEMA IF NOT EXISTS market_ref;

CREATE TABLE IF NOT EXISTS market_ref.sec_master (
    -- TS-style symbol (e.g. '600000.SH'); primary key because execution-service
    -- always looks up by this form.
    symbol          VARCHAR(20) PRIMARY KEY,
    -- Original GM-format code ('SHSE.600000'); kept for round-trip back to the SDK.
    gm_symbol       VARCHAR(30) NOT NULL,
    -- Normalized instrument class used by execution-service's MarketRuleFactory:
    -- 'stock', 'convertible_bond', 'etf', 'reit', 'bond', 'fund'.
    sec_type        VARCHAR(30) NOT NULL,
    -- Raw GM SDK sec_type1 integer (e.g. 1010, 1030, 1090) for diagnostics.
    sec_type_code   INTEGER,
    -- Trading board. NULL for instruments where the concept does not apply
    -- (e.g. convertible bonds). Values: 'main' | 'chinext' | 'star' | 'beijing'.
    board           VARCHAR(20),
    -- Human-readable security name (used for ST detection via 'ST'/'*ST' prefix).
    name            VARCHAR(100),
    -- True if the security is currently designated ST/*ST (price-limit ±5%).
    is_st           BOOLEAN NOT NULL DEFAULT FALSE,
    -- Listing exchange: 'SHSE' | 'SZSE' | 'BSE'.
    exchange        VARCHAR(10),
    -- UTC timestamp of the ingestion that last touched this row.
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sec_master_sec_type
    ON market_ref.sec_master(sec_type);

CREATE INDEX IF NOT EXISTS idx_sec_master_board
    ON market_ref.sec_master(board)
    WHERE board IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sec_master_is_st
    ON market_ref.sec_master(is_st)
    WHERE is_st = TRUE;
