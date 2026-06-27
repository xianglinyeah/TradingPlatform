import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useCurrentSymbol } from '../App';
import ParamForm from '../components/ParamForm';
import type { BacktestStatus } from '../types';

// BacktestControl: the spec's "core interaction page".
// Left: strategy picker + schema-driven param form + date range.
// Right: live status (polls every 2s while running) + log tail.
//
// The form is reset whenever the user picks a different strategy,
// because each strategy has a different param schema. Defaults are
// seeded from the strategy's PARAMS_SCHEMA so the user can run with
// zero clicks if they want.
export default function BacktestControl() {
  const navigate = useNavigate();
  const { symbol } = useCurrentSymbol();

  const strategies = useQuery({
    queryKey: ['strategies'],
    queryFn: api.getStrategies,
  });

  const [strategyName, setStrategyName] = useState<string>('');
  const [params, setParams] = useState<Record<string, number | string | boolean>>({});
  const [symbols, setSymbols] = useState<string[]>([symbol]);
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2024-01-15');
  const [speed, setSpeed] = useState(10000);

  // Default-select the first strategy once loaded.
  useEffect(() => {
    if (!strategyName && strategies.data?.strategies.length) {
      setStrategyName(strategies.data.strategies[0].name);
    }
  }, [strategies.data, strategyName]);

  // When strategy changes, re-seed params from defaults.
  useEffect(() => {
    if (!strategyName) return;
    const s = strategies.data?.strategies.find(x => x.name === strategyName);
    if (!s) return;
    const next: Record<string, number | string | boolean> = {};
    for (const p of s.params_schema) {
      next[p.key] = (p.default ?? p.min ?? 0) as number | string | boolean;
    }
    setParams(next);
  }, [strategyName, strategies.data]);

  const currentSchema = useMemo(
    () => strategies.data?.strategies.find(s => s.name === strategyName)?.params_schema ?? [],
    [strategies.data, strategyName],
  );

  const runMutation = useMutation({
    mutationFn: api.runBacktest,
    onSuccess: resp => {
      setActiveRunId(resp.run_id);
    },
  });

  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  // Poll status while a run is active. Stops polling once we hit a
  // terminal status so we don't keep hitting the API forever.
  const status = useQuery<BacktestStatus>({
    queryKey: ['backtest-status', activeRunId],
    queryFn: () => api.getBacktestStatus(activeRunId!),
    enabled: Boolean(activeRunId),
    refetchInterval: q => {
      const s = q.state.data?.status;
      if (s && ['completed', 'error', 'stopped', 'failed'].includes(s)) return false;
      return 2000;
    },
  });

  const handleSubmit = () => {
    if (!strategyName) return;
    runMutation.mutate({
      start_date: startDate,
      end_date: endDate,
      symbols,
      speed,
      strategy_name: strategyName,
      strategy_params: params,
    });
  };

  const handleStop = async () => {
    if (activeRunId) await api.stopBacktest(activeRunId);
  };

  const handleViewResults = () => {
    if (activeRunId) navigate(`/backtest/result/${activeRunId}`);
  };

  const isRunning = status.data?.status === 'running';

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* LEFT: parameter configuration */}
      <div className="panel flex flex-col gap-4">
        <h2 className="text-xl">Backtest Configuration</h2>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-text-muted">Strategy</span>
          <select
            value={strategyName}
            onChange={e => setStrategyName(e.target.value)}
            disabled={strategies.isLoading}
          >
            {strategies.isLoading ? (
              <option>Loading...</option>
            ) : (
              strategies.data?.strategies.map(s => (
                <option key={s.name} value={s.name}>
                  {s.display_name || s.name}
                </option>
              ))
            )}
          </select>
        </label>

        <fieldset className="border border-edge rounded p-3">
          <legend className="text-xs uppercase tracking-wider text-text-muted px-1">
            Parameters
          </legend>
          <ParamForm schema={currentSchema} values={params} onChange={setParams} disabled={isRunning} />
        </fieldset>

        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-sm text-text-muted">Start date</span>
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-sm text-text-muted">End date</span>
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} />
          </label>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-text-muted">Symbols (one per line)</span>
          <textarea
            rows={3}
            value={symbols.join('\n')}
            onChange={e => setSymbols(e.target.value.split('\n').map(s => s.trim()).filter(Boolean))}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-text-muted">
            Speed multiplier: <span className="font-mono">{speed}x</span>
          </span>
          <input
            type="range"
            min={1}
            max={10000}
            step={1}
            value={speed}
            onChange={e => setSpeed(Number(e.target.value))}
          />
        </label>

        <div className="flex gap-2">
          <button
            className="btn-primary"
            onClick={handleSubmit}
            disabled={isRunning || runMutation.isPending || !strategyName}
          >
            {runMutation.isPending ? 'Submitting...' : 'Run backtest'}
          </button>
          {isRunning && (
            <button className="btn-danger" onClick={handleStop}>
              Stop
            </button>
          )}
        </div>

        {runMutation.isError && (
          <p className="text-down text-sm">
            Failed to start: {(runMutation.error as Error).message}
          </p>
        )}
      </div>

      {/* RIGHT: live status */}
      <div className="panel flex flex-col gap-3">
        <h2 className="text-xl">Status</h2>
        {!activeRunId ? (
          <p className="text-text-muted">No active run. Configure and submit to begin.</p>
        ) : (
          <>
            <StatusBadge status={status.data?.status ?? 'unknown'} />
            <Row label="Run ID" value={<code className="text-sm">{activeRunId}</code>} />
            <Row
              label="Progress"
              value={status.data?.progress ? <span className="tabular">{status.data.progress}</span> : '—'}
            />
            <Row
              label="Bars sent"
              value={status.data?.bars_sent != null ? <span className="tabular">{status.data.bars_sent}</span> : '—'}
            />
            {status.data?.status === 'completed' && (
              <button className="btn-primary self-start" onClick={handleViewResults}>
                View results →
              </button>
            )}
            {status.data?.status === 'error' && (
              <p className="text-down text-sm">Replay reported an error. See server logs.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    running: 'bg-accent text-white',
    completed: 'bg-up text-white',
    error: 'bg-down text-white',
    failed: 'bg-down text-white',
    stopped: 'bg-bg-muted text-text',
    pending: 'bg-bg-muted text-text',
    idle: 'bg-bg-muted text-text',
    unknown: 'bg-bg-muted text-text-muted',
  };
  const cls = map[status] ?? 'bg-bg-muted';
  return (
    <span className={`text-xs uppercase px-2 py-0.5 rounded ${cls}`}>{status}</span>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-text-muted">{label}</span>
      <span>{value}</span>
    </div>
  );
}
