/**
 * AIActivityStream
 *
 * Shows users exactly what the AI did in each scan cycle — in plain English.
 * Polls trade history every 30 s and presents each analysis as a readable step-by-step.
 * Also shows a countdown to the next automatic scan (5-min cycle).
 */

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Search, BarChart2, Brain, Zap, Clock, RefreshCw,
  TrendingUp, TrendingDown, Minus, CheckCircle2, Loader2,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatPrice } from "@/utils/formatPrice";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TradeRecord {
  id: string;
  symbol: string;
  side: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  claude_confidence?: number;
  reasoning?: string;
  market_trend?: string;
  rsi?: number;
  macd?: number;
  volume_ratio?: number;
  status: string;
  created_at: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const SCAN_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes (matches backend loop)
const POLL_INTERVAL_MS = 30 * 1000;      // refresh history every 30 s

const BRAND: Record<string, string> = {
  AAPL: "Apple", MSFT: "Microsoft", NVDA: "NVIDIA", TSLA: "Tesla",
  AMZN: "Amazon", GOOGL: "Alphabet", META: "Meta", SPY: "S&P 500 ETF",
  VOO: "Vanguard S&P 500", "BTC/USD": "Bitcoin",
  BTCUSDT: "Bitcoin", ETHUSDT: "Ethereum", SOLUSDT: "Solana",
  BNBUSDT: "BNB", XRPUSDT: "XRP",
  EUR_USD: "EUR/USD", GBP_USD: "GBP/USD", USD_JPY: "USD/JPY",
  AUD_USD: "AUD/USD", USD_CAD: "USD/CAD",
};

function brandName(symbol: string) {
  return BRAND[symbol?.toUpperCase()] ?? symbol;
}

function relativeTime(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1)  return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function rsiLabel(rsi: number): string {
  if (rsi >= 70) return `${rsi} — overbought`;
  if (rsi <= 30) return `${rsi} — oversold`;
  return `${rsi} — neutral`;
}

function macdLabel(macd: number): string {
  return macd > 0 ? "Positive crossover (bullish)" : "Negative crossover (bearish)";
}

/** Convert a trade record into an array of plain-English "steps" the AI took. */
function buildSteps(t: TradeRecord): Array<{ icon: React.ReactNode; text: string; sub?: string }> {
  const name   = brandName(t.symbol);
  const isBuy  = t.side?.toUpperCase() === "BUY";
  const isSell = t.side?.toUpperCase() === "SELL";

  const steps: Array<{ icon: React.ReactNode; text: string; sub?: string }> = [];

  steps.push({
    icon: <Search size={12} className="text-dark-500" />,
    text: `Fetched live market data for ${name}`,
    sub: t.entry_price ? `Current price: ${formatPrice(t.entry_price, t.symbol)}` : undefined,
  });

  if (t.rsi != null || t.macd != null || t.volume_ratio != null) {
    const indicators: string[] = [];
    if (t.rsi != null)          indicators.push(`RSI ${rsiLabel(t.rsi)}`);
    if (t.macd != null)         indicators.push(`MACD: ${macdLabel(t.macd)}`);
    if (t.volume_ratio != null) indicators.push(`Volume ${t.volume_ratio}× 30-day avg`);
    steps.push({
      icon: <BarChart2 size={12} className="text-dark-400" />,
      text: "Analysed technical indicators",
      sub: indicators.join(" · "),
    });
  }

  if (t.market_trend) {
    steps.push({
      icon: <TrendingUp size={12} className="text-dark-400" />,
      text: `Detected market trend: ${t.market_trend}`,
    });
  }

  if (t.reasoning) {
    steps.push({
      icon: <Brain size={12} className="text-brand-400" />,
      text: "AI reasoning",
      sub: t.reasoning.length > 180 ? t.reasoning.slice(0, 180) + "…" : t.reasoning,
    });
  }

  const confidence = t.claude_confidence != null ? ` — ${t.claude_confidence}% confidence` : "";
  steps.push({
    icon: isBuy  ? <CheckCircle2 size={12} className="text-brand-400" /> :
          isSell ? <CheckCircle2 size={12} className="text-red-400"   /> :
                   <Minus        size={12} className="text-yellow-400" />,
    text: isBuy  ? `Decision: BUY${confidence}` :
          isSell ? `Decision: SELL${confidence}` :
                   `Decision: WAIT — not enough signal${confidence}`,
  });

  if ((isBuy || isSell) && t.entry_price) {
    steps.push({
      icon: <Zap size={12} className="text-dark-500" />,
      text: "Order parameters set",
      sub: [
        `Entry ${formatPrice(t.entry_price, t.symbol)}`,
        t.stop_loss   ? `Stop-loss ${formatPrice(t.stop_loss,   t.symbol)}` : null,
        t.take_profit ? `Take-profit ${formatPrice(t.take_profit, t.symbol)}` : null,
      ].filter(Boolean).join(" · "),
    });
  }

  return steps;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function DecisionBadge({ side }: { side: string }) {
  const up = side?.toUpperCase();
  if (up === "BUY")
    return (
      <span className="flex items-center gap-1 rounded-lg border border-brand-500/30 bg-brand-500/10 px-2 py-0.5 text-[11px] font-bold text-brand-400">
        <TrendingUp size={10} /> BUY
      </span>
    );
  if (up === "SELL")
    return (
      <span className="flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] font-bold text-red-400">
        <TrendingDown size={10} /> SELL
      </span>
    );
  return (
    <span className="flex items-center gap-1 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-2 py-0.5 text-[11px] font-bold text-yellow-400">
      <Minus size={10} /> WAIT
    </span>
  );
}

function ActivityEntry({ trade, defaultOpen }: { trade: TradeRecord; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen ?? false);
  const steps = buildSteps(trade);

  return (
    <div className="rounded-xl border border-dark-800 bg-dark-900/40 overflow-hidden">
      {/* Header row — always visible */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-dark-900/60 transition-colors"
      >
        {/* Pulse dot */}
        <div className="h-2 w-2 shrink-0 rounded-full bg-dark-600" />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-white">{brandName(trade.symbol)}</span>
            <span className="font-mono text-[11px] text-dark-600">{trade.symbol}</span>
          </div>
        </div>

        <DecisionBadge side={trade.side} />

        {trade.claude_confidence != null && (
          <span className="hidden sm:block shrink-0 text-[11px] text-dark-500 tabular-nums">
            {trade.claude_confidence}%
          </span>
        )}

        <span className="shrink-0 text-[11px] text-dark-600 tabular-nums">
          {relativeTime(trade.created_at)}
        </span>

        <span className="shrink-0 text-[11px] text-dark-600">{open ? "▲" : "▼"}</span>
      </button>

      {/* Expandable step-by-step reasoning */}
      {open && (
        <div className="border-t border-dark-800 px-4 pb-4 pt-3">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-widest text-dark-600">
            How your AI decided
          </p>
          <ol className="space-y-2.5">
            {steps.map((step, i) => (
              <li key={i} className="flex gap-3">
                {/* Step connector */}
                <div className="flex flex-col items-center">
                  <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-dark-700 bg-dark-950">
                    {step.icon}
                  </div>
                  {i < steps.length - 1 && (
                    <div className="mt-1 w-px flex-1 bg-dark-800" style={{ minHeight: 8 }} />
                  )}
                </div>
                <div className="pb-1 min-w-0">
                  <p className="text-xs text-dark-200">{step.text}</p>
                  {step.sub && (
                    <p className="mt-0.5 text-[11px] leading-relaxed text-dark-500">{step.sub}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

// ─── Countdown timer ──────────────────────────────────────────────────────────

function NextScanCountdown({ lastFetchAt }: { lastFetchAt: number }) {
  const [secsLeft, setSecsLeft] = useState(0);

  useEffect(() => {
    const tick = () => {
      const nextScan = lastFetchAt + SCAN_INTERVAL_MS;
      const diff = Math.max(0, Math.round((nextScan - Date.now()) / 1000));
      setSecsLeft(diff);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [lastFetchAt]);

  const mins = Math.floor(secsLeft / 60);
  const secs = secsLeft % 60;
  const pct  = 100 - (secsLeft / (SCAN_INTERVAL_MS / 1000)) * 100;

  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950/60 px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-[11px] text-dark-500">
          <Clock size={11} />
          Next scan cycle
        </div>
        <span className="font-mono text-[11px] text-dark-300 tabular-nums">
          {String(mins).padStart(2, "0")}:{String(secs).padStart(2, "0")}
        </span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-dark-800">
        <div
          className="h-1 rounded-full bg-brand-400 transition-all duration-1000"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-[11px] text-dark-600">
        Your AI runs a full market scan automatically every 5 minutes
      </p>
    </div>
  );
}

// ─── Main export ──────────────────────────────────────────────────────────────

export default function AIActivityStream() {
  const [trades, setTrades]         = useState<TradeRecord[]>([]);
  const [loading, setLoading]       = useState(true);
  const [lastFetchAt, setLastFetchAt] = useState(Date.now());
  const [scanning, setScanning]     = useState(false);
  const timerRef                    = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (showScan = false) => {
    if (showScan) { setScanning(true); await new Promise((r) => setTimeout(r, 1200)); }
    try {
      const res  = await api.get("/api/trading/history", { params: { limit: 30 } });
      const data: TradeRecord[] = res.data?.data?.trades || res.data?.trades || [];
      setTrades(data);
      setLastFetchAt(Date.now());
    } catch { /* silent — don't disrupt the UI */ }
    finally  { setLoading(false); setScanning(false); }
  }, []);

  // Initial load
  useEffect(() => { load(); }, [load]);

  // Poll every 30 s
  useEffect(() => {
    timerRef.current = setInterval(() => load(), POLL_INTERVAL_MS);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [load]);

  return (
    <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5 space-y-4">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-white flex items-center gap-2">
            <span className="relative flex h-2 w-2 shrink-0">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-400" />
            </span>
            AI Live Feed
          </p>
          <p className="text-xs text-dark-500 mt-0.5">
            Every decision — explained in plain English
          </p>
        </div>
        <button
          onClick={() => load(true)}
          disabled={scanning || loading}
          className="flex items-center gap-1.5 rounded-lg border border-dark-800 px-2.5 py-1.5 text-[11px] text-dark-400 hover:text-white transition-colors disabled:opacity-50"
        >
          <RefreshCw size={11} className={scanning || loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* Countdown to next scan */}
      <NextScanCountdown lastFetchAt={lastFetchAt} />

      {/* Scanning state */}
      {scanning && (
        <div className="flex items-center gap-3 rounded-xl border border-brand-500/20 bg-brand-500/[0.04] px-4 py-3">
          <Loader2 size={14} className="animate-spin text-brand-400 shrink-0" />
          <div>
            <p className="text-xs font-semibold text-brand-300">AI is scanning markets…</p>
            <p className="text-[11px] text-dark-500">Fetching live data, running indicators, deciding…</p>
          </div>
        </div>
      )}

      {/* Feed */}
      {loading && !scanning ? (
        <div className="flex items-center justify-center py-8 text-xs text-dark-500">
          <Loader2 size={13} className="mr-2 animate-spin" /> Loading AI decisions…
        </div>
      ) : trades.length === 0 ? (
        <div className="rounded-xl border border-dark-800 bg-dark-900/30 p-6 text-center">
          <p className="text-sm font-semibold text-white">No activity yet</p>
          <p className="mt-1 text-xs text-dark-500">
            Your AI scans markets every 5 minutes. First decisions will appear here shortly.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {/* First entry starts expanded so users immediately see the reasoning */}
          {trades.slice(0, 15).map((t, i) => (
            <ActivityEntry key={t.id || i} trade={t} defaultOpen={i === 0} />
          ))}
        </div>
      )}

      {trades.length > 0 && (
        <p className="text-center text-[11px] text-dark-600">
          Showing the last {Math.min(trades.length, 15)} AI decisions · Auto-updates every 30 s
        </p>
      )}
    </div>
  );
}
