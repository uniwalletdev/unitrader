import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import {
  Crosshair, Loader2, TrendingUp, TrendingDown, Minus,
  AlertCircle, ChevronRight, Link2, RefreshCw,
} from "lucide-react";
import { tradingApi, exchangeApi } from "@/lib/api";

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
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<TradeResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    exchangeApi.list().then((res) => {
      const data = res.data.data || [];
      setExchanges(data);
      if (data.length > 0) setSelectedExchange(data[0].exchange);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-dark-500">
        <Loader2 size={16} className="mr-2 animate-spin" /> Loading...
      </div>
    );
  }

  if (exchanges.length === 0) {
    return (
      <div className="mx-auto max-w-md space-y-6 py-16 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-dark-900">
          <Link2 size={28} className="text-dark-500" />
        </div>
        <h1 className="text-base md:text-xl font-bold text-white">Connect an Exchange First</h1>
        <p className="text-xs md:text-sm text-dark-400">
          To start trading, connect your exchange API keys. Your AI will analyze
          markets and execute trades on your behalf.
        </p>
        <button onClick={() => router.push("/connect-exchange")} className="btn-primary text-xs md:text-sm py-2 md:py-3 w-full md:w-auto">
          Connect Exchange <ChevronRight size={14} />
        </button>
      </div>
    );
  }

  return (
    <div className="w-full space-y-4 md:space-y-6">
      <div className="flex items-center gap-2">
        <Crosshair size={16} className="md:size-[18px] text-brand-400" />
        <h1 className="text-base md:text-xl font-bold text-white">AI Trade Execution</h1>
      </div>

      <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-4 md:p-6">
        <div className="space-y-4">
          {/* Exchange selector */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-dark-400">Exchange</label>
            <div className="flex gap-2 flex-wrap">
              {exchanges.map((ex) => (
                <button
                  key={ex.exchange}
                  onClick={() => { setSelectedExchange(ex.exchange); setSymbol(""); setResult(null); }}
                  className={`rounded-lg border px-3 md:px-4 py-1.5 md:py-2 text-xs md:text-sm font-medium transition touch-target ${
                    selectedExchange === ex.exchange
                      ? "border-brand-500 bg-brand-500/10 text-brand-400"
                      : "border-dark-700 text-dark-400 hover:border-dark-600"
                  }`}
                >
                  {ex.exchange.charAt(0).toUpperCase() + ex.exchange.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Symbol input */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-dark-400">Symbol</label>
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && !executing && handleExecute()}
              placeholder={selectedExchange === "alpaca" ? "e.g. AAPL" : selectedExchange === "binance" ? "e.g. BTCUSDT" : "e.g. EUR_USD"}
              className="input font-mono text-xs md:text-sm"
              disabled={executing}
            />
          </div>

          {/* Quick picks */}
          {suggestions.length > 0 && (
            <div>
              <p className="mb-1.5 text-xs text-dark-500">Quick picks</p>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSymbol(s)}
                    disabled={executing}
                    className={`rounded-md border px-2 md:px-2.5 py-1 text-xs font-mono transition touch-target ${
                      symbol === s
                        ? "border-brand-500/50 bg-brand-500/10 text-brand-400"
                        : "border-dark-700 text-dark-500 hover:text-dark-300"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Execute button */}
          <button
            onClick={handleExecute}
            disabled={!symbol.trim() || executing}
            className="btn-primary w-full py-2 md:py-3 text-xs md:text-sm disabled:opacity-50"
          >
            {executing ? (
              <>
                <Loader2 size={14} className="md:size-[15px] animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <Crosshair size={14} className="md:size-[15px]" />
                Analyze & Trade
              </>
            )}
          </button>

          {executing && (
            <p className="text-center text-xs text-dark-500">
              Your AI is fetching live data and analyzing. This may take a moment.
            </p>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 rounded-lg md:rounded-xl border border-red-500/30 bg-red-500/5 px-3 md:px-4 py-2 md:py-3 text-xs md:text-sm text-red-400">
            <AlertCircle size={14} className="md:size-[15px] shrink-0" />
            {error}
          </div>
          {error.toLowerCase().includes("api key") && (
            <p className="text-xs text-dark-500">
              Make sure your exchange is connected in{" "}
              <button type="button" onClick={() => onNavigate?.("settings")} className="text-brand-400 hover:underline">
                Settings → Exchanges
              </button>
              .
            </p>
          )}
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-4 md:p-6">
          <h2 className="mb-4 text-xs md:text-sm font-semibold text-dark-200">
            {result.status === "executed"
              ? "Trade Executed"
              : result.status === "wait"
                ? "AI Analysis — No Trade"
                : result.status === "rejected" || result.status === "error"
                  ? "Trade Not Executed"
                  : "Analysis Result"}
          </h2>

          {result.status === "skipped" && (
            <div className="flex items-center gap-3 rounded-lg bg-dark-900 p-3 md:p-4">
              <Minus size={18} className="md:size-[20px] text-yellow-400" />
              <div>
                <p className="text-xs md:text-sm font-medium text-yellow-400">Skipped</p>
                <p className="text-xs text-dark-400">{result.reason}</p>
              </div>
            </div>
          )}

          {(result.status === "error" || result.status === "rejected") && (
            <div className="flex items-center gap-3 rounded-lg bg-red-500/5 p-3 md:p-4">
              <AlertCircle size={18} className="md:size-[20px] text-red-400" />
              <div>
                <p className="text-xs md:text-sm font-medium text-red-400">
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
              {/* Decision badge */}
              <div className="flex flex-wrap items-center gap-2 md:gap-3">
                {(result.decision || result.side) === "BUY" ? (
                  <div className="flex items-center gap-2 rounded-lg bg-brand-500/10 px-3 md:px-4 py-1.5 md:py-2">
                    <TrendingUp size={15} className="md:size-[18px] text-brand-400" />
                    <span className="text-xs md:text-sm font-bold text-brand-400">BUY</span>
                  </div>
                ) : (result.decision || result.side) === "SELL" ? (
                  <div className="flex items-center gap-2 rounded-lg bg-red-500/10 px-3 md:px-4 py-1.5 md:py-2">
                    <TrendingDown size={15} className="md:size-[18px] text-red-400" />
                    <span className="text-xs md:text-sm font-bold text-red-400">SELL</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 rounded-lg bg-yellow-500/10 px-3 md:px-4 py-1.5 md:py-2">
                    <Minus size={15} className="md:size-[18px] text-yellow-400" />
                    <span className="text-xs md:text-sm font-bold text-yellow-400">WAIT</span>
                  </div>
                )}

                {result.confidence !== undefined && (
                  <div className="rounded-lg border border-dark-700 px-2 md:px-3 py-1 md:py-2">
                    <span className="text-xs text-dark-500">Confidence</span>
                    <span className="ml-2 text-xs md:text-sm font-bold text-white">{result.confidence}%</span>
                  </div>
                )}

                {result.market_trend && (
                  <div className="rounded-lg border border-dark-700 px-2 md:px-3 py-1 md:py-2">
                    <span className="text-xs text-dark-500">Trend</span>
                    <span className="ml-2 text-xs md:text-sm font-medium text-dark-200">{result.market_trend}</span>
                  </div>
                )}
              </div>

              {/* Reasoning */}
              {result.reasoning && (
                <div className="rounded-lg bg-dark-900 p-3 md:p-4">
                  <p className="mb-1 text-xs font-medium text-dark-500">AI Reasoning</p>
                  <p className="text-xs md:text-sm leading-relaxed text-dark-300">{result.reasoning}</p>
                </div>
              )}

              {/* Trade details */}
              {result.entry_price && (
                <div className="grid grid-cols-3 gap-2 md:gap-3">
                  <div className="rounded-lg border border-dark-700 p-2 md:p-3 text-center">
                    <p className="text-[10px] text-dark-500">Entry</p>
                    <p className="font-mono text-xs md:text-sm font-bold text-white">${result.entry_price.toFixed(2)}</p>
                  </div>
                  <div className="rounded-lg border border-red-500/20 p-2 md:p-3 text-center">
                    <p className="text-[10px] text-dark-500">Stop Loss</p>
                    <p className="font-mono text-xs md:text-sm font-bold text-red-400">${result.stop_loss?.toFixed(2)}</p>
                  </div>
                  <div className="rounded-lg border border-brand-500/20 p-2 md:p-3 text-center">
                    <p className="text-[10px] text-dark-500">Take Profit</p>
                    <p className="font-mono text-xs md:text-sm font-bold text-brand-400">${result.take_profit?.toFixed(2)}</p>
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
