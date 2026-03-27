import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/router";
import {
  Crosshair, Loader2, TrendingUp, TrendingDown, Minus,
  AlertCircle, ChevronRight, Link2, Zap, Clock, Bot,
} from "lucide-react";
import { api, tradingApi, exchangeApi, authApi } from "@/lib/api";
import CircuitBreakerAlert from "./trade/CircuitBreakerAlert";
import MarketStatusBar, { type MarketStatus } from "./trade/MarketStatusBar";
import TrustLadderBanner from "./trade/TrustLadderBanner";
import ExplanationToggle from "./trade/ExplanationToggle";
import TradeConfirmModal from "./trade/TradeConfirmModal";
import { useLivePrice } from "@/hooks/useLivePrice";
import { formatPrice } from "@/utils/formatPrice";
import BrandPicker from "./trade/BrandPicker";
import WhatIfSimulator from "./onboarding/WhatIfSimulator";
import PriceChart from "./trade/PriceChart";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

interface ConnectedExchange {
  exchange: string;
  connected_at: string | null;
}

interface TradeResult {
  status: string;
  reason?: string;
  decision?: string;
  confidence?: number;
  reasoning?: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  side?: string;
  symbol?: string;
  quantity?: number;
  trade_id?: string;
  market_trend?: string;
  message?: string;
  expert?: string;
  simple?: string;
  metaphor?: string;
  rsi?: number;
  macd?: number;
  volume_ratio?: number;
  sentiment_score?: number;
  days_to_earnings?: number;
}

type TrustLadder = {
  stage: 1 | 2 | 3 | 4;
  paperEnabled: boolean;
  canAdvance: boolean;
  daysAtStage: number;
  paperTradesCount: number;
  maxAmountGbp?: number;
};

const POPULAR_SYMBOLS: Record<string, string[]> = {
  alpaca: ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "SPY", "BTC/USD"],
  binance: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"],
  oanda: ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"],
};

function normaliseSymbol(sym: string, exchange: string): string {
  const s = sym.trim().toUpperCase().replace(/\s/g, "");
  if (!s) return s;
  const ex = exchange.toLowerCase();
  if (ex === "binance" && /^BTC$/i.test(s)) return "BTCUSDT";
  if (ex === "binance" && /^ETH$/i.test(s)) return "ETHUSDT";
  if (ex === "alpaca" && /^BTC$/i.test(s)) return "BTC/USD";
  return s;
}

function getAmountLimits(traderClass: string, trustStage: number) {
  const limits: Record<string, { min: number; max: number; step: number }> = {
    complete_novice:    { min: 1,  max: 25,    step: 1   },
    curious_saver:      { min: 1,  max: 500,   step: 1   },
    self_taught:        { min: 1,  max: 5000,  step: 5   },
    experienced:        { min: 1,  max: 10000, step: 10  },
    semi_institutional: { min: 1,  max: 50000, step: 100 },
    crypto_native:      { min: 1,  max: 5000,  step: 5   },
  };
  if (trustStage === 1) return { min: 1, max: 25, step: 1 };
  return limits[traderClass] ?? limits["complete_novice"];
}

function getAmountHelperText(traderClass: string, trustStage: number, min: number): string | null {
  if (traderClass === "complete_novice")
    return trustStage === 1 ? "£25 maximum during Watch Mode — Unitrader is proving itself" : "Unitrader will grow your limit as it builds your trust";
  if (traderClass === "experienced" || traderClass === "semi_institutional") return null;
  return "Unitrader works best with £25 or more — smaller amounts earn very small returns";
}

export default function TradePanel({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const router = useRouter();

  // ── Core state ──
  const [exchanges, setExchanges] = useState<ConnectedExchange[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedExchange, setSelectedExchange] = useState("");
  const [symbol, setSymbol] = useState("");
  const [traderClass, setTraderClass] = useState<TraderClass>("complete_novice");
  const [showBrandPickerForExperienced, setShowBrandPickerForExperienced] = useState(false);

  // ── Analysis + execution state ──
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<TradeResult | null>(null);
  const [error, setError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // ── Recent AI activity (from trade history) ──
  const [recentActivity, setRecentActivity] = useState<any[]>([]);

  // ── Settings & trust ──
  const [tradingPaused, setTradingPaused] = useState(false);
  const [maxDailyLoss, setMaxDailyLoss] = useState(10);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [trust, setTrust] = useState<TrustLadder | null>(null);
  const [amount, setAmount] = useState(100);
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null);

  // ── Self-taught track record ──
  const [selfTaughtStart, setSelfTaughtStart] = useState<number | null>(null);

  const livePrice = useLivePrice(symbol ? symbol : null);

  // ── Derived values ──
  const isPaper = useMemo(() => {
    if (!trust) return traderClass === "complete_novice" || traderClass === "curious_saver";
    if (traderClass === "complete_novice" || traderClass === "curious_saver") return trust.stage <= 2;
    return false;
  }, [trust, traderClass]);

  const amountLimits = useMemo(
    () => getAmountLimits(traderClass, trust?.stage ?? 1),
    [traderClass, trust?.stage],
  );

  const amountHelperText = useMemo(
    () => getAmountHelperText(traderClass, trust?.stage ?? 1, amountLimits.min),
    [traderClass, trust?.stage, amountLimits.min],
  );

  const showAmountSlider = traderClass !== "experienced" && traderClass !== "semi_institutional";

  // ── Load exchanges ──
  useEffect(() => {
    exchangeApi.list().then((res) => {
      const data = res.data.data || [];
      setExchanges(data);
      if (data.length > 0) setSelectedExchange(data[0].exchange);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  // ── Load settings + trust ladder ──
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const [sRes, tRes] = await Promise.all([
          authApi.getSettings(),
          api.get("/api/onboarding/trust-ladder"),
        ]);
        if (!mounted) return;
        setTradingPaused(sRes.data.trading_paused || false);
        setMaxDailyLoss(sRes.data.max_daily_loss || 10);
        setTraderClass(sRes.data.trader_class || "complete_novice");
        setTrust(tRes.data?.data ?? tRes.data);
      } catch {
        if (!mounted) return;
        setTrust({ stage: 1, paperEnabled: true, canAdvance: false, daysAtStage: 1, paperTradesCount: 0, maxAmountGbp: 25 });
      } finally {
        if (mounted) setSettingsLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, []);

  // ── Fetch recent AI decisions for the activity feed ──
  useEffect(() => {
    api.get("/api/trading/history", { params: { limit: 6 } })
      .then((res) => {
        const trades = res.data?.data?.trades || res.data?.trades || [];
        setRecentActivity(trades.slice(0, 6));
      })
      .catch(() => {});
  }, []);

  // ── Self-taught 14-day tracker ──
  useEffect(() => {
    if (typeof window === "undefined" || traderClass !== "self_taught") return;
    const key = "unitrader_self_taught_track_start_v1";
    const existing = window.localStorage.getItem(key);
    if (existing && !Number.isNaN(Number(existing))) { setSelfTaughtStart(Number(existing)); return; }
    const now = Date.now();
    window.localStorage.setItem(key, String(now));
    setSelfTaughtStart(now);
  }, [traderClass]);

  const selfTaughtDay = useMemo(() => {
    if (traderClass !== "self_taught" || !selfTaughtStart) return null;
    const days = Math.floor((Date.now() - selfTaughtStart) / (24 * 60 * 60 * 1000));
    return Math.max(1, Math.min(14, days + 1));
  }, [traderClass, selfTaughtStart]);

  // ── Toast auto-dismiss ──
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(t);
  }, [toast]);

  // ── Phase 1: Analyze ──
  const handleAnalyze = async () => {
    if (!symbol.trim() || !selectedExchange) return;
    setAnalyzing(true);
    setResult(null);
    setError("");
    try {
      const normalised = normaliseSymbol(symbol, selectedExchange);
      const res = await tradingApi.execute(normalised, selectedExchange);
      const data = res.data?.data ?? res.data;
      setResult(data);
      if (data?.status === "rejected" || data?.status === "error") {
        setError(data.reason || "Trade was not executed.");
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      const msg = typeof detail === "string" ? detail
        : Array.isArray(detail) && detail[0]?.msg ? detail[0].msg
        : err.response?.data?.message || err.message || "Analysis failed. Please try again.";
      setError(msg);
    } finally {
      setAnalyzing(false);
    }
  };

  // ── Phase 2: Confirmed execution (from modal) ──
  const handleConfirmedTrade = async () => {
    const sym = normaliseSymbol(symbol.trim(), selectedExchange);
    if (!sym) throw new Error("Missing symbol");
    const res = await tradingApi.execute(sym, selectedExchange);
    setToast("Trade submitted");
    return res.data?.data ?? res.data;
  };

  const suggestions = POPULAR_SYMBOLS[selectedExchange] || [];

  const chartSignal =
    (result?.decision || result?.side || "NONE").toUpperCase() === "BUY" ? "BUY"
    : (result?.decision || result?.side || "NONE").toUpperCase() === "SELL" ? "SELL"
    : (result?.decision || result?.side || "NONE").toUpperCase() === "WAIT" ? "WAIT"
    : "NONE";

  const canShowOhlcvChart =
    selectedExchange === "alpaca" && !!symbol.trim() && !symbol.includes("/") && !symbol.includes("_");

  const isNoviceOrSaver = traderClass === "complete_novice" || traderClass === "curious_saver";

  // ── Loading state ──
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-dark-500">
        <Loader2 size={15} className="mr-2 animate-spin text-brand-400" /> Loading...
      </div>
    );
  }

  // ── No exchange gate ──
  if (exchanges.length === 0) {
    return (
      <div className="mx-auto max-w-md space-y-6 py-16 text-center animate-fade-in">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-dark-800 bg-[#0d1117]">
          <Link2 size={28} className="text-dark-500" />
        </div>
        <h1 className="page-title">Connect an Exchange First</h1>
        <p className="text-sm text-dark-400 leading-relaxed">
          To start trading, connect your exchange API keys. Your AI will analyze
          markets and execute trades on your behalf.
        </p>
        <button onClick={() => router.push("/connect-exchange")} className="btn-primary w-full">
          Connect Exchange <ChevronRight size={14} />
        </button>
      </div>
    );
  }

  // ── Analyze button label ──
  const analyzeLabel = isNoviceOrSaver
    ? "Analyse with Unitrader"
    : traderClass === "semi_institutional"
      ? "Bulk analyse"
      : "Analyse";

  // ── Execute button label (shown after analysis) ──
  const executeLabel = isPaper
    ? "Confirm practice trade"
    : traderClass === "experienced" || traderClass === "semi_institutional"
      ? "Execute"
      : "Execute trade";

  return (
    <div className="w-full space-y-5 animate-fade-in">
      <WhatIfSimulator mode="welcome_modal" />

      {/* Toast */}
      {toast && (
        <div className="fixed right-4 top-4 z-50 rounded-xl border border-dark-800 bg-dark-950 px-4 py-3 text-sm text-white shadow-xl">
          {toast}
        </div>
      )}

      {/* Self-taught 14-day tracker */}
      {traderClass === "self_taught" && selfTaughtDay !== null && selfTaughtDay <= 14 && (
        <div className="rounded-2xl border border-blue-500/15 bg-blue-500/[0.06] p-4">
          <div className="mb-2.5 flex items-center justify-between text-xs text-blue-200">
            <span className="font-semibold">Building your track record</span>
            <span className="tabular-nums font-mono">Day {selfTaughtDay} / 14</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-dark-800">
            <div className="h-1.5 rounded-full bg-blue-400 transition-all duration-500" style={{ width: `${(selfTaughtDay / 14) * 100}%` }} />
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500/10">
          <Bot size={18} className="text-brand-400" />
        </div>
        <div>
          <h1 className="page-title">AI Trader</h1>
          <p className="page-subtitle">Your AI is trading automatically — no action needed</p>
        </div>
      </div>

      {/* ── Autopilot Status ── */}
      <div className="rounded-2xl border border-brand-500/20 bg-brand-500/[0.04] p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <span className="relative flex h-3 w-3 shrink-0">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-50" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-brand-400" />
            </span>
            <div>
              <p className="text-sm font-bold text-white">Autopilot Active</p>
              <p className="text-xs text-dark-400">Scanning markets every 5 minutes</p>
            </div>
          </div>
          <span className={`rounded-lg border px-3 py-1 text-[11px] font-semibold ${
            isPaper
              ? "border-amber-500/30 bg-amber-500/[0.06] text-amber-300"
              : "border-brand-500/30 bg-brand-500/[0.06] text-brand-300"
          }`}>
            {isPaper ? "Paper Mode" : "Live Mode"}
          </span>
        </div>
        <p className="mt-3 text-xs text-dark-400 leading-relaxed">
          Your AI is working in the background — analysing markets, finding opportunities, and executing trades for you automatically. You don't need to pick symbols or click anything. The section below lets you request an instant on-demand analysis of any asset.
        </p>
      </div>

      {/* ── Recent AI Decisions ── */}
      {recentActivity.length > 0 && (
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
          <div className="flex items-center gap-2 mb-3">
            <Clock size={13} className="text-dark-500" />
            <span className="section-label">Recent AI Decisions</span>
          </div>
          <div className="space-y-2">
            {recentActivity.map((t: any, i: number) => {
              const isBuy = (t.side || "").toUpperCase() === "BUY" || (t.signal || "") === "buy";
              const isSell = (t.side || "").toUpperCase() === "SELL" || (t.signal || "") === "sell";
              const timeStr = t.created_at
                ? new Date(t.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                : "";
              return (
                <div key={t.id || i} className="flex items-center gap-3 rounded-xl border border-dark-800 bg-dark-900/40 px-3.5 py-2.5">
                  <div className={`h-2 w-2 shrink-0 rounded-full ${isBuy ? "bg-brand-400" : isSell ? "bg-red-400" : "bg-dark-600"}`} />
                  <div className="flex-1 min-w-0 text-xs">
                    <span className="font-mono font-semibold text-white">{t.symbol || "—"}</span>
                    <span className="ml-2 text-dark-400">
                      AI decided{" "}
                      <span className={isBuy ? "font-semibold text-brand-400" : isSell ? "font-semibold text-red-400" : "font-semibold text-yellow-400"}>
                        {isBuy ? "BUY" : isSell ? "SELL" : "WAIT"}
                      </span>
                      {t.claude_confidence != null && (
                        <span className="text-dark-500"> — confidence {t.claude_confidence}%</span>
                      )}
                    </span>
                  </div>
                  {timeStr && <span className="shrink-0 tabular-nums text-[11px] text-dark-600">{timeStr}</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── On-demand divider ── */}
      <div className="flex items-center gap-3 py-1">
        <div className="flex-1 border-t border-dark-800" />
        <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-widest text-dark-600">
          <Zap size={11} />
          On-demand analysis
        </span>
        <div className="flex-1 border-t border-dark-800" />
      </div>

      {/* Paper mode indicator */}
      {isPaper && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-3 text-sm text-amber-200">
          <span className="font-semibold">PRACTICE MODE</span> — no real money will be used
        </div>
      )}

      {/* Circuit breaker alert */}
      {!settingsLoading && (
        <CircuitBreakerAlert tradingPaused={tradingPaused} dailyLossPct={0} maxDailyLossPct={maxDailyLoss} />
      )}

      {/* Market status bar */}
      <MarketStatusBar
        traderClass={traderClass}
        exchange={selectedExchange}
        symbol={symbol}
        onStatusChange={setMarketStatus}
      />

      {/* Trust ladder banner (novice/saver stages 1-2) */}
      {isNoviceOrSaver && trust && (
        <TrustLadderBanner
          stage={trust.stage}
          paperEnabled={trust.paperEnabled}
          canAdvance={trust.canAdvance}
          daysAtStage={trust.daysAtStage}
          paperTradesCount={trust.paperTradesCount}
        />
      )}

      {/* Main card */}
      <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
        <div className="space-y-4">
          {/* Exchange selector */}
          <div>
            <label className="section-label mb-2">Exchange</label>
            <div className="flex gap-2 flex-wrap">
              {exchanges.map((ex) => (
                <button
                  key={ex.exchange}
                  onClick={() => { setSelectedExchange(ex.exchange); setSymbol(""); setResult(null); }}
                  className={`rounded-xl border px-4 py-2 text-xs font-medium transition-all ${
                    selectedExchange === ex.exchange
                      ? "border-brand-500/50 bg-brand-500/10 text-brand-400 shadow-glow-sm"
                      : "border-dark-700 text-dark-400 hover:border-dark-600 hover:text-dark-300"
                  }`}
                >
                  {ex.exchange.charAt(0).toUpperCase() + ex.exchange.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Symbol input (adapted by trader class) */}
          {traderClass === "semi_institutional" ? (
            <BrandPicker exchange={selectedExchange} onManualSymbol={(s) => setSymbol(s.toUpperCase())} />
          ) : (
            <>
              <div>
                <label className="section-label mb-2">Symbol</label>
                <input
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  onKeyDown={(e) => e.key === "Enter" && !analyzing && handleAnalyze()}
                  placeholder={selectedExchange === "alpaca" ? "e.g. AAPL" : selectedExchange === "binance" ? "e.g. BTCUSDT" : "e.g. EUR_USD"}
                  className="input font-mono text-sm"
                  disabled={analyzing}
                />
                {traderClass === "experienced" && (
                  <button type="button" onClick={() => setShowBrandPickerForExperienced((v) => !v)} className="mt-2 text-xs text-brand-400 hover:underline">
                    {showBrandPickerForExperienced ? "Hide brands" : "Browse brands"}
                  </button>
                )}
              </div>
              {traderClass !== "experienced" && (
                <BrandPicker
                  exchange={selectedExchange}
                  onManualSymbol={(s) => setSymbol(s.toUpperCase())}
                  onChangeSelectedSymbols={(syms) => setSymbol((syms[0] || "").toUpperCase())}
                  selectedSymbols={symbol ? [symbol] : []}
                />
              )}
              {traderClass === "experienced" && showBrandPickerForExperienced && (
                <BrandPicker
                  exchange={selectedExchange}
                  onManualSymbol={(s) => setSymbol(s.toUpperCase())}
                  onChangeSelectedSymbols={(syms) => setSymbol((syms[0] || "").toUpperCase())}
                  selectedSymbols={symbol ? [symbol] : []}
                />
              )}
            </>
          )}

          {/* Live price */}
          {symbol && (
            <div className="rounded-xl bg-dark-900/50 p-3.5 border border-dark-800">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-dark-500 mb-0.5">Live Price</p>
                  <p className="text-base font-bold text-white tabular-nums">
                    {livePrice.price !== null ? formatPrice(livePrice.price, symbol) : livePrice.isConnected ? "Loading..." : "Disconnected"}
                  </p>
                </div>
                <div className="text-right">
                  <p className={`text-xs font-mono tabular-nums ${livePrice.bid && livePrice.ask ? "text-dark-400" : "text-dark-500"}`}>
                    {livePrice.bid !== null && livePrice.ask !== null
                      ? `${formatPrice(livePrice.bid, symbol)} / ${formatPrice(livePrice.ask, symbol)}`
                      : "—"}
                  </p>
                  <p className="text-[11px] text-dark-500">Bid / Ask</p>
                </div>
              </div>
              <div className="mt-2.5 flex items-center justify-between text-[11px]">
                <span className={livePrice.isConnected ? "text-brand-400" : "text-red-400"}>
                  <span className="inline-block w-1.5 h-1.5 rounded-full mr-1 align-middle" style={{ backgroundColor: livePrice.isConnected ? "#0adb6a" : "#f87171" }} />
                  {livePrice.isConnected ? "Connected" : "Disconnected"}
                </span>
                <span className="text-dark-500 font-mono tabular-nums">
                  {livePrice.lastUpdated ? new Date(livePrice.lastUpdated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}
                </span>
              </div>
            </div>
          )}

          {/* Price chart */}
          {canShowOhlcvChart && (
            <div className="rounded-xl border border-dark-800 bg-dark-950/50 p-4">
              <PriceChart symbol={symbol} traderClass={traderClass as any} signal={chartSignal as any} />
            </div>
          )}

          {/* Amount slider (hidden for experienced/institutional) */}
          {showAmountSlider && (
            <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
              <div className="mb-2 flex items-center justify-between text-xs text-dark-400">
                <span>Amount (GBP)</span>
                <span className="tabular-nums text-white">£{amount}</span>
              </div>
              <input
                type="range"
                min={amountLimits.min}
                max={amountLimits.max}
                step={amountLimits.step}
                value={amount}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setAmount(Math.max(amountLimits.min, Math.min(amountLimits.max, v)));
                }}
                className="w-full"
              />
              <div className="mt-2 flex justify-between text-[11px] text-dark-500">
                <span>Min: £{amountLimits.min}</span>
                <span>Max: £{amountLimits.max}</span>
              </div>
              {amountHelperText && (
                <p className="mt-2 text-[11px] leading-relaxed text-dark-400">{amountHelperText}</p>
              )}
            </div>
          )}

          {/* Risk section */}
          <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
            <div className="text-xs font-semibold text-white">Risk</div>
            <div className="mt-2 text-xs text-dark-300">
              {traderClass === "self_taught" || traderClass === "experienced" || traderClass === "semi_institutional"
                ? "Stop-loss and take-profit are applied as % distances from entry where possible."
                : "Unitrader uses stop-loss and take-profit to manage downside and lock gains."}
            </div>
          </div>

          {/* Quick picks */}
          {suggestions.length > 0 && (
            <div>
              <p className="section-label mb-2">Quick picks</p>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSymbol(s)}
                    disabled={analyzing}
                    className={`rounded-lg border px-2.5 py-1.5 text-xs font-mono transition-all ${
                      symbol === s ? "border-brand-500/40 bg-brand-500/10 text-brand-400" : "border-dark-700 text-dark-500 hover:text-dark-300 hover:border-dark-600"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Analyze button */}
          <button
            onClick={handleAnalyze}
            disabled={!symbol.trim() || analyzing}
            title={marketStatus?.analyzeTooltip}
            className="btn-primary w-full py-3 disabled:opacity-50"
          >
            {analyzing ? (
              <><Loader2 size={15} className="animate-spin" /> Analysing...</>
            ) : (
              <><Crosshair size={15} /> {analyzeLabel}</>
            )}
          </button>

          {/* Market status hint */}
          {marketStatus?.analyzeIndicator && (
            <div className="text-xs text-amber-300">{marketStatus.analyzeIndicator.text}</div>
          )}

          {analyzing && (
            <p className="text-center text-[11px] text-dark-500">
              Your AI is fetching live data and analyzing. This may take a moment.
            </p>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="space-y-2">
          <div className="flex items-center gap-2.5 rounded-2xl border border-red-500/20 bg-red-500/[0.04] px-4 py-3 text-sm text-red-400">
            <AlertCircle size={15} className="shrink-0" />
            {error}
          </div>
          {error.toLowerCase().includes("api key") && (
            <p className="text-xs text-dark-500 pl-1">
              Make sure your exchange is connected in{" "}
              <button type="button" onClick={() => onNavigate?.("settings")} className="text-brand-400 hover:underline">Settings → Exchanges</button>.
            </p>
          )}
        </div>
      )}

      {/* ── Analysis Result Card ── */}
      {result && (
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5 space-y-4">
          <h2 className="section-label">
            {result.status === "executed" ? "Trade Executed"
              : result.status === "wait" ? "AI Analysis — No Trade"
              : result.status === "rejected" || result.status === "error" ? "Trade Not Executed"
              : "Analysis Result"}
          </h2>

          {result.status === "skipped" && (
            <div className="flex items-center gap-3 rounded-xl bg-yellow-500/[0.06] border border-yellow-500/15 p-4">
              <Minus size={18} className="text-yellow-400" />
              <div>
                <p className="text-sm font-medium text-yellow-400">Skipped</p>
                <p className="text-xs text-dark-400">{result.reason}</p>
              </div>
            </div>
          )}

          {(result.status === "error" || result.status === "rejected") && (
            <div className="flex items-center gap-3 rounded-xl bg-red-500/[0.04] border border-red-500/15 p-4">
              <AlertCircle size={18} className="text-red-400" />
              <div>
                <p className="text-sm font-medium text-red-400">{result.status === "rejected" ? "Trade Rejected" : "Error"}</p>
                <p className="text-xs text-dark-400">{result.reason}</p>
              </div>
            </div>
          )}

          {(result.status === "executed" || result.status === "wait" || result.decision) && (
            <div className="space-y-4">
              {result.message && <p className="text-xs md:text-sm text-dark-300">{result.message}</p>}

              {/* Signal + confidence + trend */}
              <div className="flex flex-wrap items-center gap-2.5">
                {(result.decision || result.side) === "BUY" ? (
                  <div className="flex items-center gap-2 rounded-xl bg-brand-500/10 border border-brand-500/15 px-4 py-2">
                    <TrendingUp size={16} className="text-brand-400" />
                    <span className="text-sm font-bold text-brand-400">BUY</span>
                  </div>
                ) : (result.decision || result.side) === "SELL" ? (
                  <div className="flex items-center gap-2 rounded-xl bg-red-500/10 border border-red-500/15 px-4 py-2">
                    <TrendingDown size={16} className="text-red-400" />
                    <span className="text-sm font-bold text-red-400">SELL</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 rounded-xl bg-yellow-500/10 border border-yellow-500/15 px-4 py-2">
                    <Minus size={16} className="text-yellow-400" />
                    <span className="text-sm font-bold text-yellow-400">WAIT</span>
                  </div>
                )}
                {result.confidence !== undefined && (
                  <div className="rounded-xl border border-dark-700 px-3 py-2">
                    <span className="text-[11px] text-dark-500">Confidence</span>
                    <span className="ml-2 text-sm font-bold text-white tabular-nums">{result.confidence}%</span>
                  </div>
                )}
                {result.market_trend && (
                  <div className="rounded-xl border border-dark-700 px-3 py-2">
                    <span className="text-[11px] text-dark-500">Trend</span>
                    <span className="ml-2 text-sm font-medium text-dark-200">{result.market_trend}</span>
                  </div>
                )}
              </div>

              {/* Raw data (for experienced+ users) */}
              {(traderClass === "experienced" || traderClass === "semi_institutional") && (result.rsi != null || result.macd != null) && (
                <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                  <div className="mb-3 text-xs font-semibold text-dark-400">What the analysis shows</div>
                  <div className="space-y-2 font-mono text-xs text-dark-200">
                    {result.rsi != null && <div>RSI: <span className="text-white">{result.rsi}</span></div>}
                    {result.macd != null && <div>MACD: <span className={result.macd > 0 ? "text-green-400" : "text-red-400"}>{result.macd > 0 ? "Positive crossover" : "Negative crossover"}</span></div>}
                    {result.volume_ratio != null && <div>Volume: <span className="text-white">{result.volume_ratio}x vs 30d avg</span></div>}
                    {result.sentiment_score != null && <div>Sentiment: <span className="text-white">{result.sentiment_score}</span></div>}
                    {result.days_to_earnings != null && <div>Earnings: <span className="text-white">{result.days_to_earnings} days</span></div>}
                  </div>
                </div>
              )}

              {/* Explanation toggles (Expert / Simple / Metaphor) */}
              <ExplanationToggle
                explanations={{
                  expert: result.expert ?? result.reasoning ?? "—",
                  simple: result.simple ?? result.message ?? "—",
                  metaphor: result.metaphor ?? result.message ?? "—",
                }}
              />

              {/* Entry / SL / TP grid */}
              {result.entry_price && (
                <div className="grid grid-cols-3 gap-2.5">
                  <div className="rounded-xl border border-dark-700 p-3 text-center">
                    <p className="text-[10px] uppercase tracking-wider text-dark-500 mb-1">Entry</p>
                    <p className="font-mono text-sm font-bold text-white tabular-nums">${result.entry_price.toFixed(2)}</p>
                  </div>
                  <div className="rounded-xl border border-red-500/15 p-3 text-center">
                    <p className="text-[10px] uppercase tracking-wider text-dark-500 mb-1">Stop Loss</p>
                    <p className="font-mono text-sm font-bold text-red-400 tabular-nums">${result.stop_loss?.toFixed(2)}</p>
                  </div>
                  <div className="rounded-xl border border-brand-500/15 p-3 text-center">
                    <p className="text-[10px] uppercase tracking-wider text-dark-500 mb-1">Take Profit</p>
                    <p className="font-mono text-sm font-bold text-brand-400 tabular-nums">${result.take_profit?.toFixed(2)}</p>
                  </div>
                </div>
              )}

              {/* Execute button (opens confirmation modal) */}
              {(result.decision === "BUY" || result.decision === "SELL" || result.side === "BUY" || result.side === "SELL") && (
                <button
                  type="button"
                  onClick={() => setConfirmOpen(true)}
                  className="btn-primary w-full py-3"
                >
                  {executeLabel}
                </button>
              )}

              {result.trade_id && (
                <p className="text-xs text-dark-500">
                  Trade executed successfully. View it in{" "}
                  <button onClick={() => onNavigate?.("positions")} className="text-brand-400 hover:underline">Positions</button>.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Confirmation modal */}
      <TradeConfirmModal
        isOpen={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={async () => { await handleConfirmedTrade(); }}
        trade={{ ...result, symbol }}
        isPaper={isPaper}
        traderClass={traderClass}
      />
    </div>
  );
}
