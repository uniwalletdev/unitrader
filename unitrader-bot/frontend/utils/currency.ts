/**
 * Trading account currency helpers — display only (no FX conversion).
 * Alpaca / Coinbase / OANDA / Binance integrations are USD-denominated today.
 */

const USD_EXCHANGES = new Set(["alpaca", "coinbase", "oanda", "binance"]);

/**
 * Resolve ISO currency code for display from API value or exchange default.
 */
export function resolveTradingCurrency(
  exchange: string,
  currencyFromApi?: string | null,
): string {
  const trimmed = currencyFromApi?.trim();
  if (trimmed) return trimmed.toUpperCase();
  const ex = (exchange || "").toLowerCase();
  if (USD_EXCHANGES.has(ex)) return "USD";
  return "USD";
}

/**
 * Symbol for UI amounts (prices, notional, caps).
 */
export function getCurrencySymbol(exchange: string, currency?: string): string {
  const code = (currency || resolveTradingCurrency(exchange)).toUpperCase();
  if (code === "GBP") return "£";
  if (code === "EUR") return "€";
  return "$";
}

/** e.g. "Amount (USD)" for range input label */
export function formatAmountLabel(iso: string): string {
  const code = (iso || "USD").toUpperCase();
  return `Amount (${code})`;
}
