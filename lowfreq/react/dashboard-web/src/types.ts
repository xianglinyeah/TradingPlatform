// Shared TypeScript types matching Dashboard.Service response shapes.
// Generated from dashboard_service.models; kept in sync manually to
// avoid adding an OpenAPI generator to the toolchain for v1.

export interface KlineBar {
  time: number; // unix seconds UTC
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface KlineResponse {
  symbol: string;
  interval: string;
  bars: KlineBar[];
}

export interface FundamentalPoint {
  date: string;
  pe_ttm: number | null;
  pb_lyr: number | null;
  dv_ttm: number | null;
  turnover_rate: number | null;
}

export interface FundamentalsResponse {
  symbol: string;
  data: FundamentalPoint[];
}

export interface SymbolHit {
  symbol: string;
  name: string | null;
}

export interface SymbolsResponse {
  symbols: SymbolHit[];
}

export interface UniverseInfo {
  universe_id: string;
  name: string;
  source_index: string | null;
  description: string | null;
}

export interface UniversesListResponse {
  universes: UniverseInfo[];
}

export interface UniverseMembersResponse {
  universe_id: string;
  count: number;
  symbols: string[];
}

export interface StrategyParamSchema {
  key: string;
  label: string;
  type: 'int' | 'float' | 'string' | 'bool';
  default?: number | string | boolean;
  min?: number;
  max?: number;
  step?: number;
}

export interface StrategyInfo {
  name: string;
  class_name: string;
  display_name: string;
  description: string;
  params_schema: StrategyParamSchema[];
}

export interface StrategiesResponse {
  strategies: StrategyInfo[];
}

export interface BacktestRunRequest {
  start_date: string;
  end_date: string;
  symbols?: string[];
  universe_id?: string;
  speed: number;
  strategy_name: string;
  strategy_params: Record<string, number | string | boolean>;
}

export interface BacktestRunResponse {
  run_id: string;
  status: string;
}

export interface BacktestStatus {
  status: string;
  progress: string | null;
  bars_sent: number | null;
  run_id: string;
}

export interface BacktestSummary {
  total_pnl: number;
  win_rate: number;
  total_trades: number;
  max_drawdown: number;
  sharpe_ratio: number | null;
}

export interface PnlCurvePoint {
  timestamp: string;
  cumulative_pnl: number;
}

export interface TradeRow {
  timestamp: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  status: string;
}

export interface BacktestResults {
  run_id: string;
  summary: BacktestSummary;
  pnl_curve: PnlCurvePoint[];
  trades: TradeRow[];
}

export interface RunRecord {
  run_id: string;
  strategy_name: string;
  strategy_params: Record<string, number | string | boolean>;
  symbols: string[];
  start_date: string | null;
  end_date: string | null;
  speed: number | null;
  status: string;
  total_pnl: number | null;
  created_at: string;
  error_message: string | null;
}

export interface RunsListResponse {
  runs: RunRecord[];
}

export interface CompareResponse {
  runs: BacktestResults[];
}
