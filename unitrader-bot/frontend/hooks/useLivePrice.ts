/**
 * useLivePrice — React hook for real-time price data via WebSocket.
 *
 * Usage:
 *   const { price, bid, ask, changePct, isConnected } = useLivePrice("AAPL");
 *
 * Features:
 *   - Automatically connects to WebSocket on mount
 *   - Reconnects with exponential backoff on disconnect
 *   - Closes connection on unmount or symbol change
 *   - Returns null for all prices while disconnected
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";

import { devLogError, devWarn } from "@/lib/devLog";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface LivePrice {
  price: number | null;
  bid: number | null;
  ask: number | null;
  changePct: number | null;
  volume: number | null;
  isConnected: boolean;
  lastUpdated: Date | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook Implementation
// ─────────────────────────────────────────────────────────────────────────────

const INITIAL_STATE: LivePrice = {
  price: null,
  bid: null,
  ask: null,
  changePct: null,
  volume: null,
  isConnected: false,
  lastUpdated: null,
};

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]; // ms, max 30s

export function useLivePrice(
  symbol: string | null,
  opts?: { tradingAccountId?: string | null },
): LivePrice {
  const { getToken } = useAuth();
  const [priceData, setPriceData] = useState<LivePrice>(INITIAL_STATE);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const mountedRef = useRef(true);
  const tradingAccountId = opts?.tradingAccountId ?? null;

  // Cleanup function for WebSocket and timers
  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  // Connect to WebSocket
  const connect = useCallback(async () => {
    if (!symbol || !mountedRef.current) return;

    try {
      // Prefer the same HS256 access_token as REST (`lib/api.ts`). Clerk session
      // JWTs are RS256 and require JWKS on the API; internal JWT matches `get_current_user`.
      const stored =
        typeof window !== "undefined" ? window.localStorage.getItem("access_token") : null;
      const token = stored?.trim() || (await getToken());
      if (!token) {
        devWarn("useLivePrice: No auth token available");
        return;
      }

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const wsUrl = apiUrl
        .replace(/^https:/, "wss:")
        .replace(/^http:/, "ws:");

      const params = new URLSearchParams({ token });
      if (tradingAccountId) params.set("trading_account_id", tradingAccountId);
      const url = `${wsUrl}/api/ws/prices/${symbol.toUpperCase()}?${params.toString()}`;

      const ws = new WebSocket(url);

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setPriceData((prev) => ({ ...prev, isConnected: true }));
        reconnectAttemptsRef.current = 0; // Reset counter on successful connection
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(event.data);
          setPriceData({
            price: data.price ?? null,
            bid: data.bid ?? null,
            ask: data.ask ?? null,
            changePct: data.change_pct ?? null,
            volume: data.volume ?? null,
            isConnected: true,
            lastUpdated: new Date(),
          });
        } catch (err) {
          devLogError("useLivePrice: Failed to parse message", err);
        }
      };

      ws.onerror = (error) => {
        devLogError("useLivePrice: WebSocket error", error);
        if (!mountedRef.current) return;
        setPriceData((prev) => ({ ...prev, isConnected: false }));
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setPriceData((prev) => ({ ...prev, isConnected: false }));
        wsRef.current = null;

        // Reconnect with exponential backoff
        const delay =
          RECONNECT_DELAYS[
            Math.min(reconnectAttemptsRef.current, RECONNECT_DELAYS.length - 1)
          ];
        reconnectAttemptsRef.current += 1;

        reconnectTimerRef.current = setTimeout(() => {
          if (mountedRef.current) {
            connect();
          }
        }, delay);
      };

      wsRef.current = ws;
    } catch (err) {
      devLogError("useLivePrice: Connection error", err);
      if (!mountedRef.current) return;
      setPriceData((prev) => ({ ...prev, isConnected: false }));

      // Retry connection
      const delay =
        RECONNECT_DELAYS[
          Math.min(reconnectAttemptsRef.current, RECONNECT_DELAYS.length - 1)
        ];
      reconnectAttemptsRef.current += 1;

      reconnectTimerRef.current = setTimeout(() => {
        if (mountedRef.current) {
          connect();
        }
      }, delay);
    }
  }, [symbol, getToken, tradingAccountId]);

  // Effect: Connect on mount and symbol change
  useEffect(() => {
    mountedRef.current = true;

    // If no symbol, reset state and return early
    if (!symbol) {
      setPriceData(INITIAL_STATE);
      return;
    }

    // Clean up any existing connection
    cleanup();
    reconnectAttemptsRef.current = 0;

    // Connect to new symbol
    connect();

    return () => {
      // Cleanup on unmount
      cleanup();
    };
  }, [symbol, connect, cleanup]);

  // Effect: Handle unmount
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [cleanup]);

  return priceData;
}
