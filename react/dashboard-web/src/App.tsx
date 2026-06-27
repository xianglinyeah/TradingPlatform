import { createContext, useContext, useMemo, useState } from 'react';
import { NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import MarketView from './pages/MarketView';
import BacktestControl from './pages/BacktestControl';
import BacktestResults from './pages/BacktestResults';
import BacktestHistory from './pages/BacktestHistory';

// The "current viewed symbol" is shared across pages. Bloomberg-style:
// when you click a trade in the results page, you jump to MarketView with
// that symbol + timestamp pre-loaded, and the symbol stays selected if
// you then navigate to BacktestControl.
interface SymbolCtx {
  symbol: string;
  setSymbol: (s: string) => void;
}
const Ctx = createContext<SymbolCtx>({ symbol: '000001.SZ', setSymbol: () => {} });
export const useCurrentSymbol = () => useContext(Ctx);

const NAV_ITEMS = [
  { to: '/market', label: 'Market' },
  { to: '/backtest', label: 'Backtest' },
  { to: '/history', label: 'History' },
  { to: '/compare', label: 'Compare' },
];

export default function App() {
  const [symbol, setSymbol] = useState('000001.SZ');
  const value = useMemo(() => ({ symbol, setSymbol }), [symbol]);
  const navigate = useNavigate();

  return (
    <Ctx.Provider value={value}>
      <div className="min-h-screen flex flex-col">
        <header className="border-b border-edge bg-bg-panel">
          <div className="flex items-center gap-4 px-4 py-2">
            <span className="font-mono text-sm text-text-muted">TP</span>
            <nav className="flex gap-1">
              {NAV_ITEMS.map(item => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `px-3 py-1.5 rounded text-sm transition-colors ${
                      isActive
                        ? 'bg-accent text-white'
                        : 'text-text-muted hover:text-text hover:bg-bg-muted'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="ml-auto flex items-center gap-2">
              <SymbolSearch
                value={symbol}
                onChange={s => {
                  setSymbol(s);
                  if (window.location.pathname !== '/market') navigate('/market');
                }}
              />
            </div>
          </div>
        </header>

        <main className="flex-1 p-4">
          <Routes>
            <Route path="/" element={<MarketView />} />
            <Route path="/market" element={<MarketView />} />
            <Route path="/backtest" element={<BacktestControl />} />
            <Route path="/backtest/result/:run_id" element={<BacktestResults />} />
            <Route path="/history" element={<BacktestHistory />} />
            <Route path="/compare" element={<BacktestHistory compareMode />} />
          </Routes>
        </main>
      </div>
    </Ctx.Provider>
  );
}

import { useQuery } from '@tanstack/react-query';
import { api } from './api/client';

function SymbolSearch({ value, onChange }: { value: string; onChange: (s: string) => void }) {
  const [q, setQ] = useState(value);
  const { data, isFetching } = useQuery({
    queryKey: ['symbols', q],
    queryFn: () => api.getSymbols(q || undefined, 20),
    placeholderData: (prev) => prev,
  });

  return (
    <div className="flex items-center gap-2">
      <input
        className="w-48 text-sm"
        list="symbol-list"
        value={q}
        placeholder="symbol search"
        onChange={e => setQ(e.target.value)}
        onBlur={() => {
          if (q.trim()) onChange(q.trim().toUpperCase());
        }}
        onKeyDown={e => {
          if (e.key === 'Enter' && q.trim()) {
            onChange(q.trim().toUpperCase());
            (e.target as HTMLInputElement).blur();
          }
        }}
      />
      {isFetching ? (
        <span className="text-xs text-text-muted">...</span>
      ) : null}
      <datalist id="symbol-list">
        {(data?.symbols ?? []).map(s => (
          <option key={s.symbol} value={s.symbol}>
            {s.name ?? ''}
          </option>
        ))}
      </datalist>
    </div>
  );
}
