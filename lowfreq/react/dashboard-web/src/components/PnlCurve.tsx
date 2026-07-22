import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { PnlCurvePoint } from '../types';

interface Props {
  data: PnlCurvePoint[];
  height?: number;
  // Optional label shown in the legend/tooltip - used by the compare
  // page when multiple curves are drawn together.
  label?: string;
  color?: string;
}

// Recharts-based PnL curve. We deliberately use Recharts rather than
// lightweight-charts here (per spec section 3.2) - the PnL curve is a
// plain time-series, not a candlestick, and Recharts handles multi-series
// overlays cleanly for the compare page.
export default function PnlCurve({ data, height = 280, label = 'PnL', color = '#3b82f6' }: Props) {
  // Pre-format timestamps once rather than per-tick.
  const formatted = data.map(p => ({
    ...p,
    label: new Date(p.timestamp).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }),
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={formatted} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#2a3554" strokeDasharray="3 3" />
        <XAxis
          dataKey="label"
          tick={{ fill: '#8a96b3', fontSize: 11 }}
          minTickGap={48}
        />
        <YAxis
          tick={{ fill: '#8a96b3', fontSize: 11 }}
          tickFormatter={v => v.toFixed(0)}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#121a2b',
            border: '1px solid #2a3554',
            color: '#e6ecf7',
          }}
          formatter={(v: number) => [v.toFixed(2), label]}
        />
        <ReferenceLine y={0} stroke="#2a3554" />
        <Line
          type="monotone"
          dataKey="cumulative_pnl"
          stroke={color}
          dot={false}
          strokeWidth={2}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
