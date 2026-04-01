"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Loader2, TrendingUp, TrendingDown, Minus, CheckCircle, SlidersHorizontal } from "lucide-react";
import { api } from "@/lib/api";
import { Signal } from "@/hooks/useSignalStack";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface UserSettings {
  apex_selects_threshold?: number;
  apex_selects_max_trades?: number;
  apex_selects_asset_classes?: string[];
  max_trade_amount?: number;
}

interface BotSelectsPanelProps {
  botName: string;
  userSettings: UserSettings;
  onExecute: (signalIds: string[]) => Promise<void>;
}

const ALL_ASSET_CLASSES = ["stocks", "crypto", "forex", "commodities"] as const;
const ASSET_CLASS_LABELS: Record<string, string> = {
  stocks: "Stocks",
  crypto: "Crypto",
  forex: "Forex",
  commodities: "Commodities",
};

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function DirectionBadge({ direction }: { direction: string }) {
  if (direction === "buy")
    return (
      <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold">
        <TrendingUp className="w-2.5 h-2.5" />
        BUY
      </span>
    );
  if (direction === "sell")
    return (
      <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30 text-[10px] font-bold">
        <TrendingDown className="w-2.5 h-2.5" />
        SELL
      </span>
    );
  return (
    <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30 text-[10px] font-bold">
      <Minus className="w-2.5 h-2.5" />
      WATCH
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export default function BotSelectsPanel({ botName, userSettings, onExecute }: BotSelectsPanelProps) {
  const [shortlist, setShortlist] = useState<Signal[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isExecuting, setIsExecuting] = useState(false);
  const [done, setDone] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const [threshold, setThreshold] = useState(userSettings.apex_selects_threshold ?? 75);
  const [maxTrades, setMaxTrades] = useState(userSettings.apex_selects_max_trades ?? 3);
  const [assetClasses, setAssetClasses] = useState<string[]>(
    userSettings.apex_selects_asset_classes ?? ["stocks", "crypto"]
  );

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchShortlist = useCallback(async (t: number, m: number, ac: string[]) => {
    setIsLoading(true);
    try {
      const params = new URLSearchParams({
        threshold: String(t),
        max_trades: String(m),
        asset_classes: ac.join(","),
      });
      const res = await api.get(`/api/signals/apex-selects?${params}`);
      setShortlist(res.data?.signals ?? []);
    } catch {
      setShortlist([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Debounced reload when settings change
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchShortlist(threshold, maxTrades, assetClasses);
    }, 800);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [threshold, maxTrades, assetClasses, fetchShortlist]);

  const toggleAssetClass = (ac: string) => {
    setAssetClasses((prev) =>
      prev.includes(ac) ? prev.filter((x) => x !== ac) : [...prev, ac]
    );
  };

  const handleExecute = async () => {
    setShowConfirm(false);
    setIsExecuting(true);
    await onExecute(shortlist.map((s) => s.id));
    setIsExecuting(false);
    setDone(true);
  };

  const maxAmount = userSettings.max_trade_amount ?? 100;
  const plural = shortlist.length !== 1 ? "s" : "";

  return (
    <div className="flex flex-col gap-5">

      {/* ── Settings section ──────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-dark-700 bg-dark-900 p-4 flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="w-4 h-4 text-dark-400" />
          <span className="text-sm font-semibold text-white">Filter settings</span>
        </div>

        {/* Confidence threshold slider */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label className="text-xs text-dark-300 font-medium">Minimum confidence</label>
            <span className="text-xs font-bold text-white">{threshold}%</span>
          </div>
          <input
            type="range"
            min={60}
            max={95}
            step={5}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full accent-emerald-500"
          />
          <div className="flex justify-between text-[10px] text-dark-500">
            <span>60%</span>
            <span>95%</span>
          </div>
        </div>

        {/* Max trades slider */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label className="text-xs text-dark-300 font-medium">Max trades {botName} can place</label>
            <span className="text-xs font-bold text-white">{maxTrades}</span>
          </div>
          <input
            type="range"
            min={1}
            max={5}
            step={1}
            value={maxTrades}
            onChange={(e) => setMaxTrades(Number(e.target.value))}
            className="w-full accent-emerald-500"
          />
          <div className="flex justify-between text-[10px] text-dark-500">
            <span>1</span>
            <span>5</span>
          </div>
        </div>

        {/* Asset class toggles */}
        <div className="flex flex-col gap-2">
          <label className="text-xs text-dark-300 font-medium">Asset classes</label>
          <div className="flex flex-wrap gap-2">
            {ALL_ASSET_CLASSES.map((ac) => {
              const active = assetClasses.includes(ac);
              return (
                <button
                  key={ac}
                  onClick={() => toggleAssetClass(ac)}
                  className={`px-3 py-1.5 rounded-full border text-xs font-medium transition-all ${
                    active
                      ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300"
                      : "bg-dark-800 border-dark-600 text-dark-400 hover:text-dark-200"
                  }`}
                >
                  {ASSET_CLASS_LABELS[ac]}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── Shortlist section ─────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-dark-700 bg-dark-900 p-4 flex flex-col gap-3">
        <div>
          <p className="text-sm font-semibold text-white">{botName}&apos;s shortlist for you</p>
          <p className="text-xs text-dark-400 mt-0.5">
            {isLoading ? "Loading…" : `${shortlist.length} signal${plural} qualify at ${threshold}%+`}
          </p>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-dark-400" />
          </div>
        ) : shortlist.length === 0 ? (
          <div className="rounded-xl border border-dark-700 bg-dark-800 px-4 py-6 text-center">
            <p className="text-sm text-dark-300">
              No signals meet your {threshold}% threshold right now.
            </p>
            <p className="text-xs text-dark-500 mt-1">
              Try lowering the threshold or check back after the next scan.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {shortlist.map((s) => (
              <div
                key={s.id}
                className="flex items-center gap-3 rounded-xl border border-dark-700 bg-dark-800 px-3 py-2.5"
              >
                {/* Icon */}
                <div className="flex-shrink-0 w-7 h-7 rounded-lg bg-brand-500/20 border border-brand-500/30 flex items-center justify-center">
                  <span className="text-[11px] font-bold text-brand-400">
                    {s.asset_name.charAt(0).toUpperCase()}
                  </span>
                </div>

                {/* Name + badge */}
                <div className="flex-1 min-w-0 flex items-center gap-2">
                  <span className="text-sm font-medium text-white truncate">{s.asset_name}</span>
                  <DirectionBadge direction={s.signal} />
                </div>

                {/* Confidence */}
                <span className="flex-shrink-0 text-xs font-bold text-white">
                  {s.confidence}%
                </span>

                {/* Amount */}
                <span className="flex-shrink-0 text-xs text-dark-400">
                  £{maxAmount}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Confirmation overlay ──────────────────────────────────────────── */}
      {showConfirm && (
        <div className="rounded-2xl border border-dark-600 bg-dark-800 p-4 flex flex-col gap-3">
          <p className="text-sm font-semibold text-white">
            {botName} will place {shortlist.length} trade{plural}:
          </p>
          <ul className="flex flex-col gap-1">
            {shortlist.map((s) => (
              <li key={s.id} className="text-xs text-dark-300 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
                {s.asset_name} ({s.signal.toUpperCase()}) — {s.confidence}% confidence
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <button
              onClick={() => setShowConfirm(false)}
              className="flex-1 py-2 rounded-xl border border-dark-600 text-sm text-dark-300 hover:bg-dark-700 transition-all"
            >
              Cancel
            </button>
            <button
              onClick={handleExecute}
              className="flex-1 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold flex items-center justify-center gap-2 transition-all"
            >
              Confirm
            </button>
          </div>
        </div>
      )}

      {/* ── Execute button ────────────────────────────────────────────────── */}
      {done ? (
        <div className="flex items-center justify-center gap-2 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 py-3">
          <CheckCircle className="w-4 h-4 text-emerald-400" />
          <span className="text-sm text-emerald-300 font-medium">
            Done — {shortlist.length} trade{plural} placed. Check the positions tab.
          </span>
        </div>
      ) : isExecuting ? (
        <div className="flex items-center justify-center gap-2 rounded-2xl bg-emerald-600/50 py-3.5">
          <Loader2 className="w-4 h-4 animate-spin text-white" />
          <span className="text-sm text-white font-medium">{botName} is placing your trades…</span>
        </div>
      ) : (
        !showConfirm && (
          <button
            onClick={() => setShowConfirm(true)}
            disabled={shortlist.length === 0 || isLoading}
            className="w-full py-3.5 rounded-2xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold flex items-center justify-center gap-2 transition-all"
          >
            Let {botName} place {shortlist.length} trade{plural} →
          </button>
        )
      )}
    </div>
  );
}
