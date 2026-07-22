import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  IChartApi,
  ISeriesApi,
  CrosshairMode,
  LineStyle,
} from 'lightweight-charts';
import type { KlineBar } from '../types';

interface Props {
  bars: KlineBar[];
  height?: number;
  // Optional EMA overlay, e.g. from the strategy params we want to
  // visualise. Pre-computed server-side in v1; client-side later.
  overlays?: { name: string; color: string; data: { time: number; value: number }[] }[];
  // When set, scrolls the chart to this unix-timestamp on next render.
  // Used by the "click trade -> jump to chart" interaction.
  focusTime?: number;
}

// Candlestick chart built on TradingView Lightweight Charts.
// We keep one IChartApi per mounted component and feed data via
// series.setData (full replace) rather than update (incremental) -
// our data volumes are bounded by the user's date range.
export default function KLineChart({ bars, height = 420, overlays = [], focusTime }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const overlayRefs = useRef<Map<string, ISeriesApi<'Line'>>>(new Map());

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8a96b3',
      },
      grid: {
        vertLines: { color: 'rgba(42,53,84,0.5)' },
        horzLines: { color: 'rgba(42,53,84,0.5)' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a3554' },
      timeScale: { borderColor: '#2a3554', timeVisible: true, secondsVisible: false },
    });
    const candle = chart.addCandlestickSeries({
      upColor: '#16c784',
      downColor: '#ea3943',
      borderUpColor: '#16c784',
      borderDownColor: '#ea3943',
      wickUpColor: '#16c784',
      wickDownColor: '#ea3943',
    });
    chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    }).priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });

    chartRef.current = chart;
    candleRef.current = candle;

    // Resize observer keeps the chart filling its container.
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        chart.applyOptions({ width: e.contentRect.width });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      overlayRefs.current.clear();
    };
  }, [height]);

  // Feed bar data.
  useEffect(() => {
    if (!candleRef.current) return;
    candleRef.current.setData(
      bars.map(b => ({
        time: b.time as any,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  // Manage overlay series (create/destroy to match overlays prop).
  useEffect(() => {
    if (!chartRef.current) return;
    const seen = new Set<string>();
    for (const o of overlays) {
      seen.add(o.name);
      let s = overlayRefs.current.get(o.name);
      if (!s) {
        s = chartRef.current.addLineSeries({
          color: o.color,
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        overlayRefs.current.set(o.name, s);
      }
      s.setData(o.data.map(d => ({ time: d.time as any, value: d.value })));
    }
    // Remove overlays no longer present.
    for (const [name, s] of overlayRefs.current) {
      if (!seen.has(name)) {
        chartRef.current.removeSeries(s);
        overlayRefs.current.delete(name);
      }
    }
  }, [overlays]);

  // Focus timestamp - used by the trade->chart link.
  // lightweight-charts v4 uses setVisibleRange to scroll to a timestamp;
  // we centre a narrow window around the target so the chart doesn't
  // jump to "fit all content" mode.
  useEffect(() => {
    if (!focusTime || !chartRef.current) return;
    const ts = focusTime as any;
    const pad = 60 * 60; // ±1h window
    chartRef.current.timeScale().setVisibleRange({
      from: (ts - pad) as any,
      to: (ts + pad) as any,
    });
  }, [focusTime]);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}
