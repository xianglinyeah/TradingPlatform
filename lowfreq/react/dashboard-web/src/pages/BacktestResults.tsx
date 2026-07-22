import { useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { useState } from 'react';
import { api } from '../api/client';
import StatCard from '../components/StatCard';
import PnlCurve from '../components/PnlCurve';
import type { TradeRow } from '../types';

// Results view: shown after a backtest completes, or when the user clicks
// into a historical run from the History page.
//
// "Click trade -> jump to chart": each trade row deep-links to /market
// with the symbol + timestamp encoded in the URL so MarketView can
// focus the K-line on that moment.
export default function BacktestResults() {
  const { run_id } = useParams<{ run_id: string }>();
  const navigate = useNavigate();
  const [sorting, setSorting] = useState<SortingState>([{ id: 'timestamp', desc: false }]);

  const results = useQuery({
    queryKey: ['results', run_id],
    queryFn: () => api.getResults(run_id!),
    enabled: Boolean(run_id),
  });

  const columns = useMemo<ColumnDef<TradeRow>[]>(
    () => [
      {
        header: 'Time',
        accessorKey: 'timestamp',
        cell: info => (
          <span className="tabular text-text-muted">
            {new Date(info.getValue<string>()).toLocaleString()}
          </span>
        ),
      },
      { header: 'Symbol', accessorKey: 'symbol' },
      {
        header: 'Side',
        accessorKey: 'side',
        cell: info => {
          const s = info.getValue<string>().toUpperCase();
          return (
            <span className={s === 'BUY' ? 'text-up' : 'text-down'}>{s}</span>
          );
        },
      },
      {
        header: 'Qty',
        accessorKey: 'quantity',
        cell: info => <span className="tabular">{Number(info.getValue()).toLocaleString()}</span>,
      },
      {
        header: 'Price',
        accessorKey: 'price',
        cell: info => <span className="tabular">{Number(info.getValue()).toFixed(2)}</span>,
      },
      { header: 'Status', accessorKey: 'status' },
    ],
    [],
  );

  const table = useReactTable({
    data: results.data?.trades ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (results.isLoading) {
    return <div className="text-text-muted">Loading results...</div>;
  }
  if (results.isError || !results.data) {
    return <div className="text-down">Failed to load results for {run_id}.</div>;
  }

  const s = results.data.summary;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl">
          Run <code className="text-sm">{run_id}</code>
        </h2>
        <Link to="/history" className="btn text-sm">
          ← Back to history
        </Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard
          label="Total PnL"
          value={s.total_pnl.toFixed(2)}
          tone={s.total_pnl >= 0 ? 'up' : 'down'}
        />
        <StatCard label="Win Rate" value={`${(s.win_rate * 100).toFixed(1)}%`} />
        <StatCard label="Trades" value={s.total_trades} />
        <StatCard
          label="Max Drawdown"
          value={s.max_drawdown.toFixed(2)}
          tone={s.max_drawdown < 0 ? 'down' : 'neutral'}
        />
        <StatCard label="Sharpe" value={s.sharpe_ratio ?? null} />
      </div>

      <div className="panel">
        <h3 className="text-sm text-text-muted mb-2">PnL Curve</h3>
        {results.data.pnl_curve.length === 0 ? (
          <div className="h-[280px] flex items-center justify-center text-text-muted">
            No fills recorded. The strategy may not have generated any trades.
          </div>
        ) : (
          <PnlCurve data={results.data.pnl_curve} />
        )}
      </div>

      <div className="panel">
        <h3 className="text-sm text-text-muted mb-2">Trade Detail</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              {table.getHeaderGroups().map(hg => (
                <tr key={hg.id} className="border-b border-edge">
                  {hg.headers.map(h => (
                    <th
                      key={h.id}
                      className="text-left py-2 px-2 text-text-muted font-medium cursor-pointer select-none"
                      onClick={h.column.getToggleSortingHandler()}
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getIsSorted() === 'asc' ? ' ▲' : h.column.getIsSorted() === 'desc' ? ' ▼' : ''}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="py-6 text-center text-text-muted">
                    No trade rows
                  </td>
                </tr>
              ) : (
                table.getRowModel().rows.map(row => {
                  const trade = row.original;
                  const ts = new Date(trade.timestamp).getTime() / 1000;
                  return (
                    <tr
                      key={row.id}
                      className="border-b border-edge/50 hover:bg-bg-muted cursor-pointer"
                      onClick={() =>
                        navigate(
                          `/market?symbol=${encodeURIComponent(trade.symbol)}&t=${ts}`,
                        )
                      }
                    >
                      {row.getVisibleCells().map(cell => (
                        <td key={cell.id} className="py-2 px-2">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
