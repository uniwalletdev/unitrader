/**
 * useTrialStatus — React hook for trial state management.
 *
 * Usage:
 *   const { status, daysRemaining, hasChosen, loading, refetch } = useTrialStatus();
 *
 *   if (status === "expired" && !hasChosen) {
 *     return <TrialChoiceModal />;
 *   }
 *
 * Cache strategy:
 *   - Data is cached in localStorage for 5 minutes to avoid refetching on
 *     every render. Call `refetch()` to force a fresh API hit (e.g. after
 *     the user makes a choice).
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { trialApi } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type TrialPhase = "early" | "mid" | "late" | "expired";
export type TrialChoiceStatus =
  | "active"       // still in trial
  | "expired"      // trial ended, no choice yet  ← force modal
  | "converted"    // upgraded to Pro
  | "downgraded";  // chose Free tier

export interface TrialPerformance {
  trades_made: number;
  wins: number;
  win_rate_pct: number;
  total_profit: number;
  total_loss: number;
  net_pnl: number;
}

export interface TrialState {
  status: TrialChoiceStatus;
  phase: TrialPhase;
  daysRemaining: number;
  trialEndDate: string | null;
  aiName: string;
  subscriptionTier: string;
  banner: string;
  showChoiceModal: boolean;
  /** True when the user has already made a choice (converted or downgraded). */
  hasChosen: boolean;
  performance: TrialPerformance;
  performanceSummary: string;
}

const CACHE_KEY = "unitrader_trial_status";
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

interface CacheEntry {
  data: TrialState;
  fetchedAt: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Cache helpers
// ─────────────────────────────────────────────────────────────────────────────

function readCache(): TrialState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const entry: CacheEntry = JSON.parse(raw);
    if (Date.now() - entry.fetchedAt > CACHE_TTL_MS) {
      localStorage.removeItem(CACHE_KEY);
      return null;
    }
    return entry.data;
  } catch {
    return null;
  }
}

function writeCache(data: TrialState): void {
  if (typeof window === "undefined") return;
  try {
    const entry: CacheEntry = { data, fetchedAt: Date.now() };
    localStorage.setItem(CACHE_KEY, JSON.stringify(entry));
  } catch { /* storage full — ignore */ }
}

export function clearTrialCache(): void {
  if (typeof window !== "undefined") localStorage.removeItem(CACHE_KEY);
}

// ─────────────────────────────────────────────────────────────────────────────
// API response → TrialState normalisation
// ─────────────────────────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalise(raw: any): TrialState {
  const hasChosen =
    raw.status === "converted" || raw.status === "downgraded";

  return {
    status:             raw.status         ?? "active",
    phase:              raw.phase          ?? "early",
    daysRemaining:      raw.days_remaining ?? 14,
    trialEndDate:       raw.trial_end_date ?? null,
    aiName:             raw.ai_name        ?? "Your AI",
    subscriptionTier:   raw.subscription_tier ?? "free",
    banner:             raw.banner         ?? "",
    showChoiceModal:    raw.show_choice_modal ?? false,
    hasChosen,
    performance: {
      trades_made:   raw.performance?.trades_made   ?? 0,
      wins:          raw.performance?.wins          ?? 0,
      win_rate_pct:  raw.performance?.win_rate_pct  ?? 0,
      total_profit:  raw.performance?.total_profit  ?? 0,
      total_loss:    raw.performance?.total_loss    ?? 0,
      net_pnl:       raw.performance?.net_pnl       ?? 0,
    },
    performanceSummary: raw.performance_summary ?? "",
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useTrialStatus(options: { skip?: boolean } = {}) {
  const [trial, setTrial]   = useState<TrialState | null>(() => readCache());
  const [loading, setLoading] = useState(!readCache());
  const [error, setError]   = useState<string | null>(null);
  const fetchingRef = useRef(false);

  const fetchStatus = useCallback(async (force = false) => {
    if (options.skip) return;

    // Don't double-fetch
    if (fetchingRef.current) return;
    fetchingRef.current = true;

    // Use cache unless forced
    if (!force) {
      const cached = readCache();
      if (cached) {
        setTrial(cached);
        setLoading(false);
        fetchingRef.current = false;
        return;
      }
    }

    // No token → skip (user not logged in)
    if (typeof window !== "undefined" && !localStorage.getItem("access_token")) {
      setLoading(false);
      fetchingRef.current = false;
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await trialApi.status();
      const normalised = normalise(res.data);
      writeCache(normalised);
      setTrial(normalised);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Could not load trial status");
    } finally {
      setLoading(false);
      fetchingRef.current = false;
    }
  }, [options.skip]);

  // Fetch on mount
  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  /**
   * Force a fresh API call and clear the cache.
   * Call this after the user makes a choice, or after Stripe redirects back.
   */
  const refetch = useCallback(() => {
    clearTrialCache();
    fetchStatus(true);
  }, [fetchStatus]);

  // ── Derived helpers ──────────────────────────────────────────────────────

  /**
   * Returns true when the modal MUST be shown and cannot be dismissed.
   * Condition: trial expired AND user has not yet made a plan choice.
   */
  const mustShowModal = trial
    ? trial.status === "expired" && !trial.hasChosen
    : false;

  /**
   * Returns true for any banner-worthy state (trial active or expired,
   * not yet converted to pro).
   */
  const showBanner = trial
    ? trial.subscriptionTier !== "pro" && !trial.hasChosen
    : false;

  return {
    trial,
    loading,
    error,
    refetch,

    // Convenience accessors matching the spec's destructure pattern:
    status:       trial?.status       ?? null,
    daysRemaining: trial?.daysRemaining ?? null,
    hasChosen:    trial?.hasChosen    ?? false,
    phase:        trial?.phase        ?? null,
    aiName:       trial?.aiName       ?? "",
    performance:  trial?.performance  ?? null,

    // Flags
    mustShowModal,
    showBanner,
  };
}
