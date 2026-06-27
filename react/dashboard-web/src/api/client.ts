// Centralised HTTP client + typed query helpers.
//
// All back-end calls go through here so the URL conventions and error
// handling are uniform. The base URL is empty in production (same-origin)
// and proxied to Dashboard.Service in dev via vite.config.ts.

import axios, { AxiosInstance } from 'axios';
import type {
  BacktestRunRequest,
  BacktestRunResponse,
  BacktestStatus,
  BacktestResults,
  CompareResponse,
  FundamentalsResponse,
  KlineResponse,
  RunsListResponse,
  StrategiesResponse,
  SymbolsResponse,
} from '../types';

const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30_000,
});

export const api = {
  // --- data queries ---
  getKline: (params: {
    symbol: string;
    start_date: string;
    end_date: string;
    interval: '1m' | '1d';
  }) => client.get<KlineResponse>('/kline/' + encodeURIComponent(params.symbol), {
    params: { start_date: params.start_date, end_date: params.end_date, interval: params.interval },
  }).then(r => r.data),

  getFundamentals: (params: {
    symbol: string;
    start_date: string;
    end_date: string;
  }) => client.get<FundamentalsResponse>('/fundamentals/' + encodeURIComponent(params.symbol), {
    params,
  }).then(r => r.data),

  getSymbols: (search?: string, limit = 50) =>
    client.get<SymbolsResponse>('/symbols', { params: { search, limit } }).then(r => r.data),

  // --- strategy metadata ---
  getStrategies: () => client.get<StrategiesResponse>('/strategies').then(r => r.data),

  // --- backtest orchestration ---
  runBacktest: (req: BacktestRunRequest) =>
    client.post<BacktestRunResponse>('/backtest/run', req).then(r => r.data),

  getBacktestStatus: (run_id: string) =>
    client.get<BacktestStatus>(`/backtest/${encodeURIComponent(run_id)}/status`).then(r => r.data),

  stopBacktest: (run_id: string) =>
    client.post<{ stopped: boolean }>(`/backtest/${encodeURIComponent(run_id)}/stop`).then(r => r.data),

  listRuns: (limit = 50, offset = 0) =>
    client.get<RunsListResponse>('/backtest/runs', { params: { limit, offset } }).then(r => r.data),

  getResults: (run_id: string) =>
    client.get<BacktestResults>(`/backtest/${encodeURIComponent(run_id)}/results`).then(r => r.data),

  compare: (run_ids: string[]) =>
    client.get<CompareResponse>('/backtest/compare', {
      params: { run_ids: run_ids.join(',') },
    }).then(r => r.data),
};
