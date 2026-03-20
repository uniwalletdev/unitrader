"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2, CheckCircle } from "lucide-react";
import { api, authApi, tradingApi } from "@/lib/api";

import ApexOnboardingChat from "@/components/onboarding/ApexOnboardingChat";
import WhatIfSimulator from "@/components/onboarding/WhatIfSimulator";
import MarketStatusBar, { MarketStatus } from "@/components/trade/MarketStatusBar";
import TrustLadderBanner from "@/components/trade/TrustLadderBanner";
import BrandPicker from "@/components/trade/BrandPicker";
import PriceChart from "@/components/trade/PriceChart";
import ExplanationToggle from "@/components/trade/ExplanationToggle";
import TradeConfirmModal from "@/components/trade/TradeConfirmModal";
import CircuitBreakerAlert from "@/components/trade/CircuitBreakerAlert";
import RiskWarning from "@/components/layout/RiskWarning";
import NeverHoldBanner from "@/components/layout/NeverHoldBanner";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

type UserSettings = {
  trader_class?: TraderClass;
  explanation_level?: string;
  trading_paused?: boolean;
  max_daily_loss?: number;
  onboarding_complete?: boolean;
};

type TrustLadder = {
  stage: 1 | 2 | 3 | 4;
  paperEnabled: boolean;
  canAdvance: boolean;
  daysAtStage: number;
  paperTradesCount: number;
  maxAmountGbp?: number;
};

type AnalysisResult = any;

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function AmountInput({
  value,
  onChange,
  max,
  label = "Amount (GBP)",
}: {
  value: number;
  onChange: (v: number) => void;
  max: number;
  label?: string;
}) {
  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
      <div className="mb-2 flex items-center justify-between text-xs text-dark-400">
        <span>{label}</span>
        <span className="tabular-nums text-white">£{value}</span>
      </div>
      <input
        type="range"
        min={25}
        max={max}
        step={25}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
      <div className="mt-2 text-[11px] text-dark-500">Max: £{max}</div>
    </div>
  );
}

function RiskSection({ variant }: { variant: "plain" | "pct" }) {
  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
      <div className="text-xs font-semibold text-white">Risk</div>
      <div className="mt-2 text-xs text-dark-300">
        {variant === "plain"
          ? "Apex uses stop-loss and take-profit to manage downside and lock gains."
          : "Stop-loss and take-profit are applied as % distances from entry where possible."}
      </div>
    </div>
  );
}

function RawDataColumn({ analysis }: { analysis: AnalysisResult }) {
  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
      <div className="mb-3 text-xs font-semibold text-dark-400">What the analysis shows</div>
      <div className="space-y-2 font-mono text-xs text-dark-200">
        {analysis.rsi != null && <div>RSI: <span className="text-white">{analysis.rsi}</span></div>}
        {analysis.macd != null && (
          <div>MACD: <span className={analysis.macd > 0 ? "text-green-400" : "text-red-400"}>
            {analysis.macd > 0 ? "Positive crossover" : "Negative crossover"}
          </span></div>
        )}
        {analysis.volume_ratio != null && (
          <div>Volume: <span className="text-white">{analysis.volume_ratio}x vs 30d avg</span></div>
        )}
        {analysis.sentiment_score != null && (
          <div>Sentiment: <span className="text-white">{analysis.sentiment_score}</span></div>
        )}
        {analysis.days_to_earnings != null && (
          <div>Earnings: <span className="text-white">{analysis.days_to_earnings} days</span></div>
        )}
      </div>
      <p className="mt-3 text-[10px] leading-relaxed text-dark-500">
        Institutional-grade analysis. Previously only available to hedge funds with dedicated trading desks.
      </p>
    </div>
  );
}

function AIAnalysisCard({
  children,
  title = "AI analysis",
  analysis,
}: {
  children: React.ReactNode;
  title?: string;
  analysis: AnalysisResult | null;
}) {
  if (analysis) {
    return (
      <div className="rounded-2xl border border-dark-800 bg-dark-950 p-4 md:p-5">
        <div className="mb-3 text-sm font-semibold text-white">{title}</div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* Left — raw data */}
          <RawDataColumn analysis={analysis} />
          {/* Right — Apex verdict */}
          <div className="rounded-xl border border-brand-500/20 bg-brand-500/5 p-4">
            <div className="mb-3 text-xs font-semibold text-brand-400">Apex&apos;s verdict</div>
            <div className="mb-3 text-sm text-dark-200">
              {analysis.message || analysis.reasoning || "Analysis ready."}
            </div>
            {children}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-dark-800 bg-dark-950 p-4 md:p-5">
      <div className="mb-3 text-sm font-semibold text-white">{title}</div>
      <div className="mb-4 rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-400">
        Run analysis to see Apex&apos;s reasoning here.
      </div>
      {children}
    </div>
  );
}

function TradePage() {
  const searchParams = useSearchParams();
  const welcome = searchParams?.get("welcome") === "true";

  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [trust, setTrust] = useState<TrustLadder | null>(null);
  const [loading, setLoading] = useState(true);

  const traderClass: TraderClass = settings?.trader_class ?? "complete_novice";

  const [exchange, setExchange] = useState("alpaca");
  const [symbol, setSymbol] = useState("");
  const [amount, setAmount] = useState(100);

  const [analysis, setAnalysis] = useState<any>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [positionsCount, setPositionsCount] = useState<number | null>(null);

  const isPaper = useMemo(() => {
    // novice/saver: paper mode until trust stage advances; else live
    if (!trust) return traderClass === "complete_novice" || traderClass === "curious_saver";
    if (traderClass === "complete_novice" || traderClass === "curious_saver") return trust.stage <= 2;
    return false;
  }, [trust, traderClass]);

  const maxAmount = useMemo(() => {
    if (trust?.maxAmountGbp) return trust.maxAmountGbp;
    if (!trust) return 500;
    if (trust.stage <= 2) return 25;
    return 500;
  }, [trust]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const [sRes, tRes] = await Promise.all([
          authApi.getSettings(),
          api.get("/api/onboarding/trust-ladder"),
        ]);
        if (!mounted) return;
        setSettings(sRes.data);
        setTrust(tRes.data?.data ?? tRes.data);
      } catch {
        if (!mounted) return;
        setSettings({ trader_class: "complete_novice", trading_paused: false, max_daily_loss: 10 });
        setTrust({
          stage: 1,
          paperEnabled: true,
          canAdvance: false,
          daysAtStage: 1,
          paperTradesCount: 0,
          maxAmountGbp: 25,
        });
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  // onboarding_complete gate: only render chat full screen
  if (!loading && settings?.onboarding_complete === false) {
    return <ApexOnboardingChat />;
  }

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const handleAnalyse = async () => {
    if (!symbol.trim()) return;
    setAnalyzing(true);
    setAnalysis(null);
    try {
      const res = await api.post("/api/trading/analyze", {
        symbol: symbol.trim(),
        exchange,
        trader_class: traderClass,
      });
      setAnalysis(res.data?.data ?? res.data);
    } catch (e: any) {
      setToast(e?.response?.data?.detail || "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleConfirmedTrade = async () => {
    const sym = symbol.trim();
    if (!sym) throw new Error("Missing symbol");
    const res = await tradingApi.execute(sym, exchange);
    const data = res.data?.data ?? res.data;
    setToast("Trade submitted");
    // Refresh positions count
    try {
      const pos = await tradingApi.openPositions();
      const d = pos.data?.data ?? pos.data;
      const count =
        typeof d?.count === "number"
          ? d.count
          : Array.isArray(d?.positions)
            ? d.positions.length
            : Array.isArray(d)
              ? d.length
              : null;
      setPositionsCount(count);
    } catch {
      // ignore
    }
    return data;
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-dark-950">
        <Loader2 size={26} className="animate-spin text-brand-500" />
      </div>
    );
  }

  const showWelcomeSimulator =
    welcome &&
    (traderClass === "complete_novice" ||
      traderClass === "curious_saver" ||
      traderClass === "crypto_native" ||
      traderClass === "self_taught");

  const showSimulatorModal = showWelcomeSimulator;

  const tradingPaused = !!settings?.trading_paused;
  const maxDailyLoss = settings?.max_daily_loss ?? 10;

  // Layout selection
  const layout: "A" | "B" | "C" | "D" | "E" =
    traderClass === "complete_novice" || traderClass === "curious_saver"
      ? "A"
      : traderClass === "self_taught"
        ? "B"
        : traderClass === "experienced"
          ? "C"
          : traderClass === "semi_institutional"
            ? "D"
            : "E";

  return (
    <div className="min-h-screen bg-dark-950">
      <RiskWarning variant="bar" />
      <div className="px-4 py-6 md:px-6">
      {showSimulatorModal && <WhatIfSimulator mode="modal" />}

      {toast && (
        <div className="fixed right-4 top-4 z-50 rounded-xl border border-dark-800 bg-dark-950 px-4 py-3 text-sm text-white shadow-xl">
          {toast}
          {positionsCount !== null && (
            <div className="mt-1 text-xs text-dark-400">
              Open positions: {positionsCount}
            </div>
          )}
        </div>
      )}

      {/* Page header */}
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-lg font-bold text-white">AI Trade Execution</h1>
        <span className="rounded-full border border-brand-500/30 bg-brand-500/10 px-2 py-0.5 text-[10px] font-semibold text-brand-400">
          Same AI as hedge funds
        </span>
      </div>

      {/* Circuit breaker */}
      <div className="mb-4">
        <CircuitBreakerAlert tradingPaused={tradingPaused} dailyLossPct={0} maxDailyLossPct={maxDailyLoss} />
      </div>

      {/* Market status */}
      <div className="mb-4">
        <MarketStatusBar
          traderClass={traderClass}
          exchange={exchange}
          symbol={symbol}
          onStatusChange={setMarketStatus}
        />
      </div>

      {/* Trust ladder banner for A */}
      {layout === "A" && trust && (
        <div className="mb-4">
          <TrustLadderBanner
            stage={trust.stage}
            paperEnabled={trust.paperEnabled}
            canAdvance={trust.canAdvance}
            daysAtStage={trust.daysAtStage}
            paperTradesCount={trust.paperTradesCount}
          />
        </div>
      )}

      {/* Never-hold trust bar */}
      <div className="mb-4">
        <NeverHoldBanner />
      </div>

      {/* Layout A */}
      {layout === "A" && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-4">
            <BrandPicker
              exchange={exchange}
              onManualSymbol={(s) => setSymbol(s.toUpperCase())}
              onChangeSelectedSymbols={(syms) => setSymbol((syms[0] || "").toUpperCase())}
              selectedSymbols={symbol ? [symbol] : []}
            />
            <AmountInput value={amount} onChange={setAmount} max={maxAmount} />
            <RiskSection variant="plain" />
            <button
              type="button"
              onClick={handleAnalyse}
              disabled={analyzing || !symbol.trim()}
              title={marketStatus?.analyzeTooltip}
              className="btn-primary w-full disabled:opacity-60"
            >
              {analyzing ? "Analysing…" : "Analyse with Apex"}
            </button>
            {marketStatus?.analyzeIndicator && (
              <div className="text-xs text-amber-300">{marketStatus.analyzeIndicator.text}</div>
            )}
          </div>

          <AIAnalysisCard analysis={analysis}>
            <ExplanationToggle
              explanations={{
                expert: analysis?.expert ?? "—",
                simple: analysis?.simple ?? analysis?.message ?? "—",
                metaphor: analysis?.metaphor ?? analysis?.message ?? "—",
              }}
            />
            <button
              type="button"
              onClick={() => setConfirmOpen(true)}
              disabled={!analysis}
              className={clsx("btn-primary mt-4 w-full", !analysis && "opacity-60")}
            >
              {isPaper ? "Confirm practice trade" : "Execute trade"}
            </button>
          </AIAnalysisCard>
        </div>
      )}

      {/* Layout B — self_taught */}
      {layout === "B" && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-4">
            <BrandPicker
              exchange={exchange}
              onManualSymbol={(s) => setSymbol(s.toUpperCase())}
              onChangeSelectedSymbols={(syms) => setSymbol((syms[0] || "").toUpperCase())}
              selectedSymbols={symbol ? [symbol] : []}
            />
            {symbol && (
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <PriceChart symbol={symbol} traderClass="self_taught" signal="NONE" />
              </div>
            )}
            <AmountInput value={amount} onChange={setAmount} max={5000} label="Amount (GBP)" />
            <RiskSection variant="pct" />
            <button
              type="button"
              onClick={handleAnalyse}
              disabled={analyzing || !symbol.trim()}
              className="btn-primary w-full disabled:opacity-60"
            >
              {analyzing ? "Analysing…" : "Analyse"}
            </button>
          </div>

          <div className="space-y-4">
            <AIAnalysisCard analysis={analysis} title="AI analysis">
              <ExplanationToggle
                explanations={{
                  expert: analysis?.expert ?? "—",
                  simple: analysis?.simple ?? analysis?.message ?? "—",
                  metaphor: analysis?.metaphor ?? analysis?.message ?? "—",
                }}
              />
              <button
                type="button"
                onClick={() => setConfirmOpen(true)}
                disabled={!analysis}
                className={clsx("btn-primary mt-4 w-full", !analysis && "opacity-60")}
              >
                Execute trade
              </button>
            </AIAnalysisCard>

            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-300">
              Portfolio context (placeholder)
            </div>
          </div>
        </div>
      )}

      {/* Layout C — experienced */}
      {layout === "C" && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-4">
            <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
              <div className="text-xs font-semibold text-white">Exchange</div>
              <select
                value={exchange}
                onChange={(e) => setExchange(e.target.value)}
                className="mt-2 w-full rounded-xl border border-dark-800 bg-dark-900 px-3 py-2 text-sm text-white"
              >
                <option value="alpaca">Alpaca</option>
                <option value="binance">Binance</option>
                <option value="oanda">OANDA</option>
              </select>
            </div>

            <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
              <div className="text-xs font-semibold text-white">Symbol</div>
              <input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="AAPL"
                className="mt-2 w-full rounded-xl border border-dark-800 bg-dark-900 px-3 py-2 text-sm text-white"
              />
            </div>

            {symbol && (
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <PriceChart symbol={symbol} traderClass="experienced" signal="NONE" />
              </div>
            )}

            <div className="rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-300">
              Pro order settings (placeholder)
            </div>

            <button
              type="button"
              onClick={handleAnalyse}
              disabled={analyzing || !symbol.trim()}
              className="btn-primary w-full disabled:opacity-60"
            >
              {analyzing ? "Analysing…" : "Analyse"}
            </button>
            {marketStatus?.analyzeIndicator && (
              <div className="text-xs text-amber-300">{marketStatus.analyzeIndicator.text}</div>
            )}
          </div>

          <div className="space-y-4">
            <AIAnalysisCard analysis={analysis} title="AI analysis (technical)">
              <ExplanationToggle
                explanations={{
                  expert: analysis?.expert ?? "—",
                  simple: analysis?.simple ?? analysis?.message ?? "—",
                  metaphor: analysis?.metaphor ?? analysis?.message ?? "—",
                }}
              />
              <button
                type="button"
                onClick={() => setConfirmOpen(true)}
                disabled={!analysis}
                className={clsx("btn-primary mt-4 w-full", !analysis && "opacity-60")}
              >
                Execute
              </button>
            </AIAnalysisCard>

            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-300">
              Portfolio context (detailed placeholder)
            </div>
          </div>
        </div>
      )}

      {/* Layout D — semi_institutional */}
      {layout === "D" && (
        <div className="space-y-4">
          <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
            <div className="text-xs font-semibold text-white">Multi-symbol input</div>
            <textarea
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="AAPL, MSFT, NVDA"
              className="mt-2 min-h-[96px] w-full rounded-xl border border-dark-800 bg-dark-900 px-3 py-2 text-sm text-white"
            />
          </div>

          <div className="rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-300">
            Institutional settings (placeholder)
          </div>

          <button
            type="button"
            onClick={handleAnalyse}
            disabled={analyzing || !symbol.trim()}
            className="btn-primary w-full disabled:opacity-60"
          >
            {analyzing ? "Analysing…" : "Bulk analyse"}
          </button>

          <AIAnalysisCard analysis={analysis} title="AI analysis (raw JSON access)">
            <button
              type="button"
              onClick={() => setConfirmOpen(true)}
              disabled={!analysis}
              className={clsx("btn-primary w-full", !analysis && "opacity-60")}
            >
              Execute
            </button>
          </AIAnalysisCard>

          <div className="rounded-2xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-300">
            Portfolio risk panel (placeholder)
          </div>
        </div>
      )}

      {/* Layout E — crypto_native */}
      {layout === "E" && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-4">
            <div className="rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-300">
              Fear & Greed widget (placeholder)
            </div>
            <BrandPicker
              exchange={exchange}
              onManualSymbol={(s) => setSymbol(s.toUpperCase())}
              onChangeSelectedSymbols={(syms) => setSymbol((syms[0] || "").toUpperCase())}
              selectedSymbols={symbol ? [symbol] : []}
            />
            {symbol && (
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <PriceChart symbol={symbol} traderClass="crypto_native" signal="NONE" />
              </div>
            )}
            <AmountInput value={amount} onChange={setAmount} max={5000} label="Amount (GBP)" />
            <RiskSection variant="plain" />
            <button
              type="button"
              onClick={handleAnalyse}
              disabled={analyzing || !symbol.trim()}
              className="btn-primary w-full disabled:opacity-60"
            >
              {analyzing ? "Analysing…" : "Analyse"}
            </button>
          </div>

          <AIAnalysisCard analysis={analysis}>
            <ExplanationToggle
              explanations={{
                expert: analysis?.expert ?? "—",
                simple: analysis?.simple ?? analysis?.message ?? "—",
                metaphor: analysis?.metaphor ?? analysis?.message ?? "—",
              }}
            />
            <button
              type="button"
              onClick={() => setConfirmOpen(true)}
              disabled={!analysis}
              className={clsx("btn-primary mt-4 w-full", !analysis && "opacity-60")}
            >
              Execute
            </button>
          </AIAnalysisCard>
        </div>
      )}

      {/* Mandatory confirm modal for all layouts */}
      <TradeConfirmModal
        isOpen={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={async () => {
          await handleConfirmedTrade();
        }}
        trade={{
          ...analysis,
          symbol,
        }}
        isPaper={isPaper}
        traderClass={traderClass}
      />
      </div>
    </div>
  );
}

export default function TradePageWrapper() {
  return (
    <Suspense fallback={<div className="flex h-screen items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-dark-400" /></div>}>
      <TradePage />
    </Suspense>
  );
}
