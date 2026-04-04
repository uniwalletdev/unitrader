/**
 * US equity regular session in America/New_York (Mon–Fri 09:30–16:00, end exclusive).
 * Used for manual Execute Trade gating on stock symbols.
 */

export function isUsEquityRegularSessionEt(date: Date = new Date()): boolean {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);

  const wd = parts.find((p) => p.type === "weekday")?.value ?? "";
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const m = Number(parts.find((p) => p.type === "minute")?.value ?? "0");

  if (!["Mon", "Tue", "Wed", "Thu", "Fri"].includes(wd)) return false;
  const mins = h * 60 + m;
  const open = 9 * 60 + 30;
  const close = 16 * 60; // Regular session ends 16:00 ET (exclusive)
  return mins >= open && mins < close;
}

/**
 * US stock regular session for signal-scan UX copy (Mon–Fri 09:30–16:00 ET, 16:00 inclusive).
 * Intentionally separate from {@link isUsEquityRegularSessionEt} (16:00 exclusive for execution).
 */
export function isMarketOpen(): boolean {
  const now = new Date();
  const et = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "numeric",
    weekday: "short",
    hour12: false,
  }).formatToParts(now);

  const weekday = et.find((p) => p.type === "weekday")?.value;
  const hour = parseInt(et.find((p) => p.type === "hour")?.value || "0", 10);
  const minute = parseInt(et.find((p) => p.type === "minute")?.value || "0", 10);
  const timeVal = hour * 60 + minute;

  if (["Sat", "Sun"].includes(weekday || "")) return false;
  return timeVal >= 570 && timeVal <= 960;
}

/** True when manual trade execute should apply US equity hours (not crypto/forex). */
export function isStocksTradingAsset(exchange: string, symbol: string): boolean {
  const ex = (exchange || "").toLowerCase();
  if (ex === "binance" || ex === "coinbase") return false;
  if (ex === "oanda") return false;
  const s = (symbol || "").trim().toUpperCase();
  if (!s) return false;
  if (s.includes("/") || s.includes("-")) return false;
  if (s.includes("_")) return false;
  if (s.endsWith("USDT") || s.endsWith("BUSD") || s.endsWith("USDC")) return false;
  return true;
}
