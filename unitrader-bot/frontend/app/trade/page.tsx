"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { CheckCircle } from "lucide-react";
import GalaxyLoader from "@/components/layout/GalaxyLoader";
import { api, authApi, signalApi, tradingApi } from "@/lib/api";

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
import BrowseStack from "@/components/signals/BrowseStack";
import ApexSelectsPanel from "@/components/signals/ApexSelectsPanel";
import FullAutoPanel from "@/components/signals/FullAutoPanel";
import { useSignalStack } from "@/hooks/useSignalStack";

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
  approved_assets?: string[];
  trading_paused?: boolean;
  max_daily_loss?: number;
  onboarding_complete?: boolean;
  signal_stack_mode?: "browse" | "apex_selects" | "full_auto";
  risk_disclosure_accepted?: boolean;
  max_trade_amount?: number;
  apex_selects_threshold?: number;
  apex_selects_max_trades?: number;
  apex_selects_asset_classes?: string[];
  auto_trade_enabled?: boolean;
  auto_trade_threshold?: number;
  auto_trade_max_per_scan?: number;
  watchlist?: string[];
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
  const { isLoaded: authLoaded, isSignedIn, getToken } = useAuth();
  const welcome = searchParams?.get("welcome") === "true";
  const debug = searchParams?.get("debug") || "";
  const debugSet = useMemo(
    () => new Set((debug || "").split(",").map((x) => x.trim()).filter(Boolean)),
    [debug],
  );
  const dbg = (key: string) => debugSet.has(key);
  const bare = dbg("bare");
  const trace = dbg("trace");

  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [trust, setTrust] = useState<TrustLadder | null>(null);
  const [loading, setLoading] = useState(() => !bare);

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

  // Signal Stack UI state
  const [signalMode, setSignalMode] = useState<"browse" | "apex_selects" | "full_auto">("browse");
  const [manualExpanded, setManualExpanded] = useState(false);
  const [modeSaving, setModeSaving] = useState(false);

  // Show a one-time banner when user skipped onboarding via the escape hatch
  const [skipBanner, setSkipBanner] = useState(false);
  useEffect(() => {
    if (bare) return;
    if (typeof window === "undefined") return;
    const skipped = sessionStorage.getItem("unitrader_onboarding_skipped");
    if (skipped === "true") {
      setSkipBanner(true);
      sessionStorage.removeItem("unitrader_onboarding_skipped");
    }
  }, [bare]);

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
    if (bare) return;
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        // App Router pages rely on Clerk. Ensure we have a fresh token for backend auth.
        // Without this, the page can spam protected endpoints with 401s and get rate-limited.
        if (authLoaded && isSignedIn) {
          const token = await getToken();
          if (token) api.defaults.headers.common.Authorization = `Bearer ${token}`;
        }

        // If Clerk isn't ready or user isn't signed in yet, avoid hammering the API.
        if (!authLoaded || !isSignedIn) {
          if (!mounted) return;
          setSettings({ trader_class: "complete_novice", onboarding_complete: false });
          setTrust({
            stage: 1,
            paperEnabled: true,
            canAdvance: false,
            daysAtStage: 1,
            paperTradesCount: 0,
            maxAmountGbp: 25,
          });
          return;
        }

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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bare, authLoaded, isSignedIn]);

  useEffect(() => {
    if (!trace) return;
    if (typeof window === "undefined") return;
    try {
      const n = Number(sessionStorage.getItem("unitrader_trade_mounts") || "0") + 1;
      sessionStorage.setItem("unitrader_trade_mounts", String(n));
    } catch {
      // ignore
    }
  }, [trace]);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(t);
  }, [toast]);

  // Debug isolation toggles (production-safe). Use:
  // - /trade?debug=bare to bypass complex UI and isolate hook-order crashes.
  // - /trade?debug=no_sim,no_market,no_picker,no_chart,no_explain to bisect which child triggers it.
  if (bare) {
    const mounts =
      typeof window !== "undefined"
        ? Number(sessionStorage.getItem("unitrader_trade_mounts") || "0")
        : 0;
    return (
      <div className="min-h-screen bg-dark-950 flex items-center justify-center px-6">
        <div className="rounded-2xl border border-dark-800 bg-dark-950 p-6 text-center">
          <div className="text-sm font-semibold text-white">Trade debug: bare</div>
          <div className="mt-2 text-xs text-dark-400">
            If this renders, the crash is in a child component.
          </div>
          {trace && (
            <div className="mt-3 text-[11px] text-dark-500">
              mounts this session: {mounts} · href:{" "}
              {typeof window !== "undefined" ? window.location.href : "—"}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Fully onboarded users belong on the main dashboard — no reason to stay here
  // NOTE: We intentionally keep onboarded users on /trade now (Signal Stack is primary).

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
              } catch {
                // ignore — still redirect to dashboard
              }
              window.location.href = "/app";
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

  // Class-aware defaults for Signal Stack mode + manual trade expansion
  useEffect(() => {
    if (!settings) return;
    const tc = settings.trader_class ?? "complete_novice";
    const defaultMode =
      tc === "experienced" || tc === "semi_institutional" ? "apex_selects" : "browse";
    setSignalMode(settings.signal_stack_mode ?? defaultMode);
    const manualDefaultExpanded =
      tc === "experienced" || tc === "semi_institutional" || tc === "self_taught";
    setManualExpanded(manualDefaultExpanded);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings?.signal_stack_mode, settings?.trader_class]);

  const explanationLevel = useMemo(() => {
    const level = settings?.explanation_level;
    if (level === "expert" || level === "simple" || level === "metaphor") return level;
    if (traderClass === "complete_novice" || traderClass === "curious_saver") return "simple";
    return "expert";
  }, [settings?.explanation_level, traderClass]);

  const fullAutoLocked = useMemo(() => {
    if (traderClass === "experienced" || traderClass === "semi_institutional") return false;
    const stage = trust?.stage ?? 1;
    return stage < 3;
  }, [traderClass, trust?.stage]);

  const modeDescription = useMemo(() => {
    if (signalMode === "browse") {
      return "Apex has pre-analysed assets. Best opportunities ranked below.";
    }
    if (signalMode === "apex_selects") {
      return "Set your parameters. Apex finds the best match.";
    }
    return "Apex is trading automatically on your schedule.";
  }, [signalMode]);

  const { signals, isLoading: signalsLoading, isRefreshing, lastScanAt, nextScanInMinutes, assetsScanned, error: signalsError, acceptSignal, skipSignal, refresh } =
    useSignalStack({ signal_stack_mode: signalMode });

  const maxSignals = useMemo(() => {
    if (traderClass === "complete_novice") return 3;
    if (traderClass === "curious_saver") return 5;
    return 10;
  }, [traderClass]);

  const browseSignals = useMemo(() => signals.slice(0, maxSignals), [signals, maxSignals]);

  const handleSetMode = async (mode: "browse" | "apex_selects" | "full_auto") => {
    if (mode === signalMode) return;
    if (mode === "full_auto" && fullAutoLocked) {
      setToast("Full Auto is locked — complete the Trust Ladder first.");
      return;
    }
    setSignalMode(mode);
    setSettings((prev) => (prev ? { ...prev, signal_stack_mode: mode } : prev));
    setModeSaving(true);
    try {
      await signalApi.updateSettings(mode);
    } catch {
      // non-fatal: keep optimistic UI
    } finally {
      setModeSaving(false);
    }
  };

  const handleAcceptSignal = async (signalId: string): Promise<boolean> => {
    const sig = signals.find((s) => s.id === signalId);
    try {
      const ok = await acceptSignal(signalId);
      if (ok) {
        setToast(`Apex is buying ${sig?.asset_name ?? "this asset"}`);
      }
      return ok;
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail === "risk_disclosure_required" || detail === "risk_disclosure_not_accepted") {
        if (typeof window !== "undefined") {
          window.location.href = `/risk-disclosure?next=${encodeURIComponent("/trade")}`;
        }
        return false;
      }
      return false;
    }
  };

  const handleSkipSignal = (signalId: string) => {
    skipSignal(signalId);
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
      {!dbg("no_sim") && showSimulatorModal && <WhatIfSimulator mode="modal" />}

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
      {!dbg("no_market") && (
        <div className="mb-4">
          <MarketStatusBar
            traderClass={traderClass}
            exchange={exchange}
            symbol={symbol}
            onStatusChange={setMarketStatus}
          />
        </div>
      )}

      {/* Trust ladder banner for A */}
      {layout === "A" && trust && (
        <div className="mb-4">
          <TrustLadderBanner
            traderClass={traderClass}
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

      {/* ── Signal Stack: primary interface ─────────────────────────────────── */}
      {settings?.onboarding_complete === true && (
        <div className="mb-6">
          {/* Mode toggle */} 
          <div className="rounded-2xl border border-dark-800 bg-dark-950 p-3 mb-3">
            <div className="grid grid-cols-3 gap-1 rounded-xl border border-dark-800 bg-dark-900 p-1">
              <button
                type="button"
                onClick={() => handleSetMode("browse")}
                className={clsx(
                  "rounded-lg px-3 py-2 text-xs font-semibold transition-all",
                  signalMode === "browse" ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white",
                )}
              >
                Browse signals · You choose
              </button>
              <button
                type="button"
                onClick={() => handleSetMode("apex_selects")}
                className={clsx(
                  "rounded-lg px-3 py-2 text-xs font-semibold transition-all",
                  signalMode === "apex_selects" ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white",
                )}
              >
                Apex selects · AI curates
              </button>
              <button
                type="button"
                onClick={() => handleSetMode("full_auto")}
                title={fullAutoLocked ? "Complete Trust Ladder first" : undefined}
                className={clsx(
                  "rounded-lg px-3 py-2 text-xs font-semibold transition-all",
                  signalMode === "full_auto" ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white",
                  fullAutoLocked && "opacity-50 cursor-not-allowed",
                )}
                disabled={fullAutoLocked}
              >
                Full auto · Apex acts alone
              </button>
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-dark-400">
              <span>{modeDescription}</span>
              {modeSaving && <span className="text-dark-500">Saving…</span>}
            </div>
          </div>

          {/* Panel */} 
          {signalMode === "browse" && (
            <BrowseStack
              signals={browseSignals}
              isRefreshing={isRefreshing || signalsLoading}
              lastScanAt={lastScanAt}
              nextScanInMinutes={nextScanInMinutes}
              assetsScanned={assetsScanned}
              traderClass={traderClass}
              explanationLevel={explanationLevel}
              onAccept={handleAcceptSignal}
              onSkip={handleSkipSignal}
              onRefresh={refresh}
            />
          )}
          {signalMode === "apex_selects" && (
            <ApexSelectsPanel
              userSettings={settings ?? {}}
              onExecute={async (ids) => {
                for (const id of ids) {
                  await handleAcceptSignal(id);
                }
              }}
            />
          )}
          {signalMode === "full_auto" && (
            <FullAutoPanel
              userSettings={settings ?? {}}
              trustLadderStage={trust?.stage ?? 1}
              onSettingsUpdate={(updates) => setSettings((prev) => (prev ? { ...prev, ...(updates as any) } : prev))}
            />
          )}

          {signalsError && (
            <div className="mt-3 rounded-xl border border-dark-800 bg-dark-950 p-3 text-xs text-dark-400">
              {signalsError} You can still use manual trade below.
            </div>
          )}
        </div>
      )}

      {/* ── Manual trade (secondary, collapsible) ───────────────────────────── */}
      <div className="rounded-2xl border border-dark-800 bg-dark-950 p-3">
        <button
          type="button"
          onClick={() => setManualExpanded((v) => !v)}
          className="w-full flex items-center justify-between rounded-xl px-3 py-2 text-sm font-semibold text-white hover:bg-dark-900 transition-colors"
        >
          <span>Search for a specific asset instead</span>
          <span className="text-dark-400">{manualExpanded ? "▴" : "▾"}</span>
        </button>

        {manualExpanded && (
          <div className="mt-3">
            {/* Layout A */}
            {layout === "A" && (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-4">
                  {!dbg("no_picker") && (
                    <BrandPicker
                      exchange={exchange}
                      traderClass={traderClass}
                      favourites={settings?.approved_assets ?? []}
                      onManualSymbol={(s) => setSymbol(s.toUpperCase())}
                      onChangeSelectedSymbols={(syms) => setSymbol((syms[0] || "").toUpperCase())}
                      selectedSymbols={symbol ? [symbol] : []}
                    />
                  )}
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
                  {!dbg("no_explain") && (
                    <ExplanationToggle
                      explanations={{
                        expert: analysis?.expert ?? "—",
                        simple: analysis?.simple ?? analysis?.message ?? "—",
                        metaphor: analysis?.metaphor ?? analysis?.message ?? "—",
                      }}
                      traderClass={traderClass}
                      settingsLevel={
                        settings?.explanation_level === "expert" ||
                        settings?.explanation_level === "simple" ||
                        settings?.explanation_level === "metaphor"
                          ? (settings.explanation_level as any)
                          : null
                      }
                    />
                  )}
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
                  {!dbg("no_picker") && (
                    <BrandPicker
                      exchange={exchange}
                      traderClass={traderClass}
                      favourites={settings?.approved_assets ?? []}
                      onManualSymbol={(s) => setSymbol(s.toUpperCase())}
                      onChangeSelectedSymbols={(syms) => setSymbol((syms[0] || "").toUpperCase())}
                      selectedSymbols={symbol ? [symbol] : []}
                    />
                  )}
                  {symbol && (
                    <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                      {!dbg("no_chart") && <PriceChart symbol={symbol} traderClass="self_taught" signal="NONE" />}
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
                    {!dbg("no_explain") && (
                      <ExplanationToggle
                        explanations={{
                          expert: analysis?.expert ?? "—",
                          simple: analysis?.simple ?? analysis?.message ?? "—",
                          metaphor: analysis?.metaphor ?? analysis?.message ?? "—",
                        }}
                        traderClass={traderClass}
                        settingsLevel={
                          settings?.explanation_level === "expert" ||
                          settings?.explanation_level === "simple" ||
                          settings?.explanation_level === "metaphor"
                            ? (settings.explanation_level as any)
                            : null
                        }
                      />
                    )}
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
                      {!dbg("no_chart") && <PriceChart symbol={symbol} traderClass="experienced" signal="NONE" />}
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
          </div>
        )}
      </div>

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
