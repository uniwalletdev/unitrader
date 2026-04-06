"use client";

import { useEffect, useMemo, useRef } from "react";
import { ColorType, LineSeries, createChart, type IChartApi, type UTCTimestamp } from "lightweight-charts";

export type CumulativePnlTrade = {
  closed_at: string | null;
  profit: number | null;
  loss: number | null;
};

export default function CumulativePnlChart({
  trades,
  height = 176,
}: {
  trades: CumulativePnlTrade[];
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const points = useMemo(() => {
    const closed = trades
      .filter((t) => t.closed_at)
      .map((t) => ({
        ts: new Date(t.closed_at as string).getTime(),
        pnl: (t.profit ?? 0) - (t.loss ?? 0),
      }))
      .filter((x) => Number.isFinite(x.ts));
    closed.sort((a, b) => a.ts - b.ts);
    let cum = 0;
    const out: { time: UTCTimestamp; value: number }[] = [];
    for (const row of closed) {
      cum += row.pnl;
      let t = Math.floor(row.ts / 1000) as UTCTimestamp;
      if (out.length && t <= out[out.length - 1].time) {
        t = (out[out.length - 1].time + 1) as UTCTimestamp;
      }
      out.push({ time: t, value: cum });
    }
    return out;
  }, [trades]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || points.length === 0) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(el, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "rgba(148,163,184,0.9)",
      },
      grid: {
        vertLines: { color: "rgba(30,41,59,0.6)" },
        horzLines: { color: "rgba(30,41,59,0.6)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
    });
    chartRef.current = chart;

    const series = chart.addSeries(LineSeries, {
      color: "rgba(10,219,106,0.95)",
      lineWidth: 2,
    });
    series.setData(points);
    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(el);
    chart.applyOptions({ width: el.clientWidth });

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [height, points]);

  if (points.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-xl border border-dark-800 bg-dark-900/30 px-4 text-center text-sm text-dark-400"
        style={{ minHeight: height }}
      >
        No closed trades in this period yet — cumulative P&amp;L will appear once trades close.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="w-full rounded-xl border border-dark-800 bg-dark-900/30"
      style={{ height }}
    />
  );
}
