"use client";

import { useState } from "react";
import { Loader2, TrendingUp, TrendingDown, Minus, CheckCircle, AlertCircle } from "lucide-react";
import { Signal } from "@/hooks/useSignalStack";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

type ExplanationLevel = "expert" | "simple" | "metaphor";

interface SignalCardProps {
  botName: string;
  signal: Signal;
  traderClass: string;
  explanationLevel: ExplanationLevel;
  onAccept: (id: string) => Promise<boolean>;
  onSkip: (id: string) => void;
  isExecuting: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function assetClassLabel(ac: string): string {
  const map: Record<string, string> = {
    stocks: "Stocks",
    crypto: "Crypto",
    forex: "Forex",
    commodity: "Commodities",
  };
  return map[ac] ?? ac;
}

function exchangeLabel(ex: string): string {
  const map: Record<string, string> = {
    alpaca: "Alpaca",
    coinbase: "Coinbase",
    binance: "Binance",
    kraken: "Kraken",
    oanda: "OANDA",
  };
  return map[ex.toLowerCase()] ?? ex;
}

function rsiColour(rsi: number): string {
  if (rsi < 40) return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
  if (rsi > 70) return "bg-red-500/20 text-red-400 border-red-500/30";
  return "bg-dark-700 text-dark-300 border-dark-600";
}

function signalBadge(signal: string): { classes: string; icon: React.ReactNode; label: string } {
  if (signal === "buy")
    return {
      classes: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
      icon: <TrendingUp className="w-3 h-3" />,
      label: "BUY",
    };
  if (signal === "sell")
    return {
      classes: "bg-red-500/20 text-red-400 border-red-500/40",
      icon: <TrendingDown className="w-3 h-3" />,
      label: "SELL",
    };
  return {
    classes: "bg-amber-500/20 text-amber-400 border-amber-500/40",
    icon: <Minus className="w-3 h-3" />,
    label: "WATCH",
  };
}

function communityBarColour(pct: number): string {
  if (pct > 60) return "bg-emerald-500";
  if (pct >= 40) return "bg-amber-500";
  return "bg-dark-600";
}

function cardTintClasses(signal: Signal): string {
  if (signal.interaction === "accepted" || signal.interaction === "traded") {
    return "ring-1 ring-emerald-500/30 bg-emerald-950/20";
  }
  if (signal.signal === "watch") {
    return "ring-1 ring-amber-500/30 bg-amber-950/10";
  }
  return "";
}

function formatPrice(price: number): string {
  if (price >= 1000) return `$${price.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  if (price >= 1) return `$${price.toFixed(2)}`;
  return `$${price.toFixed(6)}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export default function SignalCard({
  botName,
  signal,
  explanationLevel,
  onAccept,
  onSkip,
  isExecuting,
}: SignalCardProps) {
  const [activeTab, setActiveTab] = useState<ExplanationLevel>(explanationLevel);
  const [executing, setExecuting] = useState(false);
  const [executed, setExecuted] = useState(false);
  const [execError, setExecError] = useState<string | null>(null);

  // Skipped cards are hidden entirely — parent AnimatePresence handles the exit
  if (signal.interaction === "skipped") return null;

  const badge = signalBadge(signal.signal);
  const tint = cardTintClasses(signal);

  const reasoningText =
    activeTab === "expert"
      ? signal.reasoning_expert
      : activeTab === "simple"
      ? signal.reasoning_simple
      : signal.reasoning_metaphor;

  const alreadyActioned =
    executed || signal.interaction === "accepted" || signal.interaction === "traded";

  const handleAccept = async () => {
    setExecError(null);
    setExecuting(true);
    const ok = await onAccept(signal.id);
    setExecuting(false);
    if (ok) {
      setExecuted(true);
    } else {
      setExecError("Trade failed. Please try again.");
    }
  };

  const priceChange = signal.price_change_24h;
  const changeColour = priceChange >= 0 ? "text-emerald-400" : "text-red-400";
  const changePrefix = priceChange >= 0 ? "+" : "";

  const tabs: { key: ExplanationLevel; label: string }[] = [
    { key: "expert", label: "Expert" },
    { key: "simple", label: "Simple" },
    { key: "metaphor", label: "Explain like I'm 5" },
  ];

  return (
    <div
      className={`rounded-2xl border border-dark-700 bg-dark-900 p-4 flex flex-col gap-3 transition-all duration-200 ${tint}`}
    >
      {/* ── Top row ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          {/* Asset icon */}
          <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-brand-500/20 border border-brand-500/30 flex items-center justify-center">
            <span className="text-sm font-bold text-brand-400">
              {signal.asset_name.charAt(0).toUpperCase()}
            </span>
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white truncate">{signal.asset_name}</p>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-dark-400">{formatPrice(signal.current_price)}</span>
              <span className={changeColour}>
                {changePrefix}{priceChange.toFixed(2)}%
              </span>
            </div>
          </div>
        </div>

        {/* Signal badge + confidence */}
        <div className="flex-shrink-0 flex flex-col items-end gap-1">
          <span
            className={`flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-bold ${badge.classes}`}
          >
            {badge.icon}
            {badge.label}
          </span>
          <span className="text-[11px] text-dark-400">
            <span className="text-white font-medium">{signal.confidence}%</span> confidence
          </span>
        </div>
      </div>

      {/* ── Tag pills ───────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="px-2 py-0.5 rounded-full border border-dark-600 bg-dark-800 text-[11px] text-dark-300">
          {assetClassLabel(signal.asset_class)}
        </span>
        <span className="px-2 py-0.5 rounded-full border border-dark-600 bg-dark-800 text-[11px] text-dark-300">
          {exchangeLabel(signal.exchange)}
        </span>
        {signal.rsi !== null && (
          <span
            className={`px-2 py-0.5 rounded-full border text-[11px] font-medium ${rsiColour(signal.rsi)}`}
          >
            RSI {signal.rsi.toFixed(0)}
          </span>
        )}
      </div>

      {/* ── Reasoning ───────────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-2">
        {/* Explanation level tabs */}
        <div className="flex items-center gap-1 bg-dark-800 rounded-lg p-1 w-fit">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                activeTab === tab.key
                  ? "bg-dark-600 text-white"
                  : "text-dark-400 hover:text-dark-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <p className="text-sm text-dark-200 leading-relaxed line-clamp-3">{reasoningText}</p>
      </div>

      {/* ── Community bar ───────────────────────────────────────────────────── */}
      {signal.community_pct !== null && (
        <div className="flex flex-col gap-1.5">
          <div className="h-1.5 w-full rounded-full bg-dark-700 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${communityBarColour(signal.community_pct)}`}
              style={{ width: `${signal.community_pct}%` }}
            />
          </div>
          <p className="text-[11px] text-dark-400">
            <span className="text-dark-300 font-medium">{signal.community_pct.toFixed(0)}%</span>
            {" "}of Unitrader users accepted similar signals
          </p>
        </div>
      )}

      {/* ── Action area ─────────────────────────────────────────────────────── */}
      {alreadyActioned ? (
        <div className="flex items-center gap-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 px-3 py-2.5">
          <CheckCircle className="w-4 h-4 text-emerald-400 flex-shrink-0" />
          <span className="text-sm text-emerald-300 font-medium">
            Trade executed — {botName} is watching
          </span>
        </div>
      ) : signal.signal === "watch" ? (
        <div className="flex items-center gap-2 rounded-xl bg-amber-500/10 border border-amber-500/20 px-3 py-2.5">
          <Minus className="w-4 h-4 text-amber-400 flex-shrink-0" />
          <span className="text-sm text-amber-300">Below threshold — {botName} is watching only</span>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {execError && (
            <div className="flex items-center gap-2 text-xs text-red-400">
              <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
              {execError}
            </div>
          )}
          <div className="flex gap-2">
            <button
              onClick={() => onSkip(signal.id)}
              className="flex-1 py-2 rounded-xl border border-dark-600 bg-transparent text-dark-300 text-sm font-medium hover:bg-dark-800 hover:text-white transition-all"
            >
              Skip
            </button>
            <button
              onClick={handleAccept}
              disabled={executing || isExecuting}
              className="flex-1 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-semibold flex items-center justify-center gap-2 transition-all"
            >
              {executing || isExecuting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : null}
              Let {botName} trade this
            </button>
          </div>
        </div>
      )}

      {/* ── Disclaimer ──────────────────────────────────────────────────────── */}
      <p className="text-[10px] text-dark-500 text-center">
        Not financial advice. Trading involves risk.
      </p>
    </div>
  );
}
