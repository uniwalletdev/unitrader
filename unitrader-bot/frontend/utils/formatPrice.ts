/**
 * formatPrice — Price formatting utilities for trading UI.
 *
 * Detects asset type (crypto, forex, stocks) and formats accordingly.
 * Handles currency prefixes and decimal places.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Asset Type Detection
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Detect if a symbol is cryptocurrency
 */
function isCrypto(symbol: string): boolean {
  const cryptoSymbols = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "ADA",
    "DOGE",
    "MATIC",
    "LINK",
    "AVAX",
  ];
  return cryptoSymbols.includes(symbol.toUpperCase());
}

/**
 * Detect if a symbol is forex (contains underscore like EUR_USD)
 */
function isForex(symbol: string): boolean {
  return symbol.includes("_");
}

/**
 * Get exchange from symbol context (simplified; could be enhanced with DB lookup)
 */
function detectExchange(symbol: string): "alpaca" | "binance" | "oanda" | null {
  if (isCrypto(symbol)) return "binance";
  if (isForex(symbol)) return "oanda";
  return "alpaca"; // Assume stocks default to Alpaca
}

// ─────────────────────────────────────────────────────────────────────────────
// Price Formatting
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format price with appropriate decimal places and currency prefix.
 *
 * @param price - Numeric price
 * @param symbol - Trading symbol (e.g. "AAPL", "BTC", "EUR_USD")
 * @returns Formatted string like "£150.25" or "0.0001"
 */
export function formatPrice(price: number, symbol: string): string {
  if (price === null || price === undefined) {
    return "—";
  }

  const upperSymbol = symbol.toUpperCase();

  // Crypto: BTC/ETH → 2dp, others → 4dp
  if (isCrypto(upperSymbol)) {
    const decimals = ["BTC", "ETH"].includes(upperSymbol) ? 2 : 4;
    return price.toFixed(decimals);
  }

  // Forex: Always 4dp, no prefix
  if (isForex(upperSymbol)) {
    return price.toFixed(4);
  }

  // Stocks: 2dp with currency prefix
  // Default to £ for now (can be enhanced with user settings)
  return `£${price.toFixed(2)}`;
}

/**
 * Format price change percentage with color.
 *
 * @param pct - Change percentage (e.g. 1.24 or -2.5)
 * @returns Object with formatted text and color
 */
export function formatChangePct(pct: number | null): {
  text: string;
  color: string;
} {
  if (pct === null || pct === undefined) {
    return { text: "—", color: "#9ca3af" }; // gray-400
  }

  const sign = pct >= 0 ? "+" : "";
  const text = `${sign}${pct.toFixed(2)}%`;
  const color = pct >= 0 ? "#22c55e" : "#ef4444"; // green or red

  return { text, color };
}

/**
 * Format volume with K/M/B suffix
 *
 * @param volume - Volume number
 * @returns Formatted string like "1.2M" or "500K"
 */
export function formatVolume(volume: number | null): string {
  if (volume === null || volume === undefined) {
    return "—";
  }

  if (volume >= 1_000_000_000) {
    return (volume / 1_000_000_000).toFixed(1) + "B";
  }
  if (volume >= 1_000_000) {
    return (volume / 1_000_000).toFixed(1) + "M";
  }
  if (volume >= 1_000) {
    return (volume / 1_000).toFixed(1) + "K";
  }
  return volume.toFixed(0);
}

/**
 * Format time since last update
 *
 * @param date - Date of last update
 * @returns String like "2s ago" or "3m ago"
 */
export function formatTimeSinceUpdate(date: Date | null): string {
  if (!date) {
    return "—";
  }

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);

  if (diffSecs < 60) {
    return `${diffSecs}s ago`;
  }

  const diffMins = Math.floor(diffSecs / 60);
  if (diffMins < 60) {
    return `${diffMins}m ago`;
  }

  const diffHours = Math.floor(diffMins / 60);
  return `${diffHours}h ago`;
}

/**
 * Calculate spread (ask - bid) as percentage
 *
 * @param bid - Bid price
 * @param ask - Ask price
 * @returns Spread percentage
 */
export function calculateSpread(
  bid: number | null,
  ask: number | null
): number | null {
  if (bid === null || ask === null || bid === 0) {
    return null;
  }
  return ((ask - bid) / bid) * 100;
}
