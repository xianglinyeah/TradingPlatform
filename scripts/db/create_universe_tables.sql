-- Migration: Create centralized universe management schema
-- Purpose: Single source of truth for stock universe membership across all
--          services (data-ingestion, strategy-engine, market-data-replay,
--          Dashboard.Service, market-data-gm). Point-in-time aware to
--          prevent survivorship bias in backtests.
-- Date: 2026-06-27

CREATE SCHEMA IF NOT EXISTS market_ref;

-- Universe definitions (metadata)
CREATE TABLE IF NOT EXISTS market_ref.universe_definition (
    universe_id   VARCHAR(50) PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    source_index  VARCHAR(20),                -- GM index code, e.g. 'SHSE.000300'; NULL for composite
    description   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Universe membership with time validity (point-in-time correct)
CREATE TABLE IF NOT EXISTS market_ref.universe_member (
    universe_id    VARCHAR(50) NOT NULL REFERENCES market_ref.universe_definition(universe_id),
    symbol         VARCHAR(20) NOT NULL,      -- TS format: '600000.SH'
    effective_from DATE NOT NULL,
    effective_to   DATE,                      -- NULL = currently active
    PRIMARY KEY (universe_id, symbol, effective_from)
);

CREATE INDEX IF NOT EXISTS idx_universe_member_symbol
    ON market_ref.universe_member(symbol);
CREATE INDEX IF NOT EXISTS idx_universe_member_lookup
    ON market_ref.universe_member(universe_id, effective_from, effective_to);

-- Seed universe definitions (idempotent)
INSERT INTO market_ref.universe_definition (universe_id, name, source_index, description) VALUES
  ('csi300',  'CSI 300',     'SHSE.000300', 'CSI 300 large-cap index'),
  ('sse50',   'SSE 50',      'SHSE.000016', 'SSE 50 blue-chip index'),
  ('csi500',  'CSI 500',     'SHSE.000905', 'CSI 500 mid-cap index'),
  ('csi1000', 'CSI 1000',    'SHSE.000852', 'CSI 1000 small-cap index'),
  ('a_all',   'All A-shares', NULL,           'Composite: SHSE.000001 (SSE composite) + SZSE.399106 (SZSE composite)')
ON CONFLICT (universe_id) DO NOTHING;

-- Verification
SELECT 'universe_definition' AS table_name, COUNT(*) AS row_count
FROM market_ref.universe_definition
UNION ALL
SELECT 'universe_member' AS table_name, COUNT(*) AS row_count
FROM market_ref.universe_member;
