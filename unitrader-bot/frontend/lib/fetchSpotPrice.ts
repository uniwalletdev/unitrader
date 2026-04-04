/**
 * Fallback spot price via existing GET /api/trading/ohlcv (stocks only).
 * Used when WebSocket live price is unavailable (e.g. Alpaca 429).
 */

import { api } from "@/lib/api";

/** Symbols supported by /api/trading/ohlcv (plain equity tickers only). */
export function isStockLikeSymbolForOhlcv(symbol: string): boolean {
  const s = symbol.trim().toUpperCase();
  if (!s || s.includes("/") || s.includes("_")) return false;
  if (s.includes("-")) return false;
  if (s.endsWith("USDT") || s.endsWith("BUSD")) return false;
  return /^[A-Z0-9.]+$/.test(s);
}

/** Last daily close from OHLCV; null if unavailable or request fails. */
export async function fetchSpotPriceViaOhlcv(symbol: string): Promise<number | null> {
  if (!isStockLikeSymbolForOhlcv(symbol)) return null;
  try {
    const res = await api.get("/api/trading/ohlcv", {
      params: {
        symbol: symbol.trim().toUpperCase(),
        days: 1,
        interval: "1day",
      },
      timeout: 5000,
    });
    const rows = res.data?.data;
    if (!Array.isArray(rows) || rows.length === 0) return null;
    const last = rows[rows.length - 1];
    const c = last?.close;
    return typeof c === "number" && Number.isFinite(c) ? c : null;
  } catch {
    return null;
  }
}
