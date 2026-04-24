"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { CheckCircle, Loader2 } from "lucide-react";
import GalaxyLoader from "@/components/layout/GalaxyLoader";
import { api, authApi, exchangeApi, signalApi, tradingApi } from "@/lib/api";
import { sanitizeApiError } from "@/lib/errorUtils";

import BotOnboardingChat from "@/components/onboarding/ApexOnboardingChat";
import WhatIfSimulator from "@/components/onboarding/WhatIfSimulator";
import MarketStatusBar, { MarketStatus } from "@/components/trade/MarketStatusBar";
import TrustLadderBanner from "@/components/trade/TrustLadderBanner";
import EtoroOfferCard from "@/components/etoro/EtoroOfferCard";
import BrandPicker, { displayBrandLine } from "@/components/trade/BrandPicker";
import PriceChart from "@/components/trade/PriceChart";
import type { TradeMarker } from "@/components/trade/PriceChart";
import ExplanationToggle from "@/components/trade/ExplanationToggle";
import TradeConfirmModal from "@/components/trade/TradeConfirmModal";
import CircuitBreakerAlert from "@/components/trade/CircuitBreakerAlert";
import RiskWarning from "@/components/layout/RiskWarning";
import NeverHoldBanner from "@/components/layout/NeverHoldBanner";
import UnitraderNotificationTicker from "@/components/notifications/UnitraderNotificationTicker";
import AIConfidenceGauge from "@/components/trade/AIConfidenceGauge";
import PerformancePulse from "@/components/trade/PerformancePulse";
import BrowseStack from "@/components/signals/BrowseStack";
import BotSelectsPanel from "@/components/signals/ApexSelectsPanel";
import GuidedPanel from "@/components/signals/GuidedPanel";
import FullAutoPanel from "@/components/signals/FullAutoPanel";
import { useSignalStack } from "@/hooks/useSignalStack";
import {
  formatAmountLabel,
  getCurrencySymbol,
  resolveTradingCurrency,
} from "@/utils/currency";
import { isUsEquityRegularSessionEt, isStocksTradingAsset } from "@/utils/usEquitySession";

// Crypto bases for detection
const CRYPTO_BASES = new Set([
  "BTC", "XBT", "ETH", "SOL", "DOGE", "XDG", "ADA", "XRP", "AVAX", "MATIC",
  "LINK", "DOT", "ATOM", "LTC", "BCH", "UNI", "AAVE", "BNB", "USDT", "USDC", "BUSD"
]);

function isCryptoAsset(symbol: string): boolean {
  const s = symbol.trim().toUpperCase();
  // Crypto format: BTC/USD, ETH-USDT, etc.
  if (s.includes("/") || s.includes("-")) return true;
  // Check if it's a known crypto base
  const base = s.replace("USDT", "").replace("BUSD", "").replace("USDC", "");
  return CRYPTO_BASES.has(base);
}

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

type UserSettings = {
  ai_name?: string;
  trader_class?: TraderClass;
  explanation_level?: string;
  approved_assets?: string[];
  trading_paused?: boolean;
  max_daily_loss?: number;
  onboarding_complete?: boolean;
  execution_mode?: "watch" | "assisted" | "guided" | "autonomous";
  autonomous_mode_unlocked?: boolean;
  risk_disclosure_accepted?: boolean;
  max_trade_amount?: number;
  guided_confidence_threshold?: number;
  apex_selects_max_trades?: number;
  apex_selects_asset_classes?: string[];
  auto_trade_enabled?: boolean;
  auto_trade_threshold?: number;
  auto_trade_max_per_scan?: number;
  watchlist?: string[];
  preferred_trading_account_id?: string | null;
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
  currencySymbol: string,
  traderClass: string,
  trustLadderStage: number,
  min: number,
  botName = "Unitrader",
): string | null => {
  if (traderClass === "complete_novice") {
    return trustLadderStage === 1
      ? `${currencySymbol}25 maximum during Watch Mode \u2014 ${botName} is proving itself`
      : `${botName} will grow your limit as it builds your trust`;
  }
  if (traderClass === "experienced" || traderClass === "semi_institutional") {
    return null;
  }
  return `${botName} works best with ${currencySymbol}25 or more \u2014 smaller amounts earn very small returns`;
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

  // Trust Ladder Stage 1 always caps at $25 regardless of class (no minimum floor)
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
  label,
  currencySymbol = "$",
  helperText,
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  label?: string;
  currencySymbol?: string;
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
        <span className="tabular-nums text-white">
          {currencySymbol}
          {value}
        </span>
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
        <span>
          Min: {currencySymbol}
          {min}
        </span>
        <span>
          Max: {currencySymbol}
          {max}
        </span>
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

type OpenPositionRow = {
  id: string;
  symbol: string;
  side?: string | null;
  quantity?: number | null;
  entry_price?: number | null;
  created_at?: string | null;
};

function OpenPositionsPanel({
  loading,
  positions,
  variant,
}: {
  loading: boolean;
  positions: OpenPositionRow[];
  variant: "compact" | "detailed";
}) {
  const count = positions.length;
  return (
    <div className="rounded-2xl border border-dark-800 bg-dark-950 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-white">Open positions</div>
        <Link href="/positions" className="text-[11px] font-medium text-cyan-400 hover:underline">
          View all
        </Link>
      </div>
      {loading ? (
        <div className="mt-2 text-xs text-dark-500">Loading…</div>
      ) : count === 0 ? (
        <div className="mt-2 text-sm text-dark-300">No open positions</div>
      ) : (
        <>
          <div className="mt-1 text-2xl font-extrabold tabular-nums text-white">{count}</div>
          <ul className={variant === "detailed" ? "mt-3 space-y-2" : "mt-2 flex flex-wrap gap-2"}>
            {positions.slice(0, variant === "detailed" ? 20 : 12).map((p) => (
              <li
                key={p.id}
                className={
                  variant === "detailed"
                    ? "rounded-lg border border-dark-800 bg-dark-900/50 px-3 py-2 text-xs text-dark-200"
                    : "rounded-lg border border-dark-800 bg-dark-900/50 px-2 py-1 text-xs text-dark-200"
                }
              >
                <span className="font-semibold text-white">{p.symbol}</span>
                {variant === "detailed" && (p.side || p.quantity != null) && (
                  <span className="ml-2 text-dark-400">
                    {[p.side, p.quantity != null ? String(p.quantity) : null].filter(Boolean).join(" · ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/** Manual “Execute Trade” button (AI Trader grid + analysis). */
type TradeButtonState =
  | "disabled"
  | "analyzing"
  | "ready"
  | "market-closed"
  | "no-signal"
  | "data-unavailable";

const TRADE_BUTTON_MIN_CONFIDENCE = 60;

function applyAnalyzeResponseToTradeButton(
  response: unknown,
  exchangeForAsset: string,
  symbol: string,
): TradeButtonState {
  const a = response as Record<string, unknown> | null | undefined;
  if (!a) return "no-signal";

  // Use signal_status from backend if available
  const signalStatus = a.signal_status as string | undefined;
  if (signalStatus === "data_unavailable") return "data-unavailable";
  if (signalStatus === "market_closed") return "market-closed";
  if (signalStatus === "no_signal") return "no-signal";
  if (signalStatus === "signal_ready") return "ready";

  // Fallback: derive from raw fields for backwards compatibility
  const sigRaw = String(a.signal ?? a.decision ?? "").toLowerCase();
  const conf = Number(a.confidence ?? 0);

  if (sigRaw === "wait" || !Number.isFinite(conf) || conf < TRADE_BUTTON_MIN_CONFIDENCE) {
    return "no-signal";
  }

  if (a.market_closed === true || String(a.status ?? "").toLowerCase() === "market-closed") {
    return "market-closed";
  }

  const sym = symbol.trim();
  const localStockClosed =
    sym && isStocksTradingAsset(exchangeForAsset, sym) && !isUsEquityRegularSessionEt();
  if (localStockClosed) return "market-closed";

  const decisionUp = String(a.decision ?? a.signal ?? "").toUpperCase();
  if (decisionUp !== "BUY" && decisionUp !== "SELL") return "no-signal";

  return "ready";
}

function ManualTradeExecuteButton({
  tradeButtonState,
  onExecute,
  retryCountdown,
}: {
  tradeButtonState: TradeButtonState;
  onExecute: () => void;
  retryCountdown?: number | null;
}) {
  const ready = tradeButtonState === "ready";
  const isAnalyzing = tradeButtonState === "analyzing";
  const label =
    tradeButtonState === "disabled"
      ? "Select an asset"
      : isAnalyzing
        ? "Analysing\u2026"
        : tradeButtonState === "ready"
          ? "Execute Trade"
          : tradeButtonState === "market-closed"
            ? "Market Closed"
            : tradeButtonState === "data-unavailable"
              ? "Data Unavailable \u2014 Retrying"
              : "No Signal";

  return (
    <div>
      <button
        type="button"
        onClick={() => {
          if (tradeButtonState !== "ready") return;
          onExecute();
        }}
        title={ready ? undefined : label}
        disabled={!ready && !isAnalyzing}
        className={clsx(
          "mt-4 flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold transition-colors",
          ready
            ? "cursor-pointer bg-green-600 text-white hover:bg-green-500"
            : isAnalyzing
              ? "pointer-events-none bg-green-600/60 text-white/80"
              : "cursor-not-allowed bg-dark-800 text-dark-400 opacity-90",
        )}
      >
        {(isAnalyzing || tradeButtonState === "data-unavailable") && (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
        )}
        {label}
      </button>
      {tradeButtonState === "data-unavailable" && retryCountdown != null && retryCountdown > 0 && (
        <p className="mt-1 text-center text-xs text-dark-500">Retrying in {retryCountdown}s\u2026</p>
      )}
    </div>
  );
}

function analysisAssetHeading(symbol: string): string {
  const { name, ticker } = displayBrandLine(symbol);
  if (!ticker) return "";
  return name !== ticker ? `${name} — ${ticker}` : ticker;
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
  botName,
  symbol,
  title = "AI analysis",
  analysis,
  analyzing,
  analysisError,
  signalStatus,
  onRetry,
  showExplanationToggle,
  showPendingAnalyseHint = true,
  traderClass,
  settingsExplanationLevel,
  children,
}: {
  botName: string;
  symbol: string;
  title?: string;
  analysis: AnalysisResult | null;
  analyzing: boolean;
  analysisError: string | null;
  signalStatus: TradeButtonState;
  onRetry: () => void;
  showExplanationToggle: boolean;
  /** Layouts that auto-run analyse hide this (no manual-only gap before the request starts). */
  showPendingAnalyseHint?: boolean;
  traderClass: TraderClass;
  settingsExplanationLevel: "expert" | "simple" | "metaphor" | null;
  children: React.ReactNode;
}) {
  const sym = symbol.trim();
  const heading = sym ? analysisAssetHeading(sym) : "";
  const tickerShort = sym ? (displayBrandLine(sym).ticker || sym) : "";

  const explanationPayload = {
    expert: analysis?.expert ?? "—",
    simple: analysis?.simple ?? analysis?.message ?? "—",
    metaphor: analysis?.metaphor ?? analysis?.message ?? "—",
  };

  const keyFactors: string[] = Array.isArray(analysis?.key_factors)
    ? analysis.key_factors.filter((x: unknown) => typeof x === "string")
    : [];

  const togglesDisabled = analyzing || !!analysisError || !analysis || signalStatus === "data-unavailable";

  const nextMarketOpen = analysis?.next_market_open as string | undefined;

  /** Verdict content varies by signal status */
  const renderVerdict = () => {
    if (signalStatus === "data-unavailable") {
      return (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
          <div className="mb-3 text-xs font-semibold text-amber-400">Analysis unavailable</div>
          <div className="text-sm text-dark-300">
            Market data is temporarily unavailable. Analysis will resume automatically.
          </div>
        </div>
      );
    }
    if (signalStatus === "market-closed") {
      return (
        <div className="rounded-xl border border-dark-700 bg-dark-900/60 p-4">
          <div className="mb-3 text-xs font-semibold text-dark-400">Market is closed</div>
          <div className="text-sm text-dark-300">
            {nextMarketOpen
              ? `Next open: ${new Date(nextMarketOpen).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}`
              : "The market is currently closed. Check back during trading hours."}
          </div>
        </div>
      );
    }
    if (signalStatus === "no-signal" && analysis) {
      return (
        <div className="rounded-xl border border-dark-700 bg-dark-900/60 p-4">
          <div className="mb-3 text-xs font-semibold text-dark-400">No trade opportunity found</div>
          <div className="text-sm text-dark-300">
            {analysis.message || analysis.reasoning || "The AI analysed this asset and found no trade meeting the confidence threshold."}
          </div>
        </div>
      );
    }
    if (signalStatus === "ready" && analysis) {
      return (
        <div className="rounded-xl border border-brand-500/20 bg-brand-500/5 p-4">
          <div className="mb-3 text-xs font-semibold text-brand-400">Unitrader&apos;s verdict</div>
          {analysis.confidence != null && (
            <div className="mb-3">
              <AIConfidenceGauge
                confidence={Math.round(Number(analysis.confidence))}
                aiName={botName}
                marketCondition={analysis.market_condition ?? null}
              />
            </div>
          )}
          <div className="mb-3 text-sm text-dark-200">
            {analysis.message || analysis.reasoning || "Analysis ready."}
          </div>
          {analysis.decision && (
            <div className="text-xs font-semibold text-brand-300">
              {String(analysis.decision).toUpperCase()}
            </div>
          )}
        </div>
      );
    }
    // Default / disabled / pending
    return null;
  };

  return (
    <div className="rounded-2xl border border-dark-800 bg-dark-950 p-4 md:p-5">
      <div className="mb-3 text-sm font-semibold text-white">{title}</div>

      {!sym ? (
        <p className="rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-400">
          Select an asset from the grid to see {botName}&apos;s analysis.
        </p>
      ) : (
        <>
          <h2 className="mb-4 text-base font-semibold text-white">{heading}</h2>

          {analyzing && (
            <div className="mb-4 flex flex-col items-center justify-center gap-3 rounded-xl border border-dark-800 bg-dark-900/60 px-4 py-10 text-center">
              <Loader2 className="h-8 w-8 shrink-0 animate-spin text-brand-400" aria-hidden />
              <p className="text-sm text-dark-300">
                {botName} is analysing {tickerShort}...
              </p>
            </div>
          )}

          {!analyzing && analysisError && signalStatus !== "data-unavailable" && (
            <div className="mb-4 space-y-3 rounded-xl border border-dark-800 bg-dark-950 p-4">
              <p className="text-sm text-dark-300">{analysisError}</p>
              <button
                type="button"
                onClick={onRetry}
                className="rounded-lg border border-brand-500/40 bg-brand-500/10 px-4 py-2 text-sm font-semibold text-brand-300 transition hover:bg-brand-500/20"
              >
                Retry
              </button>
            </div>
          )}

          {!analyzing && !analysisError && !analysis && signalStatus !== "data-unavailable" && showPendingAnalyseHint && (
            <p className="mb-4 rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-400">
              Click Analyse to load {botName}&apos;s reasoning for this asset.
            </p>
          )}

          {!analyzing && (
            <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              {analysis && signalStatus !== "data-unavailable" && <RawDataColumn analysis={analysis} />}
              {renderVerdict()}
            </div>
          )}

          {showExplanationToggle && sym && signalStatus !== "data-unavailable" && (
            <div className="mb-4">
              <ExplanationToggle
                explanations={explanationPayload}
                traderClass={traderClass}
                settingsLevel={settingsExplanationLevel}
                disabled={togglesDisabled}
              />
            </div>
          )}

          {analysis && !analyzing && !analysisError && signalStatus !== "data-unavailable" && keyFactors.length > 0 && (
            <div className="mb-4">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-dark-500">
                Key factors
              </div>
              <ul className="flex flex-wrap gap-2">
                {keyFactors.map((f, i) => (
                  <li
                    key={`${f}-${i}`}
                    className="rounded-lg border border-dark-700 bg-dark-900 px-2.5 py-1 text-xs text-dark-300"
                  >
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {children}
        </>
      )}
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
  const [botName, setBotName] = useState("");
  const [trust, setTrust] = useState<TrustLadder | null>(null);
  const [loading, setLoading] = useState(() => !bare);

  const traderClass: TraderClass = settings?.trader_class ?? "complete_novice";
  const resolvedBotName = botName || settings?.ai_name || "Unitrader";

  const [exchange, setExchange] = useState("");
  const [selectedTradingAccountId, setSelectedTradingAccountId] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<Array<{
    trading_account_id: string;
    exchange: string;
    is_paper: boolean;
    account_label?: string | null;
    currency?: string;
  }>>([]);

  // Multi-exchange: user context from resolver
  const [userContext, setUserContext] = useState<{
    available_asset_classes: string[];
    active_venue: {
      exchange: string;
      asset_class: string;
      paper_mode_type: string;
      is_paper: boolean;
      trading_account_id: string;
      display_label: string;
    } | null;
    no_exchange_connected: boolean;
  } | null>(null);
  const [activeAssetClass, setActiveAssetClass] = useState<string | null>(null);

  const [symbol, setSymbol] = useState("");
  const [amount, setAmount] = useState(25);

  const [analysis, setAnalysis] = useState<any>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [tradeButtonState, setTradeButtonState] = useState<TradeButtonState>("disabled");
  const [toast, setToast] = useState<string | null>(null);
  const [retryCountdown, setRetryCountdown] = useState<number | null>(null);

  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [positionsCount, setPositionsCount] = useState<number | null>(null);

  // Execution mode UI state (watch | assisted | guided | autonomous)
  const [signalMode, setSignalMode] = useState<"watch" | "assisted" | "guided" | "autonomous">("watch");
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

  const layout: "A" | "B" | "C" | "D" | "E" = useMemo(
    () =>
      traderClass === "complete_novice" || traderClass === "curious_saver"
        ? "A"
        : traderClass === "self_taught"
          ? "B"
          : traderClass === "experienced"
            ? "C"
            : traderClass === "semi_institutional"
              ? "D"
              : "E",
    [traderClass],
  );

  const settingsExplanationLevel = useMemo((): "expert" | "simple" | "metaphor" | null => {
    const l = settings?.explanation_level;
    if (l === "expert" || l === "simple" || l === "metaphor") return l;
    return null;
  }, [settings?.explanation_level]);

  const amountLimits = useMemo(
    () => getAmountLimits(traderClass, trust?.stage ?? 1),
    [traderClass, trust?.stage]
  );

  useEffect(() => {
    setAmount((v) =>
      Math.min(Math.max(v, amountLimits.min), amountLimits.max),
    );
  }, [amountLimits.min, amountLimits.max]);

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

        const [sRes, tRes, meRes] = await Promise.all([
          authApi.getSettings(),
          api.get("/api/onboarding/trust-ladder"),
          authApi.me(),
        ]);
        if (!mounted) return;
        setSettings(sRes.data);
        setTrust(tRes.data?.data ?? tRes.data);
        setBotName(meRes.data?.ai_name ?? "");
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

  // Load connected trading accounts (for exchange-aware calls)
  useEffect(() => {
    if (bare) return;
    if (!settings) return;
    let mounted = true;
    (async () => {
      type TradingAccountRow = {
        trading_account_id: string;
        exchange: string;
        is_paper: boolean;
        account_label: string | null;
        currency?: string;
      };

      const fromBalancesRows = (rows: Array<{
        trading_account_id?: string | null;
        exchange: string;
        is_paper: boolean;
        account_label?: string | null;
        currency?: string;
      }>): TradingAccountRow[] =>
        rows
          .filter((r) => !!r.trading_account_id)
          .map((r) => ({
            trading_account_id: r.trading_account_id as string,
            exchange: r.exchange,
            is_paper: r.is_paper,
            account_label: r.account_label ?? null,
            currency: r.currency,
          }));

      const fromListRows = (rows: Array<{
        trading_account_id?: string | null;
        exchange: string;
        is_paper: boolean;
        account_label?: string | null;
      }>): TradingAccountRow[] =>
        rows
          .filter((r) => !!r.trading_account_id)
          .map((r) => ({
            trading_account_id: r.trading_account_id as string,
            exchange: r.exchange,
            is_paper: r.is_paper,
            account_label: r.account_label ?? null,
          }));

      let connected: TradingAccountRow[] = [];
      try {
        const res = await exchangeApi.balances();
        const rows = (res.data?.data ?? []) as Parameters<typeof fromBalancesRows>[0];
        connected = fromBalancesRows(rows);
      } catch {
        connected = [];
      }

      if (connected.length === 0) {
        try {
          const res = await exchangeApi.list();
          const rows = (res.data?.data ?? []) as Parameters<typeof fromListRows>[0];
          connected = fromListRows(rows);
        } catch {
          connected = [];
        }
      }

      if (!mounted) return;
      setAccounts(connected);

      const preferred = settings.preferred_trading_account_id ?? null;
      const preferredInList =
        !!preferred && connected.some((a) => a.trading_account_id === preferred);
      const resolved =
        (preferred && connected.find((a) => a.trading_account_id === preferred)?.trading_account_id) ||
        connected[0]?.trading_account_id ||
        null;

      if (preferred && !preferredInList && resolved) {
        await authApi.updateSettings({ preferred_trading_account_id: resolved }).catch(() => {});
        if (mounted) {
          setSettings((prev) => (prev ? { ...prev, preferred_trading_account_id: resolved } : prev));
        }
      }

      if (!mounted) return;
      setSelectedTradingAccountId(resolved);

      const selected = resolved ? connected.find((a) => a.trading_account_id === resolved) : null;
      if (selected?.exchange) setExchange(selected.exchange);

      // Fetch execution venue context from resolver
      try {
        const ucRes = await tradingApi.userContext();
        const uc = ucRes.data?.data ?? ucRes.data;
        if (mounted && uc) {
          setUserContext(uc);
          if (uc.active_venue) {
            setActiveAssetClass(uc.active_venue.asset_class);
            // Let resolver override exchange/account if present
            if (uc.active_venue.trading_account_id) {
              setSelectedTradingAccountId(uc.active_venue.trading_account_id);
            }
            if (uc.active_venue.exchange) {
              setExchange(uc.active_venue.exchange);
            }
          }
        }
      } catch (e) {
        console.error("[userContext] Error fetching:", e);
        // Non-blocking — fall back to existing account-based logic
      }
    })();
    return () => {
      mounted = false;
    };
  }, [bare, settings]);

  const selectedAccount = useMemo(() => {
    if (!selectedTradingAccountId) return null;
    return accounts.find((a) => a.trading_account_id === selectedTradingAccountId) ?? null;
  }, [accounts, selectedTradingAccountId]);

  const buildOpenPositionQuery = useCallback((): {
    trading_account_id?: string;
    exchange?: string;
    is_paper: boolean;
  } => {
    const q: { trading_account_id?: string; exchange?: string; is_paper: boolean } = {
      is_paper: selectedAccount?.is_paper ?? isPaper,
    };
    if (selectedTradingAccountId) q.trading_account_id = selectedTradingAccountId;
    const ex = (selectedAccount?.exchange || exchange || "").trim().toLowerCase();
    if (ex) q.exchange = ex;
    return q;
  }, [selectedTradingAccountId, selectedAccount?.exchange, selectedAccount?.is_paper, exchange, isPaper]);

  const [openPositionsRows, setOpenPositionsRows] = useState<OpenPositionRow[]>([]);
  const [openPositionsLoading, setOpenPositionsLoading] = useState(false);

  const refreshOpenPositions = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (!opts?.silent) setOpenPositionsLoading(true);
      try {
        const res = await tradingApi.openPositions(buildOpenPositionQuery());
        const d = res.data?.data ?? res.data;
        const positions = Array.isArray(d?.positions) ? d.positions : [];
        setOpenPositionsRows(
          positions.map((p: { id: unknown; symbol?: unknown; side?: unknown; quantity?: unknown; entry_price?: unknown; created_at?: unknown }) => ({
            id: String(p.id),
            symbol: String(p.symbol ?? ""),
            side: p.side != null ? String(p.side) : null,
            quantity: p.quantity != null && p.quantity !== "" ? Number(p.quantity) : null,
            entry_price: p.entry_price != null ? Number(p.entry_price) : null,
            created_at: p.created_at != null ? String(p.created_at) : null,
          })),
        );
        const count = typeof d?.count === "number" ? d.count : positions.length;
        setPositionsCount(count);
      } catch {
        if (!opts?.silent) {
          setOpenPositionsRows([]);
        }
      } finally {
        if (!opts?.silent) setOpenPositionsLoading(false);
      }
    },
    [buildOpenPositionQuery],
  );

  useEffect(() => {
    if (bare) return;
    if (!authLoaded || !isSignedIn) return;
    void refreshOpenPositions();
  }, [bare, authLoaded, isSignedIn, refreshOpenPositions]);

  // Build trade markers for PriceChart from open positions matching current symbol
  const activeTradeMarkers: TradeMarker[] = useMemo(() => {
    if (!symbol) return [];
    return openPositionsRows
      .filter((p) => p.symbol.toUpperCase() === symbol.toUpperCase() && p.entry_price)
      .map((p) => ({
        type: "entry" as const,
        price: p.entry_price!,
        time: p.created_at ? p.created_at.slice(0, 10) : new Date().toISOString().slice(0, 10),
        side: (p.side?.toUpperCase() === "SELL" ? "SELL" : "BUY") as "BUY" | "SELL",
      }));
  }, [symbol, openPositionsRows]);

  const displayCurrencyCode = useMemo(() => {
    const ex = (selectedAccount?.exchange ?? exchange ?? "").toLowerCase();
    return resolveTradingCurrency(ex || "alpaca", selectedAccount?.currency);
  }, [selectedAccount?.exchange, selectedAccount?.currency, exchange]);

  const currencySymbol = useMemo(() => {
    const ex = selectedAccount?.exchange ?? exchange ?? "";
    return getCurrencySymbol(ex || "alpaca", selectedAccount?.currency);
  }, [selectedAccount?.exchange, selectedAccount?.currency, exchange]);

  const amountSliderLabel = useMemo(
    () => formatAmountLabel(displayCurrencyCode),
    [displayCurrencyCode],
  );

  const amountHelperText = useMemo(
    () =>
      getAmountHelperText(currencySymbol, traderClass, trust?.stage ?? 1, amountLimits.min, resolvedBotName),
    [currencySymbol, traderClass, trust?.stage, amountLimits.min, resolvedBotName],
  );

  useEffect(() => {
    const ex = selectedAccount?.exchange?.trim();
    if (ex) setExchange(ex);
  }, [selectedAccount]);

  const onSelectTradingAccount = async (id: string | null) => {
    setSelectedTradingAccountId(id);
    const acct = id ? accounts.find((a) => a.trading_account_id === id) ?? null : null;
    if (acct?.exchange) setExchange(acct.exchange);
    try {
      await authApi.updateSettings({ preferred_trading_account_id: id });
      setSettings((prev) => (prev ? { ...prev, preferred_trading_account_id: id } : prev));
    } catch {
      // non-blocking; selection stays local for this session
    }
  };

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

  useEffect(() => {
    if (!symbol.trim()) {
      setTradeButtonState("disabled");
    }
  }, [symbol]);

  const handleAnalyse = useCallback(async () => {
    if (!symbol.trim()) return;
    setTradeButtonState("analyzing");
    setAnalyzing(true);
    setAnalysisError(null);
    setAnalysis(null);
    try {
      const ex = (selectedAccount?.exchange || exchange || "").toLowerCase();
      if (!ex) {
        setToast("Select a trading account (or connect an exchange) first");
        setAnalyzing(false);
        setTradeButtonState("disabled");
        return;
      }
      // tradingApi.analyze uses 90s timeout — default api client is 8s (too short for Claude + market data).
      const res = await tradingApi.analyze(symbol.trim(), ex, traderClass ?? undefined, {
        trading_account_id: selectedTradingAccountId ?? undefined,
        is_paper: selectedAccount?.is_paper ?? isPaper,
      });
      const payload = res.data?.data ?? res.data;
      setAnalysis(payload);
      setAnalysisError(null);
      const newState = applyAnalyzeResponseToTradeButton(payload, ex, symbol.trim());
      setTradeButtonState(newState);
    } catch (err: unknown) {
      setAnalysis(null);
      setAnalysisError(sanitizeApiError(err, "Analysis failed — please try again."));
      setTradeButtonState("data-unavailable");
    } finally {
      setAnalyzing(false);
    }
  }, [
    symbol,
    selectedAccount?.exchange,
    selectedAccount?.is_paper,
    exchange,
    selectedTradingAccountId,
    traderClass,
    isPaper,
  ]);

  useEffect(() => {
    setConfirmOpen(false);
    if (layout !== "C") return;
    setAnalysis(null);
    setAnalysisError(null);
    setAnalyzing(false);
    setTradeButtonState("disabled");
    setRetryCountdown(null);
  }, [symbol, layout]);

  useEffect(() => {
    if (layout !== "A" && layout !== "B") return;
    if (!symbol.trim()) {
      setAnalysis(null);
      setAnalysisError(null);
      setAnalyzing(false);
      setTradeButtonState("disabled");
      setRetryCountdown(null);
      return;
    }
    void handleAnalyse();
  }, [symbol, layout, handleAnalyse]);

  // Auto-retry when data is unavailable (30s countdown)
  useEffect(() => {
    if (tradeButtonState !== "data-unavailable") {
      setRetryCountdown(null);
      return;
    }
    let remaining = 30;
    setRetryCountdown(remaining);
    const tick = window.setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        window.clearInterval(tick);
        setRetryCountdown(null);
        void handleAnalyse();
      } else {
        setRetryCountdown(remaining);
      }
    }, 1000);
    return () => window.clearInterval(tick);
  }, [tradeButtonState, handleAnalyse]);

  // Class-aware defaults for Signal Stack mode + manual trade expansion
  useEffect(() => {
    if (!settings) return;
    const tc = settings.trader_class ?? "complete_novice";
    const defaultMode =
      tc === "experienced" || tc === "semi_institutional" ? "assisted" : "watch";
    setSignalMode(settings.execution_mode ?? defaultMode);
    const manualDefaultExpanded =
      tc === "experienced" || tc === "semi_institutional" || tc === "self_taught";
    setManualExpanded(manualDefaultExpanded);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings?.execution_mode, settings?.trader_class]);

  const explanationLevel = useMemo(() => {
    const level = settings?.explanation_level;
    if (level === "expert" || level === "simple" || level === "metaphor") return level;
    if (traderClass === "complete_novice" || traderClass === "curious_saver") return "simple";
    return "expert";
  }, [settings?.explanation_level, traderClass]);

  const stage = trust?.stage ?? 1;
  const guidedLocked = useMemo(() => stage < 3, [stage]);
  const autonomousLocked = useMemo(
    () => stage < 3 || !settings?.autonomous_mode_unlocked,
    [stage, settings?.autonomous_mode_unlocked],
  );

  const modeDescription = useMemo(() => {
    if (signalMode === "watch")
      return `${resolvedBotName} has pre-analysed assets. You review and click execute.`;
    if (signalMode === "assisted")
      return `${resolvedBotName} ranks 2–3 best options. You choose, then confirm.`;
    if (signalMode === "guided")
      return `${resolvedBotName} runs the full analysis. Auto-confirms when confidence ≥ threshold.`;
    return `${resolvedBotName} acts autonomously. 60 s undo window after each trade.`;
  }, [resolvedBotName, signalMode]);

  const { signals, isLoading: signalsLoading, isRefreshing, lastScanAt, nextScanInMinutes, assetsScanned, error: signalsError, acceptSignal, skipSignal, refresh } =
    useSignalStack({ execution_mode: signalMode }, { tradingAccountId: selectedTradingAccountId });

  const maxSignals = useMemo(() => {
    if (traderClass === "complete_novice") return 3;
    if (traderClass === "curious_saver") return 5;
    return 10;
  }, [traderClass]);

  const browseSignals = useMemo(() => signals.slice(0, maxSignals), [signals, maxSignals]);

  const handleSetMode = async (mode: "watch" | "assisted" | "guided" | "autonomous") => {
    if (mode === signalMode) return;
    if (mode === "guided" && guidedLocked) {
      setToast("Guided mode unlocks at Trust Ladder Stage 3.");
      return;
    }
    if (mode === "autonomous" && autonomousLocked) {
      setToast("Autonomous mode requires Stage 3 + explicit opt-in in Settings.");
      return;
    }
    setSignalMode(mode);
    setSettings((prev) => (prev ? { ...prev, execution_mode: mode } : prev));
    setModeSaving(true);
    try {
      await signalApi.updateSettings({ execution_mode: mode });
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
        setToast(`${resolvedBotName} is buying ${sig?.asset_name ?? "this asset"}`);
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

  // Debug isolation toggles (production-safe). Use:
  // - /trade?debug=bare to bypass complex UI and isolate child crashes (hooks still run).
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

  // onboarding_complete gate: only render the onboarding wizard full-screen
  if (isSignedIn && !loading && settings?.onboarding_complete === false) {
    return (
      <div className="relative">
        <BotOnboardingChat />
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

  const handleConfirmedTrade = async () => {
    const sym = symbol.trim();
    const ex = (selectedAccount?.exchange || exchange || "").toLowerCase();
    const derived = applyAnalyzeResponseToTradeButton(analysis, ex, sym);
    if (derived !== "ready") {
      setToast("Cannot execute — check the trade button state and try again.");
      setConfirmOpen(false);
      setTradeButtonState(derived);
      return;
    }
    const decision = String(analysis?.decision ?? analysis?.signal ?? "").toUpperCase();
    const conf = Number(analysis?.confidence ?? 0);
    if (decision === "WAIT" || decision === "" || (decision !== "BUY" && decision !== "SELL")) {
      setToast("No valid buy/sell signal — no order was placed.");
      setConfirmOpen(false);
      return;
    }
    if (!Number.isFinite(conf) || conf < TRADE_BUTTON_MIN_CONFIDENCE) {
      setToast("Confidence is below the minimum to execute.");
      setConfirmOpen(false);
      return;
    }
    // Crypto markets are 24/7 - skip market hours check for crypto assets
    const isCrypto = isCryptoAsset(sym);
    if (
      (analysis as { market_closed?: boolean } | null)?.market_closed === true ||
      (!isCrypto && isStocksTradingAsset(ex, sym) && !isUsEquityRegularSessionEt())
    ) {
      setToast("Market is closed — no order was placed.");
      setConfirmOpen(false);
      return;
    }
    const executeOpts = {
      trading_account_id: selectedTradingAccountId ?? undefined,
      is_paper: selectedAccount?.is_paper ?? isPaper,
      amount,
      side: decision,
    } as Parameters<typeof tradingApi.execute>[2] & { amount?: number; side?: string };
    let res: Awaited<ReturnType<typeof tradingApi.execute>>;
    try {
      if (!ex) throw new Error("Missing exchange");
      res = await tradingApi.execute(sym, ex, executeOpts);
    } catch (e: any) {
      setTradeButtonState("ready");
      const detail = e?.response?.data?.detail;
      if (detail === "onboarding_required") {
        // Server guard fired — clear local state and show wizard
        setSettings((prev) => ({ ...prev, onboarding_complete: false }));
        setToast("Please complete onboarding before trading.");
        return;
      }
      setToast(sanitizeApiError(e, "Trade failed — please try again."));
      return;
    }
    const data = res.data?.data ?? res.data;
    if (data?.status === "wait" || String(data?.decision ?? "").toUpperCase() === "WAIT") {
      setToast("Unitrader recommends waiting — no order was placed.");
      setTradeButtonState("ready");
    } else {
      setToast("Trade submitted");
      setTradeButtonState("disabled");
      setAnalysis(null);
      setAnalysisError(null);
    }
    await refreshOpenPositions({ silent: true });
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
        <CircuitBreakerAlert tradingPaused={tradingPaused} dailyLossPct={0} maxDailyLossPct={maxDailyLoss} botName={resolvedBotName} />
      </div>

      {/* eToro offer card — one-time dismissible banner for users with no
          connected exchange. Renders a no-op when the server-side gates
          don't all pass (feature flag, onboarding complete, etc.). */}
      <EtoroOfferCard />

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

      {/* Performance pulse banner */}
      <PerformancePulse />

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
            currencySymbol={currencySymbol}
            currencyCode={displayCurrencyCode}
            botName={resolvedBotName}
          />
        </div>
      )}

      {/* Never-hold trust bar */}
      <div className="mb-4">
        <NeverHoldBanner />
      </div>

      <UnitraderNotificationTicker botName={resolvedBotName} />

      {/* ── No exchange connected — onboarding CTA ─────────────────────────── */}
      {userContext?.no_exchange_connected && (
        <div className="mb-6 rounded-2xl border border-dark-800 bg-dark-950 p-6 text-center">
          <h2 className="mb-2 text-lg font-semibold text-white">Connect your first exchange to start trading</h2>
          <p className="mb-4 text-sm text-dark-300">
            Unitrader works with Alpaca (stocks), Coinbase (crypto), Binance, Kraken, and OANDA.
            Connect an exchange in Settings to unlock the AI Trader.
          </p>
          <Link
            href="/exchanges"
            className="inline-block rounded-xl bg-brand-500 px-6 py-3 text-sm font-semibold text-white hover:bg-brand-400 transition-colors"
          >
            Go to Exchanges
          </Link>
        </div>
      )}

      {/* ── Asset class toggle (multi-exchange users) ──────────────────────── */}
      {userContext && !userContext.no_exchange_connected && (userContext.available_asset_classes?.length ?? 0) > 1 && (
        <div className="mb-4 rounded-2xl border border-dark-800 bg-dark-950 p-3">
          <div className="flex gap-1 rounded-xl border border-dark-800 bg-dark-900 p-1">
            {userContext.available_asset_classes.map((ac) => (
              <button
                key={ac}
                type="button"
                onClick={async () => {
                  setActiveAssetClass(ac);
                  try {
                    const ucRes = await tradingApi.userContext({ asset_class: ac });
                    const uc = ucRes.data?.data ?? ucRes.data;
                    if (uc) {
                      setUserContext(uc);
                      if (uc.active_venue) {
                        setSelectedTradingAccountId(uc.active_venue.trading_account_id);
                        setExchange(uc.active_venue.exchange);
                      }
                    }
                  } catch {
                    // keep existing state
                  }
                }}
                className={clsx(
                  "rounded-lg px-4 py-2 text-xs font-semibold transition-all",
                  activeAssetClass === ac ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white",
                )}
              >
                {ac.charAt(0).toUpperCase() + ac.slice(1)}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Signal Stack: primary interface ─────────────────────────────────── */}
      {settings?.onboarding_complete === true && (
        <div className="mb-6">
          {/* Mode toggle */} 
          <div className="rounded-2xl border border-dark-800 bg-dark-950 p-3 mb-3">
            <div className="grid grid-cols-4 gap-1 rounded-xl border border-dark-800 bg-dark-900 p-1">
              <button
                type="button"
                onClick={() => handleSetMode("watch")}
                className={clsx(
                  "rounded-lg px-2 py-2 text-xs font-semibold transition-all",
                  signalMode === "watch" ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white",
                )}
              >
                Watch
              </button>
              <button
                type="button"
                onClick={() => handleSetMode("assisted")}
                className={clsx(
                  "rounded-lg px-2 py-2 text-xs font-semibold transition-all",
                  signalMode === "assisted" ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white",
                )}
              >
                Assisted
              </button>
              <button
                type="button"
                onClick={() => handleSetMode("guided")}
                title={guidedLocked ? "Unlocks at Trust Ladder Stage 3" : undefined}
                className={clsx(
                  "rounded-lg px-2 py-2 text-xs font-semibold transition-all",
                  signalMode === "guided" ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white",
                  guidedLocked && "opacity-50 cursor-not-allowed",
                )}
                disabled={guidedLocked}
              >
                Guided
              </button>
              <button
                type="button"
                onClick={() => handleSetMode("autonomous")}
                title={autonomousLocked ? "Stage 3 + Settings opt-in required" : undefined}
                className={clsx(
                  "rounded-lg px-2 py-2 text-xs font-semibold transition-all",
                  signalMode === "autonomous" ? "bg-brand-500 text-white" : "text-dark-400 hover:text-white",
                  autonomousLocked && "opacity-50 cursor-not-allowed",
                )}
                disabled={autonomousLocked}
              >
                Autonomous
              </button>
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-dark-400">
              <span>{modeDescription}</span>
              {modeSaving && <span className="text-dark-500">Saving…</span>}
            </div>
          </div>

          {/* Panel */}
          {signalMode === "watch" && (
            <BrowseStack
              botName={resolvedBotName}
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
          {signalMode === "assisted" && (
            <BotSelectsPanel
              botName={resolvedBotName}
              userSettings={settings ?? {}}
              tradingAccountId={selectedTradingAccountId}
              currencySymbol={currencySymbol}
              onExecute={async (ids) => {
                for (const id of ids) {
                  await handleAcceptSignal(id);
                }
              }}
            />
          )}
          {signalMode === "guided" && (
            <GuidedPanel
              botName={resolvedBotName}
              userSettings={settings ?? {}}
              trustLadderStage={trust?.stage ?? 1}
              tradingAccountId={selectedTradingAccountId}
              currencySymbol={currencySymbol}
              onExecute={handleAcceptSignal}
              onSettingsUpdate={(updates: object) => setSettings((prev) => (prev ? { ...prev, ...(updates as any) } : prev))}
            />
          )}
          {signalMode === "autonomous" && (
            <FullAutoPanel
              botName={resolvedBotName}
              userSettings={settings ?? {}}
              trustLadderStage={trust?.stage ?? 1}
              exchange={exchange}
              tradingAccountId={selectedTradingAccountId}
              isPaper={selectedAccount?.is_paper ?? isPaper}
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

      {/* ── Manual Trade (prominent section) ─────────────────────────────────── */}
      <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-white">Manual Trade</h2>
            <p className="text-xs text-dark-400 mt-1">Select an asset and analyse with AI</p>
          </div>
          <div className="rounded-lg border border-dark-800 bg-dark-900 px-3 py-2 text-xs">
            <span className="text-dark-400">Account:</span>{" "}
            <span className="font-semibold text-white">
              {userContext?.active_venue?.display_label ||
                (selectedAccount
                  ? selectedAccount.account_label?.trim() ||
                    `${String(selectedAccount.exchange).toUpperCase()} \u00b7 ${selectedAccount.is_paper ? "Paper" : "Live"}`
                  : `${(activeAssetClass || "stocks").charAt(0).toUpperCase() + (activeAssetClass || "stocks").slice(1)} \u00b7 ${isPaper ? "Paper" : "Live"}`)}
            </span>
          </div>
        </div>

        {/* Asset Class Selector (if multiple available) */}
        {userContext && !userContext.no_exchange_connected && (userContext.available_asset_classes?.length ?? 0) > 1 && (
          <div className="mb-4">
            <div className="flex gap-2">
              {userContext.available_asset_classes.map((ac) => {
                const isActive = activeAssetClass === ac;
                const icon = ac === "crypto" ? "₿" : ac === "forex" ? "£" : "📈";
                return (
                  <button
                    key={ac}
                    type="button"
                    onClick={async () => {
                      setActiveAssetClass(ac);
                      try {
                        const ucRes = await tradingApi.userContext({ asset_class: ac });
                        const uc = ucRes.data?.data ?? ucRes.data;
                        if (uc) {
                          setUserContext(uc);
                          if (uc.active_venue) {
                            setSelectedTradingAccountId(uc.active_venue.trading_account_id);
                            setExchange(uc.active_venue.exchange);
                          }
                        }
                      } catch {
                        // keep existing state
                      }
                    }}
                    className={clsx(
                      "flex-1 rounded-xl border px-4 py-3 text-sm font-semibold transition-all",
                      isActive
                        ? ac === "crypto"
                          ? "border-orange-500/50 bg-orange-500/10 text-orange-400"
                          : ac === "forex"
                            ? "border-purple-500/50 bg-purple-500/10 text-purple-400"
                            : "border-emerald-500/50 bg-emerald-500/10 text-emerald-400"
                        : "border-dark-800 bg-dark-900 text-dark-400 hover:border-dark-700 hover:text-white"
                    )}
                  >
                    <span className="mr-2">{icon}</span>
                    {ac.charAt(0).toUpperCase() + ac.slice(1)}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Layout sections */}
        <div>
            {/* Layout A */}
            {layout === "A" && (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-4">
                  {!dbg("no_picker") && (
                    <BrandPicker
                      exchange={exchange}
                      currencySymbol={currencySymbol}
                      tradingAccountId={selectedTradingAccountId}
                      traderClass={traderClass}
                      favourites={settings?.approved_assets ?? []}
                      selectionMode="single"
                      onManualSymbol={(s) => setSymbol(s.toUpperCase())}
                      onChangeSelectedSymbols={(syms) => setSymbol((syms[0] || "").toUpperCase())}
                      selectedSymbols={symbol ? [symbol] : []}
                      assetClass={activeAssetClass as "stocks" | "crypto" | "forex" | undefined}
                      botName={resolvedBotName}
                    />
                  )}
                  <AmountInput
                    value={amount}
                    onChange={setAmount}
                    min={amountLimits.min}
                    max={amountLimits.max}
                    step={amountLimits.step}
                    label={amountSliderLabel}
                    currencySymbol={currencySymbol}
                    helperText={amountHelperText}
                  />
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

                <AIAnalysisCard
                  botName={resolvedBotName}
                  symbol={symbol}
                  analysis={analysis}
                  analyzing={analyzing}
                  analysisError={analysisError}
                  signalStatus={tradeButtonState}
                  onRetry={handleAnalyse}
                  showExplanationToggle={!dbg("no_explain")}
                  showPendingAnalyseHint={false}
                  traderClass={traderClass}
                  settingsExplanationLevel={settingsExplanationLevel}
                >
                  <ManualTradeExecuteButton
                    tradeButtonState={tradeButtonState}
                    retryCountdown={retryCountdown}
                    onExecute={() => {
                      setTradeButtonState("analyzing");
                      setConfirmOpen(true);
                    }}
                  />
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
                      currencySymbol={currencySymbol}
                      tradingAccountId={selectedTradingAccountId}
                      traderClass={traderClass}
                      favourites={settings?.approved_assets ?? []}
                      selectionMode="single"
                      onManualSymbol={(s) => setSymbol(s.toUpperCase())}
                      onChangeSelectedSymbols={(syms) => setSymbol((syms[0] || "").toUpperCase())}
                      selectedSymbols={symbol ? [symbol] : []}
                      assetClass={activeAssetClass as "stocks" | "crypto" | "forex" | undefined}
                      botName={resolvedBotName}
                    />
                  )}
                  {symbol && (
                    <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                      {!dbg("no_chart") && <PriceChart symbol={symbol} traderClass="self_taught" signal="NONE" tradeMarkers={activeTradeMarkers} />}
                    </div>
                  )}
                  <AmountInput
                    value={amount}
                    onChange={setAmount}
                    min={amountLimits.min}
                    max={amountLimits.max}
                    step={amountLimits.step}
                    label={amountSliderLabel}
                    currencySymbol={currencySymbol}
                    helperText={amountHelperText}
                  />
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
                  <AIAnalysisCard
                    botName={resolvedBotName}
                    symbol={symbol}
                    title="AI analysis"
                    analysis={analysis}
                    analyzing={analyzing}
                    analysisError={analysisError}
                    signalStatus={tradeButtonState}
                    onRetry={handleAnalyse}
                    showExplanationToggle={!dbg("no_explain")}
                    showPendingAnalyseHint={false}
                    traderClass={traderClass}
                    settingsExplanationLevel={settingsExplanationLevel}
                  >
                    <ManualTradeExecuteButton
                      tradeButtonState={tradeButtonState}
                      retryCountdown={retryCountdown}
                      onExecute={() => {
                        setTradeButtonState("analyzing");
                        setConfirmOpen(true);
                      }}
                    />
                  </AIAnalysisCard>

                  <OpenPositionsPanel
                    loading={openPositionsLoading}
                    positions={openPositionsRows}
                    variant="compact"
                  />
                </div>
              </div>
            )}

            {/* Layout C — experienced */}
            {layout === "C" && (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-4">
                  <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                    <div className="text-xs font-semibold text-white">Trading account</div>
                    {accounts.length > 0 ? (
                      <select
                        value={selectedTradingAccountId ?? ""}
                        onChange={(e) => onSelectTradingAccount(e.target.value || null)}
                        className="mt-2 w-full rounded-xl border border-dark-800 bg-dark-900 px-3 py-2 text-sm text-white"
                      >
                        {accounts.map((a) => (
                          <option key={a.trading_account_id} value={a.trading_account_id}>
                            {a.account_label ||
                              `${a.exchange} ${
                                String(a.exchange || "").toLowerCase() === "coinbase"
                                  ? "Live"
                                  : a.is_paper
                                    ? "Paper"
                                    : "Live"
                              }`}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <select
                        value={exchange}
                        onChange={(e) => setExchange(e.target.value)}
                        className="mt-2 w-full rounded-xl border border-dark-800 bg-dark-900 px-3 py-2 text-sm text-white"
                      >
                        <option value="" disabled>
                          Select exchange…
                        </option>
                        <option value="alpaca">Alpaca — Stocks & ETFs</option>
                        <option value="coinbase">Coinbase — Crypto</option>
                        <option value="binance">Binance — Crypto</option>
                        <option value="kraken">Kraken — Crypto</option>
                        <option value="oanda">OANDA — Forex</option>
                      </select>
                    )}
                    {accounts.length === 0 && (
                      <div className="mt-2 text-[11px] text-dark-400">
                        Browse mode only. Connect an exchange to execute trades.
                      </div>
                    )}
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
                      {!dbg("no_chart") && <PriceChart symbol={symbol} traderClass="experienced" signal="NONE" tradeMarkers={activeTradeMarkers} />}
                    </div>
                  )}

                  <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                    <div className="text-xs font-semibold text-white">Order summary</div>
                    <dl className="mt-3 space-y-2 text-xs text-dark-300">
                      <div className="flex justify-between gap-3">
                        <dt>Notional</dt>
                        <dd className="font-medium text-white tabular-nums">
                          {currencySymbol}
                          {amount}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt>Mode</dt>
                        <dd className="font-medium text-white">
                          {(selectedAccount?.is_paper ?? isPaper) ? "Paper" : "Live"}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt>Risk</dt>
                        <dd className="text-right">Stop-loss and take-profit from analysis</dd>
                      </div>
                    </dl>
                    <Link
                      href="/settings"
                      className="mt-3 inline-block text-[11px] font-medium text-cyan-400 hover:underline"
                    >
                      Trading preferences in Settings
                    </Link>
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
                  <AIAnalysisCard
                    botName={resolvedBotName}
                    symbol={symbol}
                    title="AI analysis (technical)"
                    analysis={analysis}
                    analyzing={analyzing}
                    analysisError={analysisError}
                    signalStatus={tradeButtonState}
                    onRetry={handleAnalyse}
                    showExplanationToggle
                    traderClass={traderClass}
                    settingsExplanationLevel={settingsExplanationLevel}
                  >
                    <ManualTradeExecuteButton
                      tradeButtonState={tradeButtonState}
                      retryCountdown={retryCountdown}
                      onExecute={() => {
                        setTradeButtonState("analyzing");
                        setConfirmOpen(true);
                      }}
                    />
                  </AIAnalysisCard>

                  <OpenPositionsPanel
                    loading={openPositionsLoading}
                    positions={openPositionsRows}
                    variant="detailed"
                  />
                </div>
              </div>
            )}
        </div>
      </div>

      {/* Mandatory confirm modal for all layouts */}
      <TradeConfirmModal
        isOpen={confirmOpen}
        onClose={() => {
          setConfirmOpen(false);
          setTradeButtonState((s) => (s === "analyzing" ? "ready" : s));
        }}
        onConfirm={async () => {
          await handleConfirmedTrade();
        }}
        trade={{
          ...analysis,
          symbol,
        }}
        notionalAmount={amount}
        currencySymbol={currencySymbol}
        isPaper={isPaper}
        traderClass={traderClass}
        botName={resolvedBotName}
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
