/**
 * AIPicksPanel
 *
 * Shown when the user is in "AI Picks" mode.
 * Fetches the top 3 opportunities the AI identified (without executing),
 * displays them as cards, and lets the user choose which one to trade.
 */

import { useState, useEffect, useCallback } from "react";
import {
  TrendingUp, TrendingDown, Minus, Loader2, RefreshCw,
  ChevronDown, ChevronUp, Zap, AlertCircle, Brain,
} from "lucide-react";
import { api, tradingApi } from "@/lib/api";
import { formatPrice } from "@/utils/formatPrice";
import TradeConfirmModal from "./TradeConfirmModal";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Pick {
  symbol: string;
  decision: string;
  confidence: number;
  reasoning: string;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  market_condition?: string;
  key_factors?: string[];
}

const BRAND: Record<string, string> = {
  AAPL: "Apple", MSFT: "Microsoft", NVDA: "NVIDIA", TSLA: "Tesla",
  AMZN: "Amazon", GOOGL: "Alphabet", META: "Meta", SPY: "S&P 500 ETF",
  VOO: "Vanguard S&P 500", "BTC/USD": "Bitcoin",
  BTCUSDT: "Bitcoin", ETHUSDT: "Ethereum", SOLUSDT: "Solana",
  BNBUSDT: "BNB", XRPUSDT: "XRP",
  EUR_USD: "EUR/USD", GBP_USD: "GBP/USD", USD_JPY: "USD/JPY",
  AUD_USD: "AUD/USD", USD_CAD: "USD/CAD",
};

// ─── Individual Pick Card ─────────────────────────────────────────────────────

function PickCard({
  pick,
  rank,
  exchange,
  isPaper,
  traderClass,
  onTradeConfirmed,
}: {
  pick: Pick;
  rank: number;
  exchange: string;
  isPaper: boolean;
  traderClass: string;
  onTradeConfirmed: (symbol: string) => void;
}) {
  const [expanded, setExpanded] = useState(rank === 1);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [trading, setTrading] = useState(false);
  const [done, setDone] = useState(false);

  const isBuy  = pick.decision?.toUpperCase() === "BUY";
  const isSell = pick.decision?.toUpperCase() === "SELL";
  const name   = BRAND[pick.symbol] ?? pick.symbol;

  const handleConfirmedTrade = async () => {
    setTrading(true);
    try {
      await tradingApi.execute(pick.symbol, exchange);
      setDone(true);
      onTradeConfirmed(pick.symbol);
    } finally {
      setTrading(false);
    }
  };

  // Confidence colour
  const confColor =
    pick.confidence >= 75 ? "text-brand-400" :
    pick.confidence >= 55 ? "text-yellow-400" :
    "text-dark-400";

  const borderColor =
    isBuy  ? "border-brand-500/25" :
    isSell ? "border-red-500/25"   :
    "border-dark-700";

  const bgColor =
    isBuy  ? "bg-brand-500/[0.03]" :
    isSell ? "bg-red-500/[0.03]"   :
    "bg-[#0d1117]";

  if (done) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-brand-500/25 bg-brand-500/[0.04] px-5 py-4">
        <Zap size={16} className="text-brand-400 shrink-0" />
        <div>
          <p className="text-sm font-semibold text-brand-300">Trade submitted for {name}</p>
          <p className="text-xs text-dark-500 mt-0.5">Your AI is executing — check Positions shortly.</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-2xl border ${borderColor} ${bgColor} overflow-hidden`}>
      {/* Card header — always visible */}
      <div className="flex items-center gap-3 px-5 py-4">
        {/* Rank badge */}
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-dark-700 bg-dark-900 text-xs font-bold text-dark-400">
          #{rank}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-bold text-white">{name}</span>
            <span className="font-mono text-[11px] text-dark-500">{pick.symbol}</span>
            {pick.market_condition && (
              <span className="text-[11px] text-dark-600">{pick.market_condition}</span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            {isBuy ? (
              <span className="flex items-center gap-1 text-xs font-bold text-brand-400">
                <TrendingUp size={12} /> BUY
              </span>
            ) : isSell ? (
              <span className="flex items-center gap-1 text-xs font-bold text-red-400">
                <TrendingDown size={12} /> SELL
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs font-bold text-yellow-400">
                <Minus size={12} /> WAIT
              </span>
            )}
            <span className={`text-xs font-semibold tabular-nums ${confColor}`}>
              {pick.confidence?.toFixed(0)}% confidence
            </span>
          </div>
        </div>

        {/* Confidence bar */}
        <div className="hidden sm:block w-20 shrink-0">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-dark-800">
            <div
              className={`h-1.5 rounded-full transition-all ${isBuy ? "bg-brand-400" : isSell ? "bg-red-400" : "bg-yellow-400"}`}
              style={{ width: `${Math.min(100, pick.confidence || 0)}%` }}
            />
          </div>
        </div>

        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="shrink-0 text-dark-500 hover:text-dark-300 transition-colors"
        >
          {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </button>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-dark-800 px-5 pb-5 pt-4 space-y-4">
          {/* AI Reasoning */}
          {pick.reasoning && (
            <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
              <div className="flex items-center gap-1.5 mb-2 text-[11px] font-semibold uppercase tracking-widest text-dark-500">
                <Brain size={11} /> Why the AI picked this
              </div>
              <p className="text-xs text-dark-300 leading-relaxed">{pick.reasoning}</p>
            </div>
          )}

          {/* Key factors */}
          {pick.key_factors && pick.key_factors.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {pick.key_factors.slice(0, 4).map((f, i) => (
                <span key={i} className="rounded-lg border border-dark-700 bg-dark-900 px-2.5 py-1 text-[11px] text-dark-400">
                  {f}
                </span>
              ))}
            </div>
          )}

          {/* Price levels */}
          {pick.entry_price && (
            <div className="grid grid-cols-3 gap-2.5">
              <div className="rounded-xl border border-dark-700 p-3 text-center">
                <p className="text-[10px] uppercase tracking-wider text-dark-500 mb-1">Entry</p>
                <p className="font-mono text-sm font-bold text-white tabular-nums">
                  {formatPrice(pick.entry_price, pick.symbol)}
                </p>
              </div>
              <div className="rounded-xl border border-red-500/15 p-3 text-center">
                <p className="text-[10px] uppercase tracking-wider text-dark-500 mb-1">Stop Loss</p>
                <p className="font-mono text-sm font-bold text-red-400 tabular-nums">
                  {pick.stop_loss ? formatPrice(pick.stop_loss, pick.symbol) : "—"}
                </p>
              </div>
              <div className="rounded-xl border border-brand-500/15 p-3 text-center">
                <p className="text-[10px] uppercase tracking-wider text-dark-500 mb-1">Take Profit</p>
                <p className="font-mono text-sm font-bold text-brand-400 tabular-nums">
                  {pick.take_profit ? formatPrice(pick.take_profit, pick.symbol) : "—"}
                </p>
              </div>
            </div>
          )}

          {/* Trade button */}
          {(isBuy || isSell) && (
            <button
              type="button"
              onClick={() => setConfirmOpen(true)}
              disabled={trading}
              className="btn-primary w-full py-3 disabled:opacity-50"
            >
              {trading
                ? <><Loader2 size={14} className="animate-spin" /> Executing…</>
                : <><Zap size={14} /> Trade {name} now</>}
            </button>
          )}

          {isPaper && (
            <p className="text-center text-[11px] text-amber-400">
              Practice trade — no real money used
            </p>
          )}
        </div>
      )}

      <TradeConfirmModal
        isOpen={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={handleConfirmedTrade}
        trade={{
          symbol: pick.symbol,
          decision: pick.decision,
          side: pick.decision,
          entry_price: pick.entry_price ?? undefined,
          stop_loss: pick.stop_loss ?? undefined,
          take_profit: pick.take_profit ?? undefined,
          reasoning: pick.reasoning,
        }}
        isPaper={isPaper}
        traderClass={traderClass as any}
      />
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function AIPicksPanel({
  exchange,
  isPaper,
  traderClass,
}: {
  exchange: string;
  isPaper: boolean;
  traderClass: string;
}) {
  const [picks, setPicks]     = useState<Pick[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get("/api/trading/ai-picks", {
        params: { exchange, limit: 3 },
      });
      const data: Pick[] = res.data?.data || [];
      setPicks(data);
      setLastRefresh(new Date());
    } catch (err: any) {
      setError(err.response?.data?.detail || "Could not fetch AI picks. Try again shortly.");
    } finally {
      setLoading(false);
    }
  }, [exchange]);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 5 minutes (matches the AI scan cycle)
  useEffect(() => {
    const id = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [load]);

  const handleTraded = (symbol: string) => {
    // Remove the traded pick from the list
    setPicks((prev) => prev.filter((p) => p.symbol !== symbol));
  };

  return (
    <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-white">AI Picks for You</p>
          <p className="text-xs text-dark-500 mt-0.5">
            Best opportunities right now — choose which one to trade
          </p>
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-[11px] text-dark-600 tabular-nums">
              {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-dark-800 px-2.5 py-1.5 text-[11px] text-dark-400 hover:text-white transition-colors disabled:opacity-50"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* Explanation banner */}
      <div className="rounded-xl border border-dark-800 bg-dark-950/60 px-4 py-3 text-xs text-dark-400 leading-relaxed">
        Your AI analysed the full market watchlist and selected the best opportunities below.
        <span className="text-dark-200 font-medium"> You choose which one to trade.</span>
        {" "}The AI provides the entry, stop-loss and take-profit levels automatically.
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-10 text-xs text-dark-500">
          <Loader2 size={14} className="mr-2 animate-spin text-brand-400" />
          Analysing {exchange} markets…
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="flex items-center gap-2.5 rounded-xl border border-red-500/20 bg-red-500/[0.04] px-4 py-3 text-sm text-red-400">
          <AlertCircle size={14} className="shrink-0" />
          {error}
        </div>
      )}

      {/* Picks */}
      {!loading && !error && picks.length === 0 && (
        <div className="rounded-xl border border-dark-800 bg-dark-900/30 p-6 text-center">
          <p className="text-sm font-semibold text-white">No strong signals right now</p>
          <p className="mt-1 text-xs text-dark-500">
            The AI is watching for opportunities. Check back in a few minutes or switch to Autopilot.
          </p>
        </div>
      )}

      {!loading && !error && picks.length > 0 && (
        <div className="space-y-3">
          {picks.map((pick, i) => (
            <PickCard
              key={pick.symbol}
              pick={pick}
              rank={i + 1}
              exchange={exchange}
              isPaper={isPaper}
              traderClass={traderClass}
              onTradeConfirmed={handleTraded}
            />
          ))}
        </div>
      )}

      <p className="text-center text-[11px] text-dark-600">
        Refreshes automatically every 5 minutes · Powered by Claude AI
      </p>
    </div>
  );
}
