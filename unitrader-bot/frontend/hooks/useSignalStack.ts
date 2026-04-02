/**
 * useSignalStack — React hook for the shared, pre-computed Signal Stack.
 *
 * Usage:
 *   const { signals, isLoading, acceptSignal, skipSignal, setMode, refresh } =
 *     useSignalStack(userSettings);
 *
 * The stack is loaded on mount and refreshed every 5 minutes.
 * Re-fetches automatically when the user switches signal mode.
 *
 * Optimistic updates:
 *   acceptSignal / skipSignal mark the interaction locally before the API
 *   call completes so the UI responds instantly.
 */

import { useState, useEffect, useCallback } from "react";
import { signalApi } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type SignalDirection = "buy" | "sell" | "watch";
export type SignalMode = "browse" | "apex_selects" | "full_auto";
export type InteractionAction = "accepted" | "skipped" | "traded";

export interface Signal {
  id: string;
  symbol: string;
  asset_name: string;
  asset_class: "stocks" | "crypto" | "forex" | "commodity";
  exchange: string;
  signal: SignalDirection;
  confidence: number;
  /** Level-appropriate explanation chosen by the API based on trader class. */
  reasoning: string;
  reasoning_expert: string;
  reasoning_simple: string;
  reasoning_metaphor: string;
  rsi: number | null;
  macd_signal: string | null;
  volume_ratio: number | null;
  sentiment_score: string | null;
  current_price: number;
  price_change_24h: number;
  /** Null when fewer than 10 community interactions exist for this signal. */
  community_pct: number | null;
  expires_at: string;
  /** Set when the authenticated user has already interacted with this signal. */
  interaction?: InteractionAction;
}

export interface SignalStackState {
  signals: Signal[];
  isLoading: boolean;
  isRefreshing: boolean;
  mode: SignalMode;
  lastScanAt: string | null;
  nextScanInMinutes: number | null;
  assetsScanned: number;
  error: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useSignalStack(
  userSettings: { signal_stack_mode?: string },
  opts?: { tradingAccountId?: string | null },
) {
  const [state, setState] = useState<SignalStackState>({
    signals: [],
    isLoading: true,
    isRefreshing: false,
    mode: (userSettings.signal_stack_mode as SignalMode) || "browse",
    lastScanAt: null,
    nextScanInMinutes: null,
    assetsScanned: 0,
    error: null,
  });

  // Destructure mode so useCallback dependency stays stable across renders
  const { mode } = state;

  const loadStack = useCallback(async () => {
    setState((prev) => ({
      ...prev,
      isRefreshing: !prev.isLoading,
    }));
    try {
      const res = await signalApi.stack({ trading_account_id: opts?.tradingAccountId ?? undefined });
      const data = res.data as any;
      // Backend may return either:
      //  - { signals, last_scan_at, ... }
      //  - { status: "success", data: { signals, last_scan_at, ... } }
      const payload = data?.data && typeof data.data === "object" ? data.data : data;
      const rawSignals = payload?.signals;
      const safeSignals = Array.isArray(rawSignals) ? rawSignals : [];
      setState((prev) => ({
        ...prev,
        signals: safeSignals,
        isLoading: false,
        isRefreshing: false,
        lastScanAt: payload?.last_scan_at ?? null,
        nextScanInMinutes: payload?.next_scan_in_minutes ?? null,
        assetsScanned: payload?.assets_scanned ?? 0,
        error: null,
      }));
    } catch {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        isRefreshing: false,
        error: "Could not load signals. Retrying soon.",
      }));
    }
  }, [mode, opts?.tradingAccountId]); // re-create when mode changes so mode-filtered results are re-fetched

  // Load on mount and every 5 minutes; also re-loads when mode changes
  useEffect(() => {
    loadStack();
    const interval = setInterval(loadStack, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [loadStack]);

  // ── Actions ───────────────────────────────────────────────────────────────

  const acceptSignal = useCallback(async (signalId: string): Promise<boolean> => {
    // Optimistic update first
    setState((prev) => ({
      ...prev,
      signals: prev.signals.map((s) =>
        s.id === signalId ? { ...s, interaction: "accepted" as InteractionAction } : s,
      ),
    }));
    try {
      await signalApi.interact(signalId, "accepted");
      return true;
    } catch {
      // Roll back optimistic update on failure
      setState((prev) => ({
        ...prev,
        signals: prev.signals.map((s) =>
          s.id === signalId ? { ...s, interaction: undefined } : s,
        ),
      }));
      return false;
    }
  }, []);

  const skipSignal = useCallback(async (signalId: string): Promise<void> => {
    // Optimistic update
    setState((prev) => ({
      ...prev,
      signals: prev.signals.map((s) =>
        s.id === signalId ? { ...s, interaction: "skipped" as InteractionAction } : s,
      ),
    }));
    try {
      await signalApi.interact(signalId, "skipped");
    } catch {
      setState((prev) => ({
        ...prev,
        signals: prev.signals.map((s) =>
          s.id === signalId ? { ...s, interaction: undefined } : s,
        ),
      }));
    }
  }, []);

  const setMode = useCallback(async (newMode: SignalMode): Promise<void> => {
    setState((prev) => ({ ...prev, mode: newMode }));
    try {
      await signalApi.updateSettings({ signal_stack_mode: newMode });
    } catch {
      // Non-fatal — local mode is still updated; persists on next settings save
    }
  }, []);

  const refresh = useCallback(() => {
    loadStack();
  }, [loadStack]);

  return {
    ...state,
    acceptSignal,
    skipSignal,
    setMode,
    refresh,
  };
}
