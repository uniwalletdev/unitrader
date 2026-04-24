/**
 * errorUtils.ts — Centralised API error sanitization.
 *
 * Prevents raw JSON blobs, Anthropic request IDs, HTTP status codes,
 * and internal error types from being shown to users.
 */

const KNOWN_CODES: Record<string, string> = {
  token_budget_exceeded: "The AI is handling high demand. Please try again shortly.",
  execution_mode_locked: "This mode requires a higher Trust Ladder stage.",
  trading_account_id_required: "Please select a trading account first.",
  trading_account_not_found: "Trading account not found — please reconnect your exchange.",
  trading_account_not_found_or_unauthorized: "Trading account not found — please reconnect your exchange.",
  risk_disclosure_required: "Please accept the risk disclosure to continue.",
  risk_disclosure_not_accepted: "Please accept the risk disclosure to continue.",
  onboarding_required: "Please complete onboarding before trading.",
  subscription_required: "An active subscription is required to use this feature.",
  trading_paused: "Trading is paused — your daily loss limit has been reached.",
  market_closed: "The market is currently closed. Try again during trading hours.",
  etoro_trade_execution_pending:
    "eToro trading isn't available yet — your eToro account is connected for read-only features, " +
    "but to place trades now, use Alpaca or Coinbase.",
};

/**
 * Convert any caught API error to a safe, user-readable string.
 *
 * @param err        - The caught error (usually an Axios error)
 * @param fallback   - Default message when nothing better can be inferred
 */
export function sanitizeApiError(
  err: unknown,
  fallback = "Something went wrong. Please try again."
): string {
  const axiosErr = err as {
    response?: { data?: { detail?: unknown; message?: string }; status?: number };
    message?: string;
    code?: string;
  };

  // Network / timeout errors
  if (axiosErr?.code === "ECONNABORTED" || axiosErr?.message?.includes("timeout")) {
    return "The request timed out — please try again.";
  }
  if (axiosErr?.code === "ERR_NETWORK" || axiosErr?.message?.includes("Network Error")) {
    return "Could not reach the server — please check your connection.";
  }

  const detail = axiosErr?.response?.data?.detail;
  const status = axiosErr?.response?.status;

  // Structured object detail — map known codes, never expose raw object
  if (detail && typeof detail === "object") {
    const structured = detail as Record<string, unknown>;
    const code = (structured.code || structured.error) as string | undefined;
    if (code && KNOWN_CODES[code]) return KNOWN_CODES[code];
    // Special case: amount validation errors have a `message` key
    if (typeof structured.message === "string" && structured.message.length < 200) {
      return structured.message;
    }
    return fallback;
  }

  // String detail — use if short and clean (no JSON blobs or request IDs)
  if (typeof detail === "string") {
    const clean = detail.trim();
    if (KNOWN_CODES[clean]) return KNOWN_CODES[clean];
    if (clean.length < 200 && !clean.includes("{") && !clean.includes("request_id")) {
      return clean;
    }
    return fallback;
  }

  // HTTP status fallbacks
  if (status === 402) return "An active subscription is required.";
  if (status === 429) return "Too many requests — please wait a moment and try again.";
  if (status === 503) return "The service is temporarily unavailable. Please try again shortly.";
  if (status && status >= 500) return "A server error occurred. Please try again shortly.";

  return fallback;
}
