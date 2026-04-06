/**
 * Trading account currency helpers — display only.
 *
 * Product decision: standardize user-facing currency to USD ($) everywhere.
 */

/**
 * Resolve ISO currency code for display from API value or exchange default.
 */
export function resolveTradingCurrency(
  exchange: string,
  currencyFromApi?: string | null,
): string {
  return "USD";
}

/**
 * Symbol for UI amounts (prices, notional, caps).
 */
export function getCurrencySymbol(exchange: string, currency?: string): string {
  return "$";
}

/** e.g. "Amount (USD)" for range input label */
export function formatAmountLabel(iso: string): string {
  return "Amount (USD)";
}
