import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/router";
import {
  Crosshair, Loader2, TrendingUp, TrendingDown, Minus,
  AlertCircle, ChevronRight, Link2, RefreshCw,
} from "lucide-react";
import { tradingApi, exchangeApi, authApi } from "@/lib/api";
import CircuitBreakerAlert from "./trade/CircuitBreakerAlert";
import { useLivePrice } from "@/hooks/useLivePrice";
import { formatPrice, formatChangePct } from "@/utils/formatPrice";
import BrandPicker from "./trade/BrandPicker";
import WhatIfSimulator from "./onboarding/WhatIfSimulator";
import PriceChart from "./trade/PriceChart";

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
}

const POPULAR_SYMBOLS: Record<string, string[]> = {
  alpaca: ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "SPY", "BTC/USD"],
  binance: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"],
  oanda: ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"],
};

/** Normalise symbol for exchange (e.g. BTC → BTCUSDT for Binance) */
function normaliseSymbol(sym: string, exchange: string): string {
  const s = sym.trim().toUpperCase().replace(/\s/g, "");
  if (!s) return s;
  const ex = exchange.toLowerCase();
  if (ex === "binance" && /^BTC$/i.test(s)) return "BTCUSDT";
  if (ex === "binance" && /^ETH$/i.test(s)) return "ETHUSDT";
  if (ex === "alpaca" && /^BTC$/i.test(s)) return "BTC/USD";
  return s;
}

export default function TradePanel({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const router = useRouter();
  const [exchanges, setExchanges] = useState<ConnectedExchange[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedExchange, setSelectedExchange] = useState("");
  const [symbol, setSymbol] = useState("");
  const [traderClass, setTraderClass] = useState<string>("complete_novice");
  const [showBrandPickerForExperienced, setShowBrandPickerForExperienced] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<TradeResult | null>(null);
  const [error, setError] = useState("");
  const [tradingPaused, setTradingPaused] = useState(false);
  const [maxDailyLoss, setMaxDailyLoss] = useState(10);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [selfTaughtStart, setSelfTaughtStart] = useState<number | null>(null);

  // Live price data
  const livePrice = useLivePrice(symbol ? symbol : null);

  // Load exchanges
  useEffect(() => {
    exchangeApi.list().then((res) => {
      const data = res.data.data || [];
      setExchanges(data);
      if (data.length > 0) setSelectedExchange(data[0].exchange);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  // Load user settings for trading pause status
  useEffect(() => {
    authApi.getSettings().then((res) => {
      setTradingPaused(res.data.trading_paused || false);
      setMaxDailyLoss(res.data.max_daily_loss || 10);
      setTraderClass(res.data.trader_class || "complete_novice");
    }).catch(() => {
      // Fail silently - alert will not show if settings can't be loaded
    }).finally(() => setSettingsLoading(false));
  }, []);

  // self_taught: show "Day n of 14" track record bar at top for first 14 days
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (traderClass !== "self_taught") return;
    const key = "unitrader_self_taught_track_start_v1";
    const existing = window.localStorage.getItem(key);
    if (existing && !Number.isNaN(Number(existing))) {
      setSelfTaughtStart(Number(existing));
      return;
    }
    const now = Date.now();
    window.localStorage.setItem(key, String(now));
    setSelfTaughtStart(now);
  }, [traderClass]);

  const selfTaughtDay = useMemo(() => {
    if (traderClass !== "self_taught") return null;
    if (!selfTaughtStart) return 1;
    const ms = Date.now() - selfTaughtStart;
    const days = Math.floor(ms / (24 * 60 * 60 * 1000));
    return Math.max(1, Math.min(14, days + 1));
  }, [traderClass, selfTaughtStart]);

  const handleExecute = async () => {
    if (!symbol.trim() || !selectedExchange) return;
    setExecuting(true);
    setResult(null);
    setError("");
    try {
      const normalised = normaliseSymbol(symbol, selectedExchange);
      const res = await tradingApi.execute(normalised, selectedExchange);
      const data = res.data?.data ?? res.data;
      setResult(data);
      // Show rejection/error reasons in the error box too so they're visible
      if (data?.status === "rejected" || data?.status === "error") {
        setError(data.reason || "Trade was not executed.");
      } else {
        setError(""); // Clear on success (executed/wait)
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      const msg = typeof detail === "string"
        ? detail
        : Array.isArray(detail) && detail[0]?.msg
          ? detail[0].msg
          : err.response?.data?.message || err.message || "Trade execution failed. Please try again.";
      setError(msg);
    } finally {
      setExecuting(false);
    }
  };

  const suggestions = POPULAR_SYMBOLS[selectedExchange] || [];

  const chartSignal =
    (result?.decision || result?.side || "NONE").toUpperCase() === "BUY"
      ? "BUY"
      : (result?.decision || result?.side || "NONE").toUpperCase() === "SELL"
        ? "SELL"
        : (result?.decision || result?.side || "NONE").toUpperCase() === "WAIT"
          ? "WAIT"
          : "NONE";

  const canShowOhlcvChart =
    selectedExchange === "alpaca" &&
    !!symbol.trim() &&
    !symbol.includes("/") &&
    !symbol.includes("_");

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-dark-500">
        <Loader2 size={15} className="mr-2 animate-spin text-brand-400" /> Loading...
      </div>
    );
  }

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

  return (
    <div className="w-full space-y-5 animate-fade-in">
      <WhatIfSimulator mode="welcome_modal" />

      {traderClass === "self_taught" && selfTaughtDay !== null && selfTaughtDay <= 14 && (
        <div className="rounded-2xl border border-blue-500/15 bg-blue-500/[0.06] p-4">
          <div className="mb-2.5 flex items-center justify-between text-xs text-blue-200">
            <span className="font-semibold">Building your track record</span>
            <span className="tabular-nums font-mono">Day {selfTaughtDay} / 14</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-dark-800">
            <div
              className="h-1.5 rounded-full bg-blue-400 transition-all duration-500"
              style={{ width: `${(selfTaughtDay / 14) * 100}%` }}
            />
          </div>
        </div>
      )}
      <div>
        <h1 className="page-title">AI Trade Execution</h1>
        <p className="page-subtitle">Select an exchange and symbol for AI analysis</p>
      </div>

      {/* Circuit breaker alert */}
      {!settingsLoading && (
        <CircuitBreakerAlert
          tradingPaused={tradingPaused}
          dailyLossPct={0}
          maxDailyLossPct={maxDailyLoss}
        />
      )}

      <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
        <div className="space-y-4">
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

          {traderClass === "semi_institutional" ? (
            <BrandPicker
              exchange={selectedExchange}
              onManualSymbol={(s) => setSymbol(s.toUpperCase())}
            />
          ) : (
            <>
              <div>
                <label className="section-label mb-2">Symbol</label>
                <input
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  onKeyDown={(e) => e.key === "Enter" && !executing && handleExecute()}
                  placeholder={selectedExchange === "alpaca" ? "e.g. AAPL" : selectedExchange === "binance" ? "e.g. BTCUSDT" : "e.g. EUR_USD"}
                  className="input font-mono text-sm"
                  disabled={executing}
                />
                {traderClass === "experienced" && (
                  <button
                    type="button"
                    onClick={() => setShowBrandPickerForExperienced((v) => !v)}
                    className="mt-2 text-xs text-brand-400 hover:underline"
                  >
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

          {symbol && (
            <div className="rounded-xl bg-dark-900/50 p-3.5 border border-dark-800">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-dark-500 mb-0.5">Live Price</p>
                  <p className="text-base font-bold text-white tabular-nums">
                    {livePrice.price !== null 
                      ? formatPrice(livePrice.price, symbol)
                      : livePrice.isConnected ? "Loading..." : "Disconnected"
                    }
                  </p>
                </div>
                <div className="text-right">
                  <p className={`text-xs font-mono tabular-nums ${livePrice.bid && livePrice.ask ? 'text-dark-400' : 'text-dark-500'}`}>
                    {livePrice.bid !== null && livePrice.ask !== null
                      ? `${formatPrice(livePrice.bid, symbol)} / ${formatPrice(livePrice.ask, symbol)}`
                      : "—"
                    }
                  </p>
                  <p className="text-[11px] text-dark-500">Bid / Ask</p>
                </div>
              </div>
              <div className="mt-2.5 flex items-center justify-between text-[11px]">
                <span className={livePrice.isConnected ? 'text-brand-400' : 'text-red-400'}>
                  <span className="inline-block w-1.5 h-1.5 rounded-full mr-1 align-middle" style={{ backgroundColor: livePrice.isConnected ? '#0adb6a' : '#f87171' }} />
                  {livePrice.isConnected ? "Connected" : "Disconnected"}
                </span>
                <span className="text-dark-500 font-mono tabular-nums">
                  {livePrice.lastUpdated 
                    ? new Date(livePrice.lastUpdated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                    : "—"
                  }
                </span>
              </div>
            </div>
          )}

          {canShowOhlcvChart && (
            <div className="rounded-xl border border-dark-800 bg-dark-950/50 p-4">
              <PriceChart
                symbol={symbol}
                traderClass={traderClass as any}
                signal={chartSignal as any}
              />
            </div>
          )}

          {suggestions.length > 0 && (
            <div>
              <p className="section-label mb-2">Quick picks</p>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSymbol(s)}
                    disabled={executing}
                    className={`rounded-lg border px-2.5 py-1.5 text-xs font-mono transition-all ${
                      symbol === s
                        ? "border-brand-500/40 bg-brand-500/10 text-brand-400"
                        : "border-dark-700 text-dark-500 hover:text-dark-300 hover:border-dark-600"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <button
            onClick={handleExecute}
            disabled={!symbol.trim() || executing}
            className="btn-primary w-full py-3 disabled:opacity-50"
          >
            {executing ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <Crosshair size={15} />
                Analyze & Trade
              </>
            )}
          </button>

          {executing && (
            <p className="text-center text-[11px] text-dark-500">
              Your AI is fetching live data and analyzing. This may take a moment.
            </p>
          )}
        </div>
      </div>

      {error && (
        <div className="space-y-2">
          <div className="flex items-center gap-2.5 rounded-2xl border border-red-500/20 bg-red-500/[0.04] px-4 py-3 text-sm text-red-400">
            <AlertCircle size={15} className="shrink-0" />
            {error}
          </div>
          {error.toLowerCase().includes("api key") && (
            <p className="text-xs text-dark-500 pl-1">
              Make sure your exchange is connected in{" "}
              <button type="button" onClick={() => onNavigate?.("settings")} className="text-brand-400 hover:underline">
                Settings → Exchanges
              </button>
              .
            </p>
          )}
        </div>
      )}

      {result && (
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
          <h2 className="section-label mb-4">
            {result.status === "executed"
              ? "Trade Executed"
              : result.status === "wait"
                ? "AI Analysis — No Trade"
                : result.status === "rejected" || result.status === "error"
                  ? "Trade Not Executed"
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
                <p className="text-sm font-medium text-red-400">
                  {result.status === "rejected" ? "Trade Rejected" : "Error"}
                </p>
                <p className="text-xs text-dark-400">{result.reason}</p>
              </div>
            </div>
          )}

          {(result.status === "executed" || result.status === "wait" || result.decision) && (
            <div className="space-y-4">
              {result.message && (
                <p className="text-xs md:text-sm text-dark-300">{result.message}</p>
              )}
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

              {result.reasoning && (
                <div className="rounded-xl bg-dark-900/50 border border-dark-800/50 p-4">
                  <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-dark-500">AI Reasoning</p>
                  <p className="text-sm leading-relaxed text-dark-300">{result.reasoning}</p>
                </div>
              )}

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

              {result.trade_id && (
                <p className="text-xs text-dark-500">
                  Trade executed successfully. View it in{" "}
                  <button onClick={() => onNavigate?.("positions")} className="text-brand-400 hover:underline">
                    Positions
                  </button>
                  .
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
