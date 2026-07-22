interface Props {
  label: string;
  value: string | number | null;
  // Optional colour hint - up/down for PnL-style stats.
  tone?: 'up' | 'down' | 'neutral';
}

// Compact metric tile used in the results summary grid.
export default function StatCard({ label, value, tone = 'neutral' }: Props) {
  const color =
    tone === 'up' ? 'text-up' : tone === 'down' ? 'text-down' : 'text-text';
  return (
    <div className="stat-card">
      <span className="label">{label}</span>
      <span className={`value ${color}`}>
        {value === null || value === undefined ? '—' : value}
      </span>
    </div>
  );
}
