import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useRouter } from "next/router";
import {
  Loader2, TrendingUp, TrendingDown, Minus,
  AlertCircle, ChevronRight, Link2, Zap, Bot,
  ChevronDown, ChevronUp,
} from "lucide-react";
import { api, tradingApi, exchangeApi, authApi } from "@/lib/api";
import CircuitBreakerAlert from "./trade/CircuitBreakerAlert";
import ExplanationToggle from "./trade/ExplanationToggle";
import TradeConfirmModal from "./trade/TradeConfirmModal";
import AIActivityStream from "./trade/AIActivityStream";
import AIPicksPanel from "./trade/AIPicksPanel";
import { useLivePrice } from "@/hooks/useLivePrice";
import { formatPrice } from "@/utils/formatPrice";
import WhatIfSimulator from "./onboarding/WhatIfSimulator";

// ─── Types ────────────────────────────────────────────────────────────────────

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

interface ConnectedExchange { exchange: string; connected_at: string | null; }

interface TradeResult {
  status: string; reason?: string; decision?: string; confidence?: number;
  reasoning?: string; entry_price?: number; stop_loss?: number; take_profit?: number;
  side?: string; symbol?: string; quantity?: number; trade_id?: string;
  market_trend?: string; message?: string; expert?: string; simple?: string;
  metaphor?: string; rsi?: number; macd?: number; volume_ratio?: number;
  sentiment_score?: number; days_to_earnings?: number;
}

type TrustLadder = {
  stage: 1 | 2 | 3 | 4; paperEnabled: boolean; canAdvance: boolean;
  daysAtStage: number; paperTradesCount: number; maxAmountGbp?: number;
};

// ─── Types for dynamic market data ───────────────────────────────────────────

interface MarketTopItem {
  symbol: string;
  label: string;
  decision: string;
  confidence: number;
  reasoning: string;
  entry_price: number | null;
  price_change_pct: number;
  stop_loss: number | null;
  take_profit: number | null;
  market_condition: string;
  key_factors: string[];
}

interface SymbolSearchResult {
  symbol: string;
  label: string;
  exchange: string;
}

function normaliseSymbol(sym: string, exchange: string): string {
  const s = sym.trim().toUpperCase().replace(/\s/g, "");
  const ex = exchange.toLowerCase();
  if (ex === "binance" && /^BTC$/i.test(s)) return "BTCUSDT";
  if (ex === "alpaca"  && /^BTC$/i.test(s)) return "BTC/USD";
  return s;
}

// ─── Live price tile ──────────────────────────────────────────────────────────

function WatchlistTile({ symbol, label, exchange, lastDecision, priceChangePct }: {
  symbol: string;
  label: string;
  exchange: string;
  lastDecision?: { side: string; confidence?: number; created_at?: string };
  priceChangePct?: number;
}) {
  const live = useLivePrice(symbol);
  const name = label || symbol;

  const decisionColor =
    lastDecision?.side?.toUpperCase() === "BUY"  ? "text-brand-400" :
    lastDecision?.side?.toUpperCase() === "SELL" ? "text-red-400"   : "text-yellow-400";

  const decisionLabel =
    lastDecision?.side?.toUpperCase() === "BUY"  ? "BUY"  :
    lastDecision?.side?.toUpperCase() === "SELL" ? "SELL" :
    lastDecision ? "WAIT" : null;

  const changeColor =
    priceChangePct !== undefined && priceChangePct > 0 ? "text-brand-400" :
    priceChangePct !== undefined && priceChangePct < 0 ? "text-red-400" : "text-dark-500";

  return (
    <div className="flex items-center justify-between rounded-xl border border-dark-800 bg-dark-900/40 px-4 py-3 gap-3">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-white truncate">{name}</p>
        <div className="flex items-center gap-2">
          <p className="font-mono text-[11px] text-dark-500">{symbol}</p>
          {priceChangePct !== undefined && (
            <span className={`text-[10px] font-semibold tabular-nums ${changeColor}`}>
              {priceChangePct >= 0 ? "+" : ""}{priceChangePct.toFixed(2)}%
            </span>
          )}
        </div>
      </div>

      <div className="text-right shrink-0">
        <p className="font-mono text-sm font-bold text-white tabular-nums">
          {live.price !== null ? formatPrice(live.price, symbol) : "—"}
        </p>
        <p className={`text-[11px] font-semibold ${live.isConnected ? "text-dark-400" : "text-dark-600"}`}>
          {live.isConnected ? (
            <span className="flex items-center justify-end gap-1">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand-400 animate-pulse" />
              Live
            </span>
          ) : "Connecting…"}
        </p>
      </div>

      {decisionLabel && (
        <div className={`shrink-0 rounded-lg border px-2 py-1 text-[11px] font-bold ${decisionColor} border-current/30 bg-current/5`}>
          {decisionLabel}
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function TradePanel({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const router = useRouter();

  const [exchanges, setExchanges]           = useState<ConnectedExchange[]>([]);
  const [loading, setLoading]               = useState(true);
  const [selectedExchange, setSelectedExchange] = useState("");
  const [traderClass, setTraderClass]       = useState<TraderClass>("complete_novice");
  const [trust, setTrust]                   = useState<TrustLadder | null>(null);
  const [tradingPaused, setTradingPaused]   = useState(false);
  const [maxDailyLoss, setMaxDailyLoss]     = useState(10);
  const [settingsLoading, setSettingsLoading] = useState(true);

  // Trade mode: "auto" = full autopilot, "picks" = AI recommends, user decides
  const [tradeMode, setTradeMode]           = useState<"auto" | "picks">("auto");
  const [modeSaving, setModeSaving]         = useState(false);

  // Recent trades for wiring watchlist decision badges
  const [recentTrades, setRecentTrades]     = useState<any[]>([]);


  // On-demand analysis (collapsed by default — user doesn't need this)
  const [showOnDemand, setShowOnDemand]     = useState(false);
  const [odSymbol, setOdSymbol]             = useState("");
  const [odAnalyzing, setOdAnalyzing]       = useState(false);
  const [odResult, setOdResult]             = useState<TradeResult | null>(null);
  const [odError, setOdError]               = useState("");
  const [confirmOpen, setConfirmOpen]       = useState(false);
  const [toast, setToast]                   = useState<string | null>(null);
  const [isMobile, setIsMobile]             = useState(false);
  const [showLiveFeed, setShowLiveFeed]     = useState(false);
  const [showWatchlist, setShowWatchlist]   = useState(true);

  // Tier-1: instant symbol list from /exchange-assets — shows while AI loads
  const [tier1Assets, setTier1Assets]       = useState<Array<{symbol: string; label: string}> | null>(null);
  const [tier1Loading, setTier1Loading]     = useState(false);

  // Tier-2: AI-ranked top picks — enhances tier-1 tiles in the background
  const [marketTop, setMarketTop]           = useState<MarketTopItem[]>([]);
  const [marketTopLoading, setMarketTopLoading] = useState(false);
  const [marketTopAge, setMarketTopAge]     = useState<number | null>(null);

  // Symbol search autocomplete state
  const [searchQuery, setSearchQuery]       = useState("");
  const [searchResults, setSearchResults]   = useState<SymbolSearchResult[]>([]);
  const [searchLoading, setSearchLoading]   = useState(false);
  const [searchOpen, setSearchOpen]         = useState(false);
  const searchRef                           = useRef<HTMLDivElement>(null);
  const [symbolMappingNote, setSymbolMappingNote] = useState<string | null>(null);

  const isPaper = useMemo(() => {
    if (!trust) return traderClass === "complete_novice" || traderClass === "curious_saver";
    if (traderClass === "complete_novice" || traderClass === "curious_saver") return trust.stage <= 2;
    return false;
  }, [trust, traderClass]);

  // Build last-decision lookup from history for watchlist badges
  const lastDecisionBySymbol = useMemo(() => {
    const map: Record<string, { side: string; confidence?: number; created_at?: string }> = {};
    for (const t of recentTrades) {
      if (t.symbol && !map[t.symbol]) {
        map[t.symbol] = { side: t.side, confidence: t.claude_confidence, created_at: t.created_at };
      }
    }
    return map;
  }, [recentTrades]);

  // ── Fetch tier-1 instant symbol list (no AI) ──
  const fetchTier1Assets = useCallback(async (exchange: string) => {
    if (!exchange) return;
    setTier1Loading(true);
    try {
      const res = await api.get("/api/trading/exchange-assets", {
        params: { exchange, limit: 8 },
      });
      setTier1Assets(res.data?.data || []);
    } catch {
      setTier1Assets([]);
    } finally {
      setTier1Loading(false);
    }
  }, []);

  // ── Fetch dynamic market top (AI-enhanced tier-2) ──
  const fetchMarketTop = useCallback(async (exchange: string, forceRefresh = false) => {
    if (!exchange) return;
    setMarketTopLoading(true);
    try {
      const res = await api.get("/api/trading/market-top", {
        params: { exchange, limit: 5, refresh: forceRefresh },
      });
      setMarketTop(res.data?.data || []);
      setMarketTopAge(res.data?.age_minutes ?? null);
    } catch {
      // Keep tier-1 results on error
    } finally {
      setMarketTopLoading(false);
    }
  }, []);

  // ── Debounced symbol search ──
  const searchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSearchChange = useCallback((q: string) => {
    setSearchQuery(q);
    if (!q.trim()) {
      setSearchResults([]);
      setSearchOpen(false);
      return;
    }
    if (searchDebounce.current) clearTimeout(searchDebounce.current);
    searchDebounce.current = setTimeout(async () => {
      setSearchLoading(true);
      try {
        const res = await api.get("/api/trading/symbol-search", {
          params: { q, exchange: selectedExchange, limit: 8 },
        });
        setSearchResults(res.data?.data || []);
        setSearchOpen(true);
      } catch {
        setSearchResults([]);
      } finally {
        setSearchLoading(false);
      }
    }, 300);
  }, [selectedExchange]);

  // Save trade mode to backend
  const saveTradeMode = async (mode: "auto" | "picks") => {
    setModeSaving(true);
    try {
      await api.patch("/api/auth/settings", { trade_mode: mode });
      setTradeMode(mode);
    } catch {
      // revert on failure — user still sees the old mode
    } finally {
      setModeSaving(false);
    }
  };

  // ── Load exchanges ──
  useEffect(() => {
    exchangeApi.list()
      .then((res) => {
        const data = res.data.data || [];
        setExchanges(data);
        if (data.length > 0) setSelectedExchange(data[0].exchange);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // ── When exchange changes: load tier-1 immediately, AI tier-2 in background ──
  useEffect(() => {
    if (!selectedExchange) return;
    setTier1Assets(null);
    setMarketTop([]);
    fetchTier1Assets(selectedExchange);
    fetchMarketTop(selectedExchange);
  }, [selectedExchange, fetchTier1Assets, fetchMarketTop]);

  // ── Close search dropdown on outside click ──
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setSearchOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ── Load settings + trust ──
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
        const rawMode = sRes.data.trade_mode || "auto";
        setTradeMode(rawMode === "auto" ? "auto" : "picks");
        setTrust(tRes.data?.data ?? tRes.data);
      } catch {
        if (!mounted) return;
        setTrust({ stage: 1, paperEnabled: true, canAdvance: false, daysAtStage: 1, paperTradesCount: 0 });
      } finally {
        if (mounted) setSettingsLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, []);


  // ── Load recent trade history to wire watchlist decision badges ──
  useEffect(() => {
    api.get("/api/trading/history", { params: { limit: 30 } })
      .then((res) => {
        const trades = res.data?.data?.trades || res.data?.trades || [];
        setRecentTrades(trades);
      })
      .catch(() => {});
  }, []);

  // ── Toast auto-dismiss ──
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    const onResize = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      setShowLiveFeed(!mobile);
      setShowWatchlist(true);
    };
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // ── On-demand analysis ──
  const handleOnDemandAnalyze = async () => {
    if (!odSymbol.trim() || !selectedExchange) return;
    setOdAnalyzing(true);
    setOdResult(null);
    setOdError("");
    setSymbolMappingNote(null);

    // If user typed free text without picking from the dropdown, auto-resolve to top result
    let resolvedSymbol = odSymbol.trim();
    if (searchQuery.trim() && searchResults.length > 0) {
      resolvedSymbol = searchResults[0].symbol;
      setOdSymbol(resolvedSymbol);
      setSearchQuery("");
      setSearchOpen(false);
      setSymbolMappingNote(`Using symbol: ${resolvedSymbol}`);
    }

    try {
      const sym = normaliseSymbol(resolvedSymbol, selectedExchange);
      // Analysis only — no order placed here. User confirms trade in the modal.
      const res = await tradingApi.analyze(sym, selectedExchange);
      const data = res.data?.data ?? res.data;
      setOdResult(data);
      if (data?.status === "rejected" || data?.status === "error") {
        setOdError(data.reason || "Analysis failed.");
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setOdError(
        typeof detail === "string" ? detail
          : err.response?.data?.message || err.message || "Analysis failed."
      );
    } finally {
      setOdAnalyzing(false);
    }
  };

  const handleConfirmedTrade = async () => {
    const sym = normaliseSymbol(odSymbol.trim(), selectedExchange);
    if (!sym) throw new Error("Missing symbol");
    const res = await tradingApi.execute(sym, selectedExchange);
    setToast("Trade submitted");
    return res.data?.data ?? res.data;
  };

  // Top market picks used as quick-select chips in on-demand panel
  // Use AI-ranked picks if loaded, otherwise fall back to instant tier-1 list
  const suggestions = (
    marketTop.length > 0
      ? marketTop
      : (tier1Assets ?? []).map((x) => ({ ...x, decision: "WAIT" as const }))
  ).slice(0, 8);

  // ── Loading ──
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-dark-500">
        <Loader2 size={15} className="mr-2 animate-spin text-brand-400" /> Loading...
      </div>
    );
  }

  // ── No exchange connected ──
  if (exchanges.length === 0) {
    return (
      <div className="mx-auto max-w-md space-y-6 py-16 text-center animate-fade-in">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-dark-800 bg-[#0d1117]">
          <Link2 size={28} className="text-dark-500" />
        </div>
        <h1 className="page-title">Connect an Exchange First</h1>
        <p className="text-sm text-dark-400 leading-relaxed">
          Connect your exchange API keys and your AI will start trading automatically on your behalf — no manual work needed.
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

      {/* Toast */}
      {toast && (
        <div className="fixed right-4 top-4 z-50 rounded-xl border border-dark-800 bg-dark-950 px-4 py-3 text-sm text-white shadow-xl">
          {toast}
        </div>
      )}

      {/* Circuit breaker */}
      {!settingsLoading && (
        <CircuitBreakerAlert tradingPaused={tradingPaused} dailyLossPct={0} maxDailyLossPct={maxDailyLoss} />
      )}

      {/* ── Hero: Autopilot Status + Mode Toggle ── */}
      <div className="rounded-2xl border border-brand-500/25 bg-brand-500/[0.04] p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-500/10">
              <Bot size={20} className="text-brand-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="relative flex h-2.5 w-2.5 shrink-0">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-50" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-400" />
                </span>
                <p className="text-sm font-bold text-white">AI Trader Active</p>
              </div>
              <p className="text-xs text-dark-400 mt-0.5">Scanning 40–80 assets · Best picks shown · Every 5 minutes</p>
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

        {/* Mode toggle */}
        <div className="mt-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-dark-600">
            Trading mode
          </p>
          <div className="flex rounded-xl border border-dark-800 bg-dark-950 p-1 gap-1">
            <button
              type="button"
              disabled={modeSaving}
              onClick={() => saveTradeMode("auto")}
              className={`flex-1 rounded-lg py-2 text-xs font-semibold transition-all ${
                tradeMode === "auto"
                  ? "bg-brand-500/15 border border-brand-500/30 text-brand-300"
                  : "text-dark-500 hover:text-dark-300"
              }`}
            >
              Full Autopilot
              <span className="ml-1.5 hidden sm:inline text-[11px] font-normal opacity-70">AI trades automatically</span>
            </button>
            <button
              type="button"
              disabled={modeSaving}
              onClick={() => saveTradeMode("picks")}
              className={`flex-1 rounded-lg py-2 text-xs font-semibold transition-all ${
                tradeMode === "picks"
                  ? "bg-brand-500/15 border border-brand-500/30 text-brand-300"
                  : "text-dark-500 hover:text-dark-300"
              }`}
            >
              AI Picks
              <span className="ml-1.5 hidden sm:inline text-[11px] font-normal opacity-70">You review & tap to trade</span>
            </button>
          </div>
          <p className="mt-2 text-[11px] text-dark-500 leading-relaxed">
            {tradeMode === "auto"
              ? "Your AI scans the market every 5 minutes and places trades automatically. No action needed from you."
              : "Your AI finds the best opportunities right now. You review them and tap to trade — you stay in control."}
          </p>
        </div>

        {/* Exchange tabs (multiple exchanges) */}
        {exchanges.length > 1 && (
          <div className="mt-4 flex gap-2 flex-wrap">
            {exchanges.map((ex) => (
              <button
                key={ex.exchange}
                onClick={() => setSelectedExchange(ex.exchange)}
                className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-all ${
                  selectedExchange === ex.exchange
                    ? "border-brand-500/50 bg-brand-500/10 text-brand-400"
                    : "border-dark-700 text-dark-500 hover:border-dark-600 hover:text-dark-300"
                }`}
              >
                {ex.exchange.charAt(0).toUpperCase() + ex.exchange.slice(1)}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── AI Live Feed ── */}
      {isMobile ? (
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117]">
          <button
            type="button"
            onClick={() => setShowLiveFeed((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-left"
          >
            <span className="text-sm font-semibold text-white">AI Live Feed</span>
            {showLiveFeed ? <ChevronUp size={15} className="text-dark-500" /> : <ChevronDown size={15} className="text-dark-500" />}
          </button>
          {showLiveFeed && <div className="border-t border-dark-800 p-3"><AIActivityStream /></div>}
        </div>
      ) : (
        <AIActivityStream />
      )}

      {/* ── AI Picks mode: recommendation cards ── */}
      {tradeMode === "picks" ? (
        <AIPicksPanel
          exchange={selectedExchange}
          isPaper={isPaper}
          traderClass={traderClass}
        />
      ) : (
        /* ── Autopilot mode: dynamic AI top picks ── */
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117]">
          <button
            type="button"
            onClick={() => setShowWatchlist((v) => !v)}
            className="flex w-full items-center justify-between px-5 py-4 text-left"
          >
            <div>
              <p className="text-sm font-semibold text-white">
                {marketTop.length > 0 ? "Today's AI Top Picks" : "Live Assets"}
              </p>
              <p className="text-xs text-dark-500 mt-0.5">
                {marketTop.length > 0
                  ? marketTopAge !== null
                    ? `Best of 40–80 assets · Refreshed ${marketTopAge}m ago`
                    : "Best of 40–80 assets · Refreshing now…"
                  : marketTopLoading
                    ? "AI scanning 40–80 assets for best picks…"
                    : `${selectedExchange.charAt(0).toUpperCase() + selectedExchange.slice(1)} · live prices`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {marketTopLoading && <Loader2 size={13} className="animate-spin text-dark-500" />}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); fetchMarketTop(selectedExchange, true); }}
                className="rounded-lg border border-dark-700 px-2 py-1 text-[10px] font-semibold text-dark-500 hover:text-dark-300 hover:border-dark-600 transition-all"
                title="Force refresh AI picks"
              >
                Refresh
              </button>
              {showWatchlist ? <ChevronUp size={15} className="text-dark-500" /> : <ChevronDown size={15} className="text-dark-500" />}
            </div>
          </button>
          {showWatchlist && (
            <div className="border-t border-dark-800 p-5">
              {(() => {
                // Show tier-1 immediately; enhance with AI tier-2 once ready
                const displayItems = marketTop.length > 0
                  ? marketTop
                  : (tier1Assets ?? []);
                const isAiEnhanced = marketTop.length > 0;

                if (tier1Loading && displayItems.length === 0) {
                  return (
                    <div className="flex items-center gap-2 text-sm text-dark-500 py-4 justify-center">
                      <Loader2 size={14} className="animate-spin" />
                      Loading assets…
                    </div>
                  );
                }
                if (displayItems.length === 0) {
                  return <p className="text-xs text-dark-500 text-center py-4">No picks yet — tap Refresh to scan now.</p>;
                }
                return (
                  <>
                    {!isAiEnhanced && marketTopLoading && (
                      <div className="mb-3 flex items-center gap-1.5 text-[11px] text-dark-500">
                        <Loader2 size={10} className="animate-spin" />
                        AI analysing market — picks will update shortly
                      </div>
                    )}
                    {isAiEnhanced && (
                      <div className="mb-3 flex items-center gap-1.5 text-[11px] text-brand-400">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand-400" />
                        AI-ranked · best opportunities right now
                      </div>
                    )}
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {displayItems.map((item) => (
                        <WatchlistTile
                          key={item.symbol}
                          symbol={item.symbol}
                          label={item.label}
                          exchange={selectedExchange}
                          priceChangePct={'price_change_pct' in item ? (item as MarketTopItem).price_change_pct : undefined}
                          lastDecision={
                            lastDecisionBySymbol[item.symbol] ??
                            ('decision' in item && (item as MarketTopItem).decision !== "WAIT"
                              ? { side: (item as MarketTopItem).decision }
                              : undefined)
                          }
                        />
                      ))}
                    </div>
                  </>
                );
              })()}
            </div>
          )}
          {!showWatchlist && (
            <div className="px-5 pb-4 text-[11px] text-dark-600">
              Collapsed to keep your screen focused. Tap to expand.
            </div>
          )}
        </div>
      )}


      {/* ── On-demand Analysis (collapsed — advanced users only) ── */}
      <div className="rounded-2xl border border-dark-800 bg-[#0d1117]">
        <button
          type="button"
          onClick={() => setShowOnDemand((v) => !v)}
          className="flex w-full items-center justify-between px-5 py-4 text-left"
        >
          <div className="flex items-center gap-2">
            <Zap size={14} className="text-dark-500" />
            <span className="text-sm font-semibold text-dark-300">Instant on-demand analysis</span>
            <span className="rounded-full border border-dark-700 bg-dark-900 px-2 py-0.5 text-[10px] font-medium text-dark-500">
              Optional
            </span>
          </div>
          {showOnDemand ? <ChevronUp size={15} className="text-dark-500" /> : <ChevronDown size={15} className="text-dark-500" />}
        </button>

        {showOnDemand && (
          <div className="border-t border-dark-800 px-5 pb-5 pt-4 space-y-4">
            <p className="text-xs text-dark-500 leading-relaxed">
              Request an instant AI analysis of any asset. Your AI normally does this automatically every 5 minutes — use this to check a specific symbol right now.
            </p>

            {/* Exchange selector */}
            {exchanges.length > 1 && (
              <div className="flex gap-2 flex-wrap">
                {exchanges.map((ex) => (
                  <button
                    key={ex.exchange}
                    onClick={() => setSelectedExchange(ex.exchange)}
                    className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition-all ${
                      selectedExchange === ex.exchange
                        ? "border-brand-500/50 bg-brand-500/10 text-brand-400"
                        : "border-dark-700 text-dark-500 hover:border-dark-600 hover:text-dark-300"
                    }`}
                  >
                    {ex.exchange.charAt(0).toUpperCase() + ex.exchange.slice(1)}
                  </button>
                ))}
              </div>
            )}

            {/* Symbol quick-select — AI top picks as chips */}
            <div>
              <p className="section-label mb-2">
                AI top picks today
                {marketTopLoading && <Loader2 size={11} className="inline ml-1 animate-spin text-dark-600" />}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.map((item) => (
                  <button
                    key={item.symbol}
                    onClick={() => { setOdSymbol(item.symbol); setSearchQuery(""); setSearchOpen(false); }}
                    disabled={odAnalyzing}
                    className={`rounded-lg border px-2.5 py-1.5 text-xs font-mono transition-all ${
                      odSymbol === item.symbol
                        ? "border-brand-500/40 bg-brand-500/10 text-brand-400"
                        : "border-dark-700 text-dark-500 hover:text-dark-300 hover:border-dark-600"
                    }`}
                    title={item.label}
                  >
                    {item.symbol}
                    {item.decision !== "WAIT" && (
                      <span className={`ml-1 text-[9px] font-bold ${item.decision === "BUY" ? "text-brand-400" : "text-red-400"}`}>
                        {item.decision}
                      </span>
                    )}
                  </button>
                ))}
                {suggestions.length === 0 && !marketTopLoading && (
                  <span className="text-[11px] text-dark-600">Loading picks…</span>
                )}
              </div>

              {/* Search with autocomplete */}
              <div className="relative mt-2" ref={searchRef}>
                <div className="relative">
                  <input
                    value={searchQuery || odSymbol}
                    onChange={(e) => {
                      const v = e.target.value.toUpperCase();
                      setOdSymbol(v);
                      setSymbolMappingNote(null);
                      handleSearchChange(v);
                    }}
                    onFocus={() => { if (searchResults.length > 0) setSearchOpen(true); }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !odAnalyzing) { setSearchOpen(false); handleOnDemandAnalyze(); }
                      if (e.key === "Escape") setSearchOpen(false);
                    }}
                    placeholder={selectedExchange === "alpaca" ? "Search e.g. Apple, AAPL, Tesla…" : selectedExchange === "binance" ? "Search e.g. Bitcoin, ETHUSDT…" : "Search e.g. Euro, EUR_USD…"}
                    className="input font-mono text-sm pr-8"
                    disabled={odAnalyzing}
                    autoComplete="off"
                  />
                  {searchLoading && (
                    <Loader2 size={13} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-dark-500" />
                  )}
                </div>
                {searchOpen && searchResults.length > 0 && (
                  <div className="absolute left-0 right-0 top-full z-20 mt-1 rounded-xl border border-dark-800 bg-dark-950 shadow-2xl overflow-hidden">
                    {searchResults.map((r) => (
                      <button
                        key={r.symbol}
                        type="button"
                        className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-dark-900 transition-colors"
                        onMouseDown={() => {
                          setOdSymbol(r.symbol);
                          setSearchQuery("");
                          setSearchOpen(false);
                        }}
                      >
                        <span className="font-mono text-xs font-bold text-white w-24 shrink-0">{r.symbol}</span>
                        <span className="text-xs text-dark-400 truncate">{r.label}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Symbol mapping note — shown when free text was auto-resolved to a ticker */}
            {symbolMappingNote && (
              <p className="text-[11px] text-brand-400 flex items-center gap-1.5">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand-400" />
                {symbolMappingNote}
              </p>
            )}

            {/* Analyse button */}
            <button
              onClick={handleOnDemandAnalyze}
              disabled={!odSymbol.trim() || odAnalyzing}
              className="btn-primary w-full py-3 disabled:opacity-50"
            >
              {odAnalyzing
                ? <><Loader2 size={15} className="animate-spin" /> Analysing...</>
                : <><Zap size={15} /> Run instant analysis</>}
            </button>

            {/* Error */}
            {odError && (
              <div className="flex items-center gap-2.5 rounded-2xl border border-red-500/20 bg-red-500/[0.04] px-4 py-3 text-sm text-red-400">
                <AlertCircle size={15} className="shrink-0" />
                {odError}
              </div>
            )}

            {/* Result */}
            {odResult && !odError && (
              <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5 space-y-4">
                <h2 className="section-label">
                  {odResult.status === "executed" ? "Trade Executed"
                    : odResult.status === "wait"   ? "AI Decision — No Trade"
                    : "Analysis Result"}
                </h2>

                {(odResult.status === "executed" || odResult.status === "wait" || odResult.decision) && (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center gap-2.5">
                      {(odResult.decision || odResult.side) === "BUY" ? (
                        <div className="flex items-center gap-2 rounded-xl bg-brand-500/10 border border-brand-500/15 px-4 py-2">
                          <TrendingUp size={16} className="text-brand-400" />
                          <span className="text-sm font-bold text-brand-400">BUY</span>
                        </div>
                      ) : (odResult.decision || odResult.side) === "SELL" ? (
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
                      {odResult.confidence !== undefined && (
                        <div className="rounded-xl border border-dark-700 px-3 py-2">
                          <span className="text-[11px] text-dark-500">Confidence</span>
                          <span className="ml-2 text-sm font-bold text-white tabular-nums">{odResult.confidence}%</span>
                        </div>
                      )}
                    </div>

                    <ExplanationToggle
                      explanations={{
                        expert:   odResult.expert   ?? odResult.reasoning ?? "—",
                        simple:   odResult.simple   ?? odResult.message   ?? "—",
                        metaphor: odResult.metaphor ?? odResult.message   ?? "—",
                      }}
                    />

                    {odResult.entry_price && (
                      <div className="grid grid-cols-3 gap-2.5">
                        <div className="rounded-xl border border-dark-700 p-3 text-center">
                          <p className="text-[10px] uppercase tracking-wider text-dark-500 mb-1">Entry</p>
                          <p className="font-mono text-sm font-bold text-white tabular-nums">${odResult.entry_price.toFixed(2)}</p>
                        </div>
                        <div className="rounded-xl border border-red-500/15 p-3 text-center">
                          <p className="text-[10px] uppercase tracking-wider text-dark-500 mb-1">Stop Loss</p>
                          <p className="font-mono text-sm font-bold text-red-400 tabular-nums">${odResult.stop_loss?.toFixed(2)}</p>
                        </div>
                        <div className="rounded-xl border border-brand-500/15 p-3 text-center">
                          <p className="text-[10px] uppercase tracking-wider text-dark-500 mb-1">Take Profit</p>
                          <p className="font-mono text-sm font-bold text-brand-400 tabular-nums">${odResult.take_profit?.toFixed(2)}</p>
                        </div>
                      </div>
                    )}

                    {(odResult.decision === "BUY" || odResult.decision === "SELL" ||
                      odResult.side === "BUY"    || odResult.side === "SELL") && (
                      <button
                        type="button"
                        onClick={() => setConfirmOpen(true)}
                        className="btn-primary w-full py-3"
                      >
                        {isPaper ? "Confirm practice trade" : "Execute trade"}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Confirmation modal */}
      <TradeConfirmModal
        isOpen={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={async () => { await handleConfirmedTrade(); }}
        trade={{ ...odResult, symbol: odSymbol }}
        isPaper={isPaper}
        traderClass={traderClass}
      />
    </div>
  );
}
