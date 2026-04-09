"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useEngagementStats } from "@/hooks/useEngagementStats";
import { Flame, TrendingUp, TrendingDown, ChevronDown, ChevronUp, BarChart3 } from "lucide-react";

const DISMISS_KEY = "unitrader_pulse_dismissed";

function wasDismissedToday(): boolean {
  if (typeof window === "undefined") return false;
  const stored = localStorage.getItem(DISMISS_KEY);
  if (!stored) return false;
  const day = new Date().toISOString().slice(0, 10);
  return stored === day;
}

function dismissToday() {
  const day = new Date().toISOString().slice(0, 10);
  localStorage.setItem(DISMISS_KEY, day);
}

function formatUSD(n: number) {
  const prefix = n >= 0 ? "+$" : "-$";
  return prefix + Math.abs(n).toFixed(2);
}

export default function PerformancePulse() {
  const { data, isLoading } = useEngagementStats();
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    setDismissed(wasDismissedToday());
  }, []);

  if (isLoading || !data || dismissed) return null;

  const { streak, pulse, ai_name } = data;
  const hasStreak = streak.current_wins >= 2;
  const bigStreak = streak.current_wins >= 5;
  const losingStreak = streak.current_losses >= 2;
  const weekPositive = pulse.pnl_7d > 0;

  // Determine what to show
  let icon: React.ReactNode;
  let message: string;
  let accentColor: string;
  let bgClass: string;

  if (bigStreak) {
    icon = <Flame size={16} className="text-yellow-400" />;
    message = `${streak.current_wins}-WIN STREAK — ${ai_name} is on fire!`;
    accentColor = "text-yellow-400";
    bgClass = "bg-gradient-to-r from-yellow-500/10 via-orange-500/10 to-yellow-500/10";
  } else if (hasStreak) {
    icon = <Flame size={16} className="text-brand-400" />;
    message = `${ai_name} is on a ${streak.current_wins}-win streak!`;
    accentColor = "text-brand-400";
    bgClass = "bg-brand-500/8";
  } else if (losingStreak) {
    icon = <TrendingDown size={16} className="text-dark-400" />;
    message = `${ai_name} is recalibrating… ${pulse.ai_accuracy_pct}% overall accuracy`;
    accentColor = "text-dark-300";
    bgClass = "bg-dark-800/60";
  } else if (weekPositive) {
    icon = <TrendingUp size={16} className="text-brand-400" />;
    message = `${ai_name} is up ${formatUSD(pulse.pnl_7d)} this week`;
    accentColor = "text-brand-400";
    bgClass = "bg-brand-500/8";
  } else if (pulse.total_trades > 0) {
    icon = <BarChart3 size={16} className="text-dark-400" />;
    message = `${ai_name} has completed ${pulse.total_trades} trades — ${pulse.ai_accuracy_pct}% AI accuracy`;
    accentColor = "text-dark-300";
    bgClass = "bg-dark-800/60";
  } else {
    return null; // no trades yet
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className={`relative mx-auto mb-2 w-full max-w-2xl rounded-lg border border-dark-700/50 px-3 py-2 ${bgClass}`}
    >
      {/* Main row */}
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={() => setExpanded((p) => !p)}
          className="flex flex-1 items-center gap-2 text-left"
        >
          {icon}
          <span className={`text-sm font-medium ${accentColor}`}>{message}</span>
          {expanded ? (
            <ChevronUp size={14} className="text-dark-500 ml-auto shrink-0" />
          ) : (
            <ChevronDown size={14} className="text-dark-500 ml-auto shrink-0" />
          )}
        </button>
        <button
          onClick={() => { dismissToday(); setDismissed(true); }}
          className="shrink-0 text-[10px] text-dark-500 hover:text-dark-300"
        >
          ✕
        </button>
      </div>

      {/* Expanded stats */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-dark-700/50 pt-2 text-xs sm:grid-cols-4">
              <div>
                <span className="text-dark-500">7d P&amp;L</span>
                <p className={pulse.pnl_7d >= 0 ? "text-brand-400 font-medium" : "text-red-400 font-medium"}>
                  {formatUSD(pulse.pnl_7d)}
                </p>
              </div>
              <div>
                <span className="text-dark-500">30d P&amp;L</span>
                <p className={pulse.pnl_30d >= 0 ? "text-brand-400 font-medium" : "text-red-400 font-medium"}>
                  {formatUSD(pulse.pnl_30d)}
                </p>
              </div>
              <div>
                <span className="text-dark-500">Win rate (7d)</span>
                <p className="text-dark-200 font-medium">{pulse.win_rate_7d}%</p>
              </div>
              <div>
                <span className="text-dark-500">AI accuracy</span>
                <p className="text-dark-200 font-medium">{pulse.ai_accuracy_pct}%</p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
