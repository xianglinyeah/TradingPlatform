import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table';
import { api } from '../api/client';
import PnlCurve from '../components/PnlCurve';
import type { RunRecord } from '../types';

interface Props {
  // When true, the page renders the multi-run comparison view at the top
  // and treats the history list as a "pick runs to compare" picker.
  compareMode?: boolean;
}

// History / Compare page:
//  - default mode: list past runs with click-through to results
//  - compare mode: checkbox selection + side-by-side PnL curves
export default function BacktestHistory({ compareMode = false }: Props) {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const runs = useQuery({
    queryKey: ['runs'],
    queryFn: () => api.listRuns(100, 0),
  });

  // Fetch comparison data only in compare mode and only for selected runs.
  const comparison = useQuery({
    queryKey: ['compare', Array.from(selected).sort()],
    queryFn: () => api.compare(Array.from(selected)),
    enabled: compareMode && selected.size >= 2,
  });

  const columns = useMemoColumns(() =>
    compareMode
      ? [
          {
            id: 'select',
            header: '',
            cell: ({ row }: any) => (
              <input
                type="checkbox"
                checked={selected.has(row.original.run_id)}
                onChange={e => {
                  const next = new Set(selected);
                  if (e.target.checked) next.add(row.original.run_id);
                  else next.delete(row.original.run_id);
                  setSelected(next);
                }}
              />
            ),
          },
          ...baseColumns,
        ]
      : baseColumns,
    [compareMode, selected],
  );

  const table = useReactTable({
    data: runs.data?.runs ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-xl">
        {compareMode ? 'Compare Runs' : 'Run History'}
      </h2>

      <div className="panel">
        {runs.isLoading ? (
          <div className="text-text-muted">Loading...</div>
        ) : (runs.data?.runs.length ?? 0) === 0 ? (
          <div className="text-text-muted">No runs yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                {table.getHeaderGroups().map(hg => (
                  <tr key={hg.id} className="border-b border-edge">
                    {hg.headers.map(h => (
                      <th key={h.id} className="text-left py-2 px-2 text-text-muted font-medium">
                        {flexRender(h.column.columnDef.header, h.getContext())}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map(row => (
                  <tr
                    key={row.id}
                    className={`border-b border-edge/50 hover:bg-bg-muted ${
                      compareMode ? 'cursor-default' : 'cursor-pointer'
                    }`}
                    onClick={() => {
                      if (!compareMode) navigate(`/backtest/result/${row.original.run_id}`);
                    }}
                  >
                    {row.getVisibleCells().map(cell => (
                      <td key={cell.id} className="py-2 px-2">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {compareMode && (
        <div className="panel">
          <h3 className="text-sm text-text-muted mb-2">
            Comparison {selected.size >= 2 ? `(${selected.size} runs)` : '(select at least 2)'}
          </h3>
          {selected.size < 2 ? (
            <div className="h-[200px] flex items-center justify-center text-text-muted">
              Tick two or more runs above to compare.
            </div>
          ) : comparison.isLoading ? (
            <div className="h-[200px] flex items-center justify-center text-text-muted">
              Loading...
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="border border-edge rounded p-2 bg-bg">
                {comparison.data?.runs.map((r, i) => {
                  // Use a stable palette across re-renders so each run keeps its colour.
                  const palette = ['#3b82f6', '#16c784', '#f59e0b', '#a855f7', '#ec4899'];
                  const color = palette[i % palette.length];
                  return (
                    <div key={r.run_id} className="mb-2">
                      <div className="text-xs text-text-muted mb-1">
                        <span style={{ color }}>●</span>{' '}
                        <code>{r.run_id.slice(0, 12)}</code> — PnL{' '}
                        <span className={r.summary.total_pnl >= 0 ? 'text-up' : 'text-down'}>
                          {r.summary.total_pnl.toFixed(2)}
                        </span>
                      </div>
                      <PnlCurve data={r.pnl_curve} height={200} label={r.run_id} color={color} />
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {!compareMode && (
        <Link to="/compare" className="btn self-start text-sm">
          Open compare view →
        </Link>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Column definitions - kept out of the component body so the table doesn't
// re-create them on every render.
// ---------------------------------------------------------------------------

const COLORS = { up: 'text-up', down: 'text-down', muted: 'text-text-muted' };

const baseColumns: ColumnDef<RunRecord>[] = [
  {
    header: 'Created',
    accessorKey: 'created_at',
    cell: info => (
      <span className="tabular text-text-muted">
        {new Date(info.getValue<string>()).toLocaleString()}
      </span>
    ),
  },
  { header: 'Strategy', accessorKey: 'strategy_name' },
  {
    header: 'Params',
    accessorKey: 'strategy_params',
    cell: info => {
      const params = info.getValue<Record<string, unknown>>();
      const str = Object.entries(params)
        .map(([k, v]) => `${k}=${String(v)}`)
        .join(', ');
      return <span className="text-text-muted text-xs">{str}</span>;
    },
  },
  { header: 'Symbols', accessorKey: 'symbols',
    cell: info => (
      <span className="text-text-muted text-xs">
        {(info.getValue<string[]>() ?? []).join(', ')}
      </span>
    ),
  },
  {
    header: 'Range',
    id: 'range',
    cell: ({ row }) => (
      <span className="tabular text-text-muted text-xs">
        {row.original.start_date ?? '—'} → {row.original.end_date ?? '—'}
      </span>
    ),
  },
  {
    header: 'Status',
    accessorKey: 'status',
    cell: info => {
      const s = info.getValue<string>();
      const cls = s === 'completed' ? COLORS.up : s === 'error' || s === 'failed' ? COLORS.down : COLORS.muted;
      return <span className={`text-xs uppercase ${cls}`}>{s}</span>;
    },
  },
  {
    header: 'PnL',
    accessorKey: 'total_pnl',
    cell: info => {
      const v = info.getValue<number | null>();
      if (v === null || v === undefined) return <span className="text-text-muted">—</span>;
      return (
        <span className={`tabular ${v >= 0 ? 'text-up' : 'text-down'}`}>
          {v.toFixed(2)}
        </span>
      );
    },
  },
];

// tiny hook to memoize columns without re-renders
import { useMemo } from 'react';
function useMemoColumns<T>(factory: () => T, deps: unknown[]): T {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(factory, deps);
}
