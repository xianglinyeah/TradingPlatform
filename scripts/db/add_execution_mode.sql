-- Migration: Add execution_mode field to orders and trades tables
-- Purpose: Separate simulation PnL from live trading PnL
-- Date: 2026-05-30

-- Add execution_mode to orders table
ALTER TABLE orders ADD COLUMN execution_mode VARCHAR(20) DEFAULT 'SIMULATION';
CREATE INDEX idx_orders_execution_mode ON orders(execution_mode);

-- Add execution_mode to trades table
ALTER TABLE trades ADD COLUMN execution_mode VARCHAR(20) DEFAULT 'SIMULATION';
CREATE INDEX idx_trades_execution_mode ON trades(execution_mode);

-- Update existing records to SIMULATION (for backwards compatibility)
UPDATE orders SET execution_mode = 'SIMULATION' WHERE execution_mode IS NULL;
UPDATE trades SET execution_mode = 'SIMULATION' WHERE execution_mode IS NULL;

-- Verify the migration
SELECT 'orders' as table_name, column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'orders' AND column_name = 'execution_mode'
UNION ALL
SELECT 'trades' as table_name, column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'trades' AND column_name = 'execution_mode';
