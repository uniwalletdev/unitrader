"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Lock, Loader2, CheckCircle, AlertTriangle, TrendingUp, TrendingDown, Info } from "lucide-react";
import { signalApi, tradingApi } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface UserSettings {
  guided_confidence_threshold?: number;
  apex_selects_max_trades?: number;
  apex_selects_asset_classes?: string[];
  watchlist?: string[];
  trader_class?: string;
  execution_mode?: string;
}

interface GuidedPanelProps {
  botName: string;
  userSettings: UserSettings;
  trustLadderStage: number;
  tradingAccountId?: string | null;
  currencySymbol?: string;
  onExecute: (signalId: string) => Promise<boolean>;
  onSettingsUpdate: (updates: object) => void;
}

interface SignalRow {
  id: string;
  symbol: string;
  asset_name?: string;
  signal: "buy" | "sell" | "hold";
  confidence: number;
  reasoning_simple?: string;
  current_price?: number;
  price_change_24h?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function confidenceColour(c: number): string {
  if (c >= 85) return "text-emerald-400";
  if (c >= 70) return "text-yellow-400";
  return "text-dark-400";
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export default function GuidedPanel({
  botName,
  userSettings,
  trustLadderStage,
  tradingAccountId,
  currencySymbol = "$",
  onExecute,
  onSettingsUpdate,
}: GuidedPanelProps) {
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [threshold, setThreshold] = useState(() => userSettings.guided_confidence_threshold ?? 70);
  const [thresholdSaving, setThresholdSaving] = useState(false);
  const [executing, setExecuting] = useState<string | null>(null);
  const [reviewCard, setReviewCard] = useState<SignalRow | null>(null);
  const sliderDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Fetch signals above threshold ──────────────────────────────────────────
  const fetchSignals = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | null | undefined> = {};
      if (tradingAccountId) params.trading_account_id = tradingAccountId;
      const res = await signalApi.stack(params.trading_account_id ? { trading_account_id: params.trading_account_id } : {});
      const raw: SignalRow[] = Array.isArray(res.data?.data?.signals)
        ? res.data.data.signals
        : Array.isArray(res.data?.signals)
        ? res.data.signals
        : [];
      setSignals(raw.filter((s) => s.confidence >= threshold));
    } catch {
      setSignals([]);
    } finally {
      setLoading(false);
    }
  }, [tradingAccountId, threshold]);

  useEffect(() => {
    fetchSignals();
  }, [fetchSignals]);

  // ── Threshold slider persistence ───────────────────────────────────────────
  const persistThreshold = (val: number) => {
    if (sliderDebounce.current) clearTimeout(sliderDebounce.current);
    sliderDebounce.current = setTimeout(async () => {
      setThresholdSaving(true);
      try {
        await signalApi.updateSettings({ guided_confidence_threshold: val });
        onSettingsUpdate({ guided_confidence_threshold: val });
      } catch {
        // non-fatal
      } finally {
        setThresholdSaving(false);
      }
    }, 600);
  };

  const handleThresholdChange = (val: number) => {
    setThreshold(val);
    persistThreshold(val);
  };

  // ── Auto-confirm or show review card ───────────────────────────────────────
  const handleSignal = async (sig: SignalRow) => {
    if (sig.confidence >= threshold) {
      // Auto-confirm
      setExecuting(sig.id);
      await onExecute(sig.id);
      setExecuting(null);
    } else {
      // Below threshold — show review card
      setReviewCard(sig);
    }
  };

  const handleForceExecute = async () => {
    if (!reviewCard) return;
    setExecuting(reviewCard.id);
    await onExecute(reviewCard.id);
    setExecuting(null);
    setReviewCard(null);
  };

  // ── Locked ─────────────────────────────────────────────────────────────────
  if (trustLadderStage < 3) {
    return (
      <div className="rounded-2xl border border-dark-700 bg-dark-900 p-6 flex flex-col items-center gap-4 text-center">
        <div className="w-12 h-12 rounded-full bg-dark-800 border border-dark-600 flex items-center justify-center">
          <Lock className="w-5 h-5 text-dark-400" />
        </div>
        <div>
          <p className="text-base font-semibold text-white">Guided mode is locked</p>
          <p className="text-sm text-dark-400 mt-1 max-w-xs mx-auto">
            Complete the Trust Ladder to Stage 3. {botName} will then auto-confirm trades that meet
            your confidence threshold.
          </p>
        </div>
        <div className="w-full rounded-xl border border-dark-700 bg-dark-800 px-4 py-3 flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-xs">
            <span className="text-dark-400">Progress</span>
            <span className="text-dark-300 font-medium">Stage {trustLadderStage} of 3</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-dark-700 overflow-hidden">
            <div
              className="h-full rounded-full bg-brand-500 transition-all duration-500"
              style={{ width: `${(trustLadderStage / 3) * 100}%` }}
            />
          </div>
        </div>
      </div>
    );
  }

  // ── Review card (below-threshold signal) ───────────────────────────────────
  if (reviewCard) {
    return (
      <div className="rounded-2xl border border-yellow-500/30 bg-yellow-500/5 p-5 flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-yellow-400 flex-shrink-0" />
          <p className="text-sm font-semibold text-yellow-300">Review required — confidence below threshold</p>
        </div>
        <div className="rounded-xl border border-dark-700 bg-dark-900 p-4 flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-white">{reviewCard.asset_name ?? reviewCard.symbol}</span>
            <span className={`text-xs font-bold ${confidenceColour(reviewCard.confidence)}`}>
              {reviewCard.confidence}% confidence
            </span>
          </div>
          {reviewCard.reasoning_simple && (
            <p className="text-xs text-dark-300">{reviewCard.reasoning_simple}</p>
          )}
          <div className="flex items-center gap-1 mt-1">
            <Info className="w-3 h-3 text-dark-500" />
            <span className="text-[11px] text-dark-500">
              Threshold is {threshold}% — {Math.round(threshold - reviewCard.confidence)}% below
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleForceExecute}
            disabled={executing === reviewCard.id}
            className="flex-1 rounded-xl bg-brand-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-400 transition-colors disabled:opacity-50"
          >
            {executing === reviewCard.id ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : "Execute anyway"}
          </button>
          <button
            onClick={() => setReviewCard(null)}
            className="rounded-xl border border-dark-700 px-4 py-2.5 text-sm text-dark-400 hover:text-white transition-colors"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  // ── Main panel ─────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4">

      {/* ── Threshold control ──────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-dark-700 bg-dark-900 p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <label className="text-xs font-medium text-dark-300">Auto-confirm threshold</label>
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-white">{threshold}%</span>
            {thresholdSaving && <Loader2 className="w-3 h-3 animate-spin text-dark-500" />}
          </div>
        </div>
        <input
          type="range"
          min={50}
          max={95}
          step={5}
          value={threshold}
          onChange={(e) => handleThresholdChange(Number(e.target.value))}
          className="w-full accent-brand-500"
        />
        <p className="text-[11px] text-dark-500">
          Signals ≥ {threshold}% auto-confirm and execute. Below this you'll see a review card first.
        </p>
      </div>

      {/* ── Signal list ────────────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-dark-700 bg-dark-900 p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-white">Qualifying signals</p>
          <button
            onClick={fetchSignals}
            className="text-[11px] text-dark-400 hover:text-white transition-colors"
          >
            Refresh
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 animate-spin text-dark-400" />
          </div>
        ) : signals.length === 0 ? (
          <div className="rounded-xl border border-dark-700 bg-dark-800 px-4 py-5 text-center">
            <p className="text-sm text-dark-300">No signals meet your {threshold}% threshold right now.</p>
            <p className="text-xs text-dark-500 mt-1">Lower the threshold or check back after the next scan.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {signals.map((sig) => (
              <div key={sig.id} className="rounded-xl border border-dark-700 bg-dark-800 p-3 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    {sig.signal === "buy" ? (
                      <TrendingUp className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                    ) : (
                      <TrendingDown className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
                    )}
                    <span className="text-xs font-semibold text-white truncate">
                      {sig.asset_name ?? sig.symbol}
                    </span>
                  </div>
                  {sig.reasoning_simple && (
                    <p className="text-[11px] text-dark-400 mt-0.5 line-clamp-1">{sig.reasoning_simple}</p>
                  )}
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className={`text-xs font-bold tabular-nums ${confidenceColour(sig.confidence)}`}>
                    {sig.confidence}%
                  </span>
                  <button
                    onClick={() => handleSignal(sig)}
                    disabled={executing === sig.id}
                    className="rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-400 transition-colors disabled:opacity-50"
                  >
                    {executing === sig.id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : sig.confidence >= threshold ? (
                      <span className="flex items-center gap-1">
                        <CheckCircle className="w-3 h-3" /> Auto
                      </span>
                    ) : (
                      "Review"
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
