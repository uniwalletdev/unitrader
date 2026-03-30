"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle } from "lucide-react";
import GalaxyLoader from "@/components/layout/GalaxyLoader";
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

const getAmountHelperText = (
  traderClass: string,
  trustLadderStage: number,
  min: number,
): string | null => {
  if (traderClass === "complete_novice") {
    return trustLadderStage === 1
      ? "£25 maximum during Watch Mode \u2014 Unitrader is proving itself"
      : "Unitrader will grow your limit as it builds your trust";
  }
  if (traderClass === "experienced" || traderClass === "semi_institutional") {
    return null;
  }
  return "Unitrader works best with £25 or more \u2014 smaller amounts earn very small returns";
};

const getAmountLimits = (traderClass: string, trustLadderStage: number) => {
  const limits: Record<string, { min: number; max: number; step: number }> = {
    complete_novice:    { min: 1,  max: 25,    step: 1   },
    curious_saver:      { min: 1,  max: 500,   step: 1   },
    self_taught:        { min: 1,  max: 5000,  step: 5   },
    experienced:        { min: 1,  max: 10000, step: 10  },
    semi_institutional: { min: 1,  max: 50000, step: 100 },
    crypto_native:      { min: 1,  max: 5000,  step: 5   },
  };

  // Trust Ladder Stage 1 always caps at £25 regardless of class (no minimum floor)
  if (trustLadderStage === 1) {
    return { min: 1, max: 25, step: 1 };
  }

  return limits[traderClass] ?? limits["complete_novice"];
};

function AmountInput({
  value,
  onChange,
  min,
  max,
  step,
  label = "Amount (GBP)",
  helperText,
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  label?: string;
  helperText?: string | null;
}) {
  const handleChange = (raw: number) => {
    if (raw < min) { onChange(min); return; }
    if (raw > max) { onChange(max); return; }
    onChange(raw);
  };

  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
      <div className="mb-2 flex items-center justify-between text-xs text-dark-400">
        <span>{label}</span>
        <span className="tabular-nums text-white">£{value}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => handleChange(Number(e.target.value))}
        className="w-full"
      />
      <div className="mt-2 flex justify-between text-[11px] text-dark-500">
        <span>Min: £{min}</span>
        <span>Max: £{max}</span>
      </div>
      {helperText && (
        <p className="mt-2 text-[11px] leading-relaxed text-dark-400">{helperText}</p>
      )}
    </div>
  );
}

function RiskSection({ variant }: { variant: "plain" | "pct" }) {
  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
      <div className="text-xs font-semibold text-white">Risk</div>
      <div className="mt-2 text-xs text-dark-300">
        {variant === "plain"
          ? "Unitrader uses stop-loss and take-profit to manage downside and lock gains."
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
          {/* Right — Unitrader verdict */}
          <div className="rounded-xl border border-brand-500/20 bg-brand-500/5 p-4">
            <div className="mb-3 text-xs font-semibold text-brand-400">Unitrader&apos;s verdict</div>
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
        Run analysis to see Unitrader&apos;s reasoning here.
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

  // Show a one-time banner when user skipped onboarding via the escape hatch
  const [skipBanner, setSkipBanner] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const skipped = sessionStorage.getItem("unitrader_onboarding_skipped");
    if (skipped === "true") {
      setSkipBanner(true);
      sessionStorage.removeItem("unitrader_onboarding_skipped");
    }
  }, []);

  const isPaper = useMemo(() => {
    // novice/saver: paper mode until trust stage advances; else live
    if (!trust) return traderClass === "complete_novice" || traderClass === "curious_saver";
    if (traderClass === "complete_novice" || traderClass === "curious_saver") return trust.stage <= 2;
    return false;
  }, [trust, traderClass]);

  const amountLimits = useMemo(
    () => getAmountLimits(traderClass, trust?.stage ?? 1),
    [traderClass, trust?.stage]
  );

  const amountHelperText = useMemo(
    () => getAmountHelperText(traderClass, trust?.stage ?? 1, amountLimits.min),
    [traderClass, trust?.stage, amountLimits.min]
  );

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

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(t);
  }, [toast]);

  // onboarding_complete gate: only render Apex wizard full-screen
  if (!loading && settings?.onboarding_complete === false) {
    return (
      <div className="relative">
        <ApexOnboardingChat />
        {/* "Skip onboarding" escape hatch for impatient traders */}
        <div className="absolute bottom-4 right-4 z-50">
          <button
            className="rounded-lg border border-dark-700 bg-dark-900 px-3 py-1.5 text-xs text-dark-400 hover:text-white transition-colors"
            onClick={async () => {
              try {
                await authApi.skipOnboarding();
                if (typeof window !== "undefined") {
                  sessionStorage.setItem("unitrader_onboarding_skipped", "true");
                }
                setSettings((prev) => ({ ...prev, onboarding_complete: true }));
              } catch {
                setSettings((prev) => ({ ...prev, onboarding_complete: true }));
              }
            }}
          >
            Skip setup — trade now
          </button>
        </div>
      </div>
    );
  }

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
    let res: Awaited<ReturnType<typeof tradingApi.execute>>;
    try {
      res = await tradingApi.execute(sym, exchange);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail === "onboarding_required") {
        // Server guard fired — clear local state and show wizard
        setSettings((prev) => ({ ...prev, onboarding_complete: false }));
        throw new Error("Please complete onboarding first");
      }
      throw e;
    }
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
        <GalaxyLoader size={72} label="Loading your trader…" />
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

      {/* Skip-onboarding info banner */}
      {skipBanner && (
        <div className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-yellow-500/20 bg-yellow-500/5 px-4 py-3 text-sm text-yellow-300">
          <span>
            You&apos;re trading with conservative defaults. Update your preferences anytime in{" "}
            <a href="/settings" className="underline hover:text-yellow-100">Settings</a>.
          </span>
          <button
            onClick={() => setSkipBanner(false)}
            className="shrink-0 text-yellow-500 hover:text-yellow-200"
          >
            ✕
          </button>
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
            <AmountInput value={amount} onChange={setAmount} min={amountLimits.min} max={amountLimits.max} step={amountLimits.step} helperText={amountHelperText} />
            <RiskSection variant="plain" />
            <button
              type="button"
              onClick={handleAnalyse}
              disabled={analyzing || !symbol.trim()}
              title={marketStatus?.analyzeTooltip}
              className="btn-primary w-full disabled:opacity-60"
            >
              {analyzing ? "Analysing…" : "Analyse with Unitrader"}
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
            <AmountInput value={amount} onChange={setAmount} min={amountLimits.min} max={amountLimits.max} step={amountLimits.step} label="Amount (GBP)" helperText={amountHelperText} />
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
            <AmountInput value={amount} onChange={setAmount} min={amountLimits.min} max={amountLimits.max} step={amountLimits.step} label="Amount (GBP)" helperText={amountHelperText} />
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
    <Suspense fallback={<div className="flex h-screen items-center justify-center bg-dark-950"><GalaxyLoader size={64} /></div>}>
      <TradePage />
    </Suspense>
  );
}
