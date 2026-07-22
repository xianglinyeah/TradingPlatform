import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useLocation, useSearchParams } from 'react-router-dom';
import { useCurrentSymbol } from '../App';
import { api } from '../api/client';
import KLineChart from '../components/KLineChart';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import StatCard from '../components/StatCard';

const TODAY = new Date().toISOString().slice(0, 10);
const THREE_YEARS_AGO = (() => {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 3);
  return d.toISOString().slice(0, 10);
})();

// Market view: K-line + fundamentals for the selected symbol.
// Reads `symbol` and `t` (focus timestamp) from the URL search params
// so the trade->chart link from BacktestResults can deep-link in.
export default function MarketView() {
  const { symbol: ctxSymbol } = useCurrentSymbol();
  const [search] = useSearchParams();
  const symbol = search.get('symbol') ?? ctxSymbol;
  const focusTime = search.get('t') ? Number(search.get('t')) : undefined;

  const [interval, setInterval] = useState<'1m' | '1d'>('1d');
  const [startDate, setStartDate] = useState(THREE_YEARS_AGO);
  const [endDate, setEndDate] = useState(TODAY);

  // We read location just to re-trigger queries when the user navigates
  // here from another page with new params - keeps the UX predictable.
  const location = useLocation();

  const kline = useQuery({
    queryKey: ['kline', symbol, startDate, endDate, interval, location.key],
    queryFn: () => api.getKline({ symbol, start_date: startDate, end_date: endDate, interval }),
    enabled: Boolean(symbol),
  });

  const fundamentals = useQuery({
    queryKey: ['fundamentals', symbol, startDate, endDate],
    queryFn: () => api.getFundamentals({ symbol, start_date: startDate, end_date: endDate }),
    enabled: Boolean(symbol),
  });

  // Latest fundamentals snapshot for the stat cards.
  const latest = fundamentals.data?.data[fundamentals.data.data.length - 1];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xl">{symbol}</h2>
        <div className="flex items-center gap-2 text-sm">
          <label className="text-text-muted">From</label>
          <input
            type="date"
            value={startDate}
            onChange={e => setStartDate(e.target.value)}
            style={{ maxWidth: '10rem' }}
          />
          <label className="text-text-muted">To</label>
          <input
            type="date"
            value={endDate}
            onChange={e => setEndDate(e.target.value)}
            style={{ maxWidth: '10rem' }}
          />
          <select
            value={interval}
            onChange={e => setInterval(e.target.value as '1m' | '1d')}
            style={{ maxWidth: '6rem' }}
          >
            <option value="1d">Daily</option>
            <option value="1m">1 min</option>
          </select>
        </div>
      </div>

      <div className="panel">
        {kline.isLoading ? (
          <div className="h-[420px] flex items-center justify-center text-text-muted">
            Loading bars...
          </div>
        ) : kline.isError ? (
          <div className="h-[420px] flex items-center justify-center text-down">
            Failed to load bars. Check the symbol and that data has been ingested.
          </div>
        ) : (kline.data?.bars.length ?? 0) === 0 ? (
          <div className="h-[420px] flex items-center justify-center text-text-muted">
            No bars in the selected range.
          </div>
        ) : (
          <KLineChart bars={kline.data!.bars} focusTime={focusTime} />
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="PE TTM" value={latest?.pe_ttm ?? null} />
        <StatCard label="PB (LYR)" value={latest?.pb_lyr ?? null} />
        <StatCard label="Div Yield" value={latest?.dv_ttm ?? null} />
        <StatCard label="Turnover" value={latest?.turnover_rate ?? null} />
      </div>

      <div className="panel">
        <h3 className="text-sm text-text-muted mb-2">Fundamentals History</h3>
        {fundamentals.isLoading ? (
          <div className="h-[260px] flex items-center justify-center text-text-muted">Loading...</div>
        ) : (fundamentals.data?.data.length ?? 0) === 0 ? (
          <div className="h-[260px] flex items-center justify-center text-text-muted">
            No fundamentals data for this range.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={fundamentals.data!.data}>
              <CartesianGrid stroke="#2a3554" strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fill: '#8a96b3', fontSize: 11 }} minTickGap={48} />
              <YAxis tick={{ fill: '#8a96b3', fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#121a2b',
                  border: '1px solid #2a3554',
                  color: '#e6ecf7',
                }}
              />
              <Line type="monotone" dataKey="pe_ttm" stroke="#3b82f6" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="pb_lyr" stroke="#a855f7" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
