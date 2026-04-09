import { useEffect, useMemo, useRef, useState } from "react";
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  IChartApi,
  LineSeries,
  LineStyle,
  createChart,
} from "lightweight-charts";
import { api } from "@/lib/api";
import { useLivePrice } from "@/hooks/useLivePrice";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

type TradeSignal = "BUY" | "SELL" | "WAIT" | "NONE";

type OhlcvBar = {
  time: string; // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function sma(values: number[], period: number) {
  const out: Array<number | null> = Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

function std(values: number[], period: number) {
  const out: Array<number | null> = Array(values.length).fill(null);
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) continue;
    const slice = values.slice(i - period + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / period;
    const v =
      slice.reduce((a, b) => a + (b - mean) * (b - mean), 0) / period;
    out[i] = Math.sqrt(v);
  }
  return out;
}

function computeRSI(closes: number[], period = 14) {
  if (closes.length < period + 1) return null;
  let gains = 0;
  let losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff >= 0) gains += diff;
    else losses += Math.abs(diff);
  }
  const avgGain = gains / period;
  const avgLoss = losses / period;
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

export type TradeMarker = {
  type: "entry" | "exit";
  price: number;
  time: string; // YYYY-MM-DD or ISO
  side: "BUY" | "SELL";
  pnl?: number | null;
};

export default function PriceChart({
  symbol,
  traderClass,
  signal = "NONE",
  fearGreed,
  tradeMarkers,
}: {
  symbol: string;
  traderClass: TraderClass;
  signal?: TradeSignal;
  fearGreed?: { label: string; value: number } | null;
  tradeMarkers?: TradeMarker[];
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [loading, setLoading] = useState(true);
  const [bars, setBars] = useState<OhlcvBar[]>([]);
  const [timeframe, setTimeframe] = useState<"1h" | "24h" | "7d" | "30d">("24h");

  const live = useLivePrice(symbol || null);

  const config = useMemo(() => {
    if (traderClass === "complete_novice") return { type: "area" as const, days: 7, height: 100 };
    if (traderClass === "curious_saver") return { type: "area" as const, days: 14, height: 120 };
    if (traderClass === "self_taught") return { type: "area" as const, days: 30, height: 150 };
    if (traderClass === "experienced") return { type: "candle" as const, days: 30, height: 180 };
    if (traderClass === "semi_institutional") return { type: "candle" as const, days: 90, height: 220 };
    // crypto_native defaults to 24h; we approximate via daily bars for now
    return { type: "area" as const, days: timeframe === "7d" ? 7 : timeframe === "30d" ? 30 : 7, height: 160 };
  }, [traderClass, timeframe]);

  // Fetch OHLCV
  useEffect(() => {
    if (!symbol) return;
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const res = await api.get("/api/trading/ohlcv", {
          params: { symbol, days: config.days, interval: "1day" },
        });
        const d = res.data?.data ?? res.data;
        const arr: OhlcvBar[] = Array.isArray(d) ? d : [];
        if (!mounted) return;
        setBars(arr.filter((b) => b.time));
      } catch {
        if (!mounted) return;
        setBars([]);
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [symbol, config.days]);

  // Create / rebuild chart when data or config changes
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // cleanup
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(el, {
      height: config.height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "rgba(148,163,184,0.9)",
      },
      grid: {
        vertLines: { color: "rgba(30,41,59,0.6)" },
        horzLines: { color: "rgba(30,41,59,0.6)" },
      },
      crosshair: { mode: CrosshairMode.Magnet },
      rightPriceScale: {
        visible: traderClass !== "complete_novice",
        borderVisible: false,
      },
      leftPriceScale: {
        visible: false,
      },
      timeScale: {
        borderVisible: false,
      },
    });
    chartRef.current = chart;

    const timeData = bars.map((b) => ({
      time: b.time as any,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      value: b.close,
    }));

    if (config.type === "area") {
      const area = chart.addSeries(AreaSeries, {
        lineColor: "rgba(56,189,248,0.9)",
        topColor: "rgba(56,189,248,0.25)",
        bottomColor: "rgba(56,189,248,0.02)",
        lineWidth: 2,
      });
      area.setData(timeData.map((d) => ({ time: d.time, value: d.close })));

      // self_taught overlay: 20MA dashed amber
      if (traderClass === "self_taught") {
        const ma = sma(bars.map((b) => b.close), 20);
        const line = chart.addSeries(LineSeries, {
          color: "rgba(245,158,11,0.9)",
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
        });
        line.setData(
          bars
            .map((b, i) => (ma[i] === null ? null : { time: b.time as any, value: ma[i] as number }))
            .filter(Boolean) as any,
        );
      }
    } else {
      const candle = chart.addSeries(CandlestickSeries, {
        upColor: "rgba(34,197,94,0.9)",
        downColor: "rgba(239,68,68,0.9)",
        borderVisible: false,
        wickUpColor: "rgba(34,197,94,0.9)",
        wickDownColor: "rgba(239,68,68,0.9)",
      });
      candle.setData(
        timeData.map((d) => ({
          time: d.time,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        })),
      );

      // overlays
      const closes = bars.map((b) => b.close);
      const addMA = (period: number, color: string) => {
        const ma = sma(closes, period);
        const line = chart.addSeries(LineSeries, { color, lineWidth: 2 });
        line.setData(
          bars
            .map((b, i) => (ma[i] === null ? null : { time: b.time as any, value: ma[i] as number }))
            .filter(Boolean) as any,
        );
      };
      addMA(20, "rgba(245,158,11,0.9)");
      addMA(50, "rgba(59,130,246,0.9)");
      if (traderClass === "semi_institutional") {
        addMA(200, "rgba(148,163,184,0.9)");
        // Bollinger Bands (20, 2 std)
        const ma20 = sma(closes, 20);
        const sd20 = std(closes, 20);
        const upper = chart.addSeries(LineSeries, { color: "rgba(34,197,94,0.6)", lineWidth: 1 });
        const lower = chart.addSeries(LineSeries, { color: "rgba(239,68,68,0.6)", lineWidth: 1 });
        upper.setData(
          bars
            .map((b, i) =>
              ma20[i] === null || sd20[i] === null
                ? null
                : { time: b.time as any, value: (ma20[i] as number) + 2 * (sd20[i] as number) },
            )
            .filter(Boolean) as any,
        );
        lower.setData(
          bars
            .map((b, i) =>
              ma20[i] === null || sd20[i] === null
                ? null
                : { time: b.time as any, value: (ma20[i] as number) - 2 * (sd20[i] as number) },
            )
            .filter(Boolean) as any,
        );
      }

      // volume bars (experienced + semi_institutional)
      if (traderClass === "experienced" || traderClass === "semi_institutional") {
        const vol = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "volume" },
          priceScaleId: "",
          color: "rgba(148,163,184,0.25)",
        });
        vol.setData(
          bars.map((b) => ({
            time: b.time as any,
            value: b.volume,
            color: "rgba(148,163,184,0.25)",
          })),
        );
      }
    }

    chart.timeScale().fitContent();

    // ── Trade markers (entry/exit arrows + price line) ──
    if (tradeMarkers && tradeMarkers.length > 0 && bars.length > 0) {
      // Find the main series (first series added)
      const mainSeries = (chart as any).getSeries?.() ?? [];
      const series = mainSeries[0] ?? null;

      for (const m of tradeMarkers) {
        // Dashed horizontal line at entry price
        if (m.type === "entry" && series) {
          try {
            series.createPriceLine({
              price: m.price,
              color: m.side === "BUY" ? "rgba(34,197,94,0.6)" : "rgba(239,68,68,0.6)",
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              axisLabelVisible: true,
              title: m.side === "BUY" ? "Entry ▲" : "Entry ▼",
            });
          } catch { /* older lightweight-charts versions */ }
        }
        if (m.type === "exit" && series) {
          try {
            const pnlLabel = m.pnl != null
              ? (m.pnl >= 0 ? ` +$${m.pnl.toFixed(2)}` : ` -$${Math.abs(m.pnl).toFixed(2)}`)
              : "";
            series.createPriceLine({
              price: m.price,
              color: (m.pnl ?? 0) >= 0 ? "rgba(34,197,94,0.6)" : "rgba(239,68,68,0.6)",
              lineWidth: 1,
              lineStyle: LineStyle.Dotted,
              axisLabelVisible: true,
              title: `Exit${pnlLabel}`,
            });
          } catch { /* fallback */ }
        }
      }
    }

    const onResize = () => {
      if (!containerRef.current || !chartRef.current) return;
      chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
    };
    onResize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, config.height, config.type, traderClass, tradeMarkers]);

  // Realtime: update last bar close with live price
  useEffect(() => {
    if (!live.price || !bars.length) return;
    const last = bars[bars.length - 1];
    const next = { ...last, close: live.price, high: Math.max(last.high, live.price), low: Math.min(last.low, live.price) };
    setBars((prev) => {
      if (!prev.length) return prev;
      const copy = prev.slice();
      copy[copy.length - 1] = next;
      return copy;
    });
  }, [live.price]); // eslint-disable-line react-hooks/exhaustive-deps

  const currentPrice = live.price ?? (bars.length ? bars[bars.length - 1].close : null);
  const rsiValue = useMemo(() => computeRSI(bars.map((b) => b.close), 14), [bars]);
  const rsiColor =
    rsiValue === null ? "bg-dark-800" : rsiValue < 40 ? "bg-green-500/30" : rsiValue > 70 ? "bg-red-500/30" : "bg-dark-800";

  const changePct = live.changePct;
  const changeColor =
    changePct === null ? "text-dark-300" : changePct >= 0 ? "text-green-300" : "text-red-300";

  const showPct =
    traderClass !== "complete_novice";

  const showExport = traderClass === "semi_institutional";

  return (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs text-dark-500">{symbol.toUpperCase()}</div>
          <div className="flex items-baseline gap-2">
            <div className="text-lg font-bold text-white">
              {currentPrice === null ? "—" : currentPrice.toLocaleString(undefined, { maximumFractionDigits: 6 })}
            </div>
            {showPct && changePct !== null && (
              <div className={clsx("text-xs font-semibold tabular-nums", changeColor)}>
                {changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%
              </div>
            )}
            {traderClass === "self_taught" && rsiValue !== null && (
              <div className="text-xs text-dark-300 tabular-nums">RSI {Math.round(rsiValue)}</div>
            )}
          </div>
        </div>

        {traderClass === "crypto_native" && fearGreed && (
          <div
            className={clsx(
              "rounded-xl border px-3 py-2 text-xs font-semibold",
              fearGreed.value < 50
                ? "border-red-500/20 bg-red-500/10 text-red-200"
                : "border-green-500/20 bg-green-500/10 text-green-200",
            )}
          >
            {fearGreed.label} ({fearGreed.value})
          </div>
        )}
      </div>

      {traderClass === "crypto_native" && (
        <div className="inline-flex rounded-xl border border-dark-800 bg-dark-950 p-1">
          {(["1h", "24h", "7d", "30d"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTimeframe(t)}
              className={clsx(
                "rounded-lg px-3 py-1.5 text-xs font-semibold",
                timeframe === t ? "bg-dark-800 text-white" : "text-dark-300 hover:text-white",
              )}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <div className="rounded-xl border border-dark-800 bg-dark-900" style={{ height: config.height }} />
      ) : (
        <div className="relative">
          <div ref={containerRef} className="w-full" />
          {traderClass === "complete_novice" && signal !== "NONE" && (
            <div className="pointer-events-none absolute right-3 top-3 rounded-lg bg-dark-950/80 px-2 py-1 text-xs font-semibold">
              <span className={signal === "BUY" ? "text-green-300" : signal === "SELL" ? "text-red-300" : "text-dark-300"}>
                {signal}
              </span>
            </div>
          )}
        </div>
      )}

      {traderClass === "self_taught" && (
        <div className="h-[30px] w-full overflow-hidden rounded-xl border border-dark-800 bg-dark-950">
          <div className={clsx("h-full w-full", rsiColor)} />
        </div>
      )}

      {(traderClass === "experienced" || traderClass === "semi_institutional") && bars.length > 5 && (
        <div className="text-xs text-dark-400">
          Volume (last bar):{" "}
          <span className="tabular-nums text-dark-200">
            {Math.round(bars[bars.length - 1].volume).toLocaleString()}
          </span>
        </div>
      )}

      {showExport && (
        <div>
          <button
            type="button"
            onClick={() => {
              const chart = chartRef.current as any;
              if (!chart?.takeScreenshot) return;
              const canvas: HTMLCanvasElement = chart.takeScreenshot();
              const url = canvas.toDataURL("image/png");
              const a = document.createElement("a");
              a.href = url;
              a.download = `${symbol.toUpperCase()}-${Date.now()}.png`;
              a.click();
            }}
            className="btn-outline text-xs"
          >
            Export PNG
          </button>
        </div>
      )}
    </div>
  );
}

