"use client";

import { AnimatePresence, motion } from "framer-motion";
import { RefreshCw, Radio } from "lucide-react";
import SignalCard from "./SignalCard";
import { Signal } from "@/hooks/useSignalStack";
import { isMarketOpen } from "@/utils/usEquitySession";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface BrowseStackProps {
  botName: string;
  signals: Signal[];
  isRefreshing: boolean;
  lastScanAt: string | null;
  nextScanInMinutes: number | null;
  assetsScanned: number;
  traderClass: string;
  explanationLevel: string;
  onAccept: (id: string) => Promise<boolean>;
  onSkip: (id: string) => void;
  onRefresh: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function formatScanTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-2xl border border-dark-700 bg-dark-800 h-40" />
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export default function BrowseStack({
  botName,
  signals,
  isRefreshing,
  lastScanAt,
  nextScanInMinutes,
  assetsScanned,
  traderClass,
  explanationLevel,
  onAccept,
  onSkip,
  onRefresh,
}: BrowseStackProps) {
  const visibleSignals = signals.filter((s) => s.interaction !== "skipped");
  const marketOpen = isMarketOpen();

  const resolvedExplanationLevel = (
    ["expert", "simple", "metaphor"].includes(explanationLevel)
      ? explanationLevel
      : "simple"
  ) as "expert" | "simple" | "metaphor";

  return (
    <div className="flex flex-col gap-4">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            {marketOpen ? (
              <>
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
              </>
            ) : (
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-dark-500" />
            )}
          </span>
          <span className="text-sm font-semibold text-white">
            {botName} signals — {marketOpen ? "live" : "paused"}
          </span>
        </div>

        <div className="flex items-center gap-3 text-xs text-dark-400">
          <span>
            <span className="text-dark-300">{assetsScanned}</span> assets scanned
            {" · "}
            <span className="text-dark-300">{visibleSignals.length}</span> signals
          </span>
          {marketOpen && (
            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              className="p-1.5 rounded-lg border border-dark-700 hover:bg-dark-800 text-dark-400 hover:text-white transition-all disabled:opacity-40"
              aria-label="Refresh signals"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin" : ""}`} />
            </button>
          )}
        </div>
      </div>

      {/* ── Content ───────────────────────────────────────────────────────── */}
      {isRefreshing ? (
        <div className="flex flex-col gap-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : visibleSignals.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dark-700 bg-dark-900 px-6 py-10 text-center">
          <Radio className="w-8 h-8 text-dark-500" />
          {marketOpen ? (
            <>
              <p className="text-sm font-medium text-dark-300">
                All signals reviewed. {botName} is scanning for more.
              </p>
              {nextScanInMinutes !== null && (
                <p className="text-xs text-dark-500">
                  Next scan in{" "}
                  <span className="text-dark-300 font-medium">{nextScanInMinutes}</span> minutes.
                </p>
              )}
              <button
                onClick={onRefresh}
                className="mt-1 px-4 py-2 rounded-xl border border-dark-600 bg-dark-800 text-sm text-dark-200 hover:bg-dark-700 hover:text-white transition-all"
              >
                Refresh now
              </button>
            </>
          ) : (
            <>
              <p className="text-sm font-medium text-dark-300">
                {botName} pauses scanning outside market hours
              </p>
              <p className="max-w-md text-xs text-dark-500">
                US stock markets are open Monday–Friday, 9:30am–4:00pm ET (2:30pm–9:00pm UK time).{" "}
                {botName} will resume scanning automatically when markets open.
              </p>
            </>
          )}
        </div>
      ) : (
        <AnimatePresence mode="popLayout">
          {signals.map((signal) => {
            if (signal.interaction === "skipped") return null;
            return (
              <motion.div
                key={signal.id}
                layout
                initial={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 16, transition: { duration: 0.2 } }}
              >
                <SignalCard
                  botName={botName}
                  signal={signal}
                  traderClass={traderClass}
                  explanationLevel={resolvedExplanationLevel}
                  onAccept={onAccept}
                  onSkip={onSkip}
                  isExecuting={false}
                />
              </motion.div>
            );
          })}
        </AnimatePresence>
      )}

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      {lastScanAt && (
        <p className="text-center text-[11px] text-dark-500">
          Last scanned: {formatScanTime(lastScanAt)}
        </p>
      )}
    </div>
  );
}
