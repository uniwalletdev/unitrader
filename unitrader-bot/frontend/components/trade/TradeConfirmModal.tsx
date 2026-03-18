import { useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronUp, X } from "lucide-react";
import { formatPrice } from "@/utils/formatPrice";
import { Haptics, ImpactStyle } from "@capacitor/haptics";
import { isNative } from "@/hooks/useCapacitor";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

type TradeLike = {
  symbol?: string;
  side?: string; // BUY | SELL
  decision?: string; // BUY | SELL | WAIT
  quantity?: number;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  reasoning?: string;
  message?: string;
  order_type?: string;
  tif?: string;
  slippage_estimate?: number;
  spread_pct?: number;
  portfolio_pct?: number;
  expected_market_impact?: "minimal" | "moderate" | "significant" | string;
  estimated_fill_time?: "immediate" | "1-3 seconds" | "up to 30 seconds" | string;
  order_json?: any;
  alpaca_payload?: any;
  fee_amount_gbp?: number;
  fee_pct?: number;
  bid?: number;
  ask?: number;
  price_usd?: number;
  price_gbp?: number;
};

const BRAND_NAMES: Record<string, string> = {
  AAPL: "Apple",
  MSFT: "Microsoft",
  NVDA: "NVIDIA",
  TSLA: "Tesla",
  AMZN: "Amazon",
  GOOGL: "Alphabet",
  META: "Meta",
  SPY: "S&P 500",
  VOO: "Vanguard S&P 500",
  BTCUSD: "Bitcoin",
  "BTC/USD": "Bitcoin",
  ETHUSD: "Ethereum",
  "ETH/USD": "Ethereum",
  SOLUSD: "Solana",
  "SOL/USD": "Solana",
};

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function badge(side: string) {
  const s = (side || "").toUpperCase();
  const isBuy = s === "BUY";
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-xl px-3 py-1 text-sm font-extrabold",
        isBuy ? "bg-green-500/15 text-green-300" : "bg-red-500/15 text-red-300",
      )}
    >
      {isBuy ? "BUY" : "SELL"}
    </span>
  );
}

function formatPct(n: number | null | undefined, dp: number = 2) {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(dp)}%`;
}

export default function TradeConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  trade,
  isPaper,
  traderClass,
}: {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
  trade: TradeLike;
  isPaper: boolean;
  traderClass: TraderClass;
}) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showJson, setShowJson] = useState(false);

  const symbol = (trade.symbol || "").toUpperCase();
  const side = ((trade.side || trade.decision || "BUY") as string).toUpperCase();
  const brand = BRAND_NAMES[symbol] || BRAND_NAMES[symbol.replace("USDT", "/USD")] || symbol;

  const entry = trade.entry_price ?? trade.price_usd ?? null;
  const sl = trade.stop_loss ?? null;
  const tp = trade.take_profit ?? null;
  const qty = trade.quantity ?? null;

  const confirmText = useMemo(() => {
    if (traderClass === "complete_novice" || traderClass === "curious_saver") {
      return isPaper ? "Confirm practice trade" : "Yes, let Apex make this trade";
    }
    if (traderClass === "self_taught") return isPaper ? "Confirm paper trade" : "Confirm trade";
    if (traderClass === "experienced") return isPaper ? "Submit paper" : "Execute";
    if (traderClass === "semi_institutional") return isPaper ? "Submit paper" : "Execute";
    if (traderClass === "crypto_native") {
      return side === "SELL" ? "Sell crypto" : "Buy crypto";
    }
    return "Confirm";
  }, [isPaper, traderClass, side]);

  const showPracticeBanner =
    isPaper && (traderClass === "complete_novice" || traderClass === "curious_saver");

  const apexSummary = trade.message || trade.reasoning || "";

  const estimatedCost = useMemo(() => {
    if (!entry || !qty) return null;
    return entry * qty;
  }, [entry, qty]);

  const slPlain = useMemo(() => {
    if (!sl) return null;
    // “minus 2%” is copy; compute actual relative drop vs entry if possible
    if (entry) {
      const pct = ((sl - entry) / entry) * 100;
      return `${formatPrice(sl, symbol)} (${formatPct(pct, 1)})`;
    }
    return formatPrice(sl, symbol);
  }, [sl, entry, symbol]);

  const tpPlain = useMemo(() => {
    if (!tp) return null;
    if (entry) {
      const pct = ((tp - entry) / entry) * 100;
      return `${formatPrice(tp, symbol)} (${formatPct(pct, 1)})`;
    }
    return formatPrice(tp, symbol);
  }, [tp, entry, symbol]);

  if (!isOpen) return null;

  const isNovice = traderClass === "complete_novice" || traderClass === "curious_saver";
  const isPro = traderClass === "experienced" || traderClass === "semi_institutional";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-2xl rounded-2xl border border-dark-800 bg-dark-950 shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-dark-800 p-5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-lg">{badge(side)}</div>
              <div className="truncate text-lg font-extrabold text-white">
                {isNovice ? brand : symbol}
              </div>
            </div>
            <div className="mt-1 text-xs text-dark-400">
              Review the details before confirming.
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              if (isSubmitting) return;
              onClose();
            }}
            className="rounded-lg p-2 text-dark-400 hover:bg-dark-900 hover:text-white"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {showPracticeBanner && (
          <div className="border-b border-amber-500/30 bg-amber-500/10 px-5 py-4">
            <div className="text-sm font-extrabold text-amber-200">
              PRACTICE TRADE - no real money will be spent
            </div>
          </div>
        )}

        {/* Body */}
        <div className="space-y-4 p-5">
          {error && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
              {error}
            </div>
          )}

          {/* Novice/Saver layout */}
          {isNovice && (
            <div className="space-y-3">
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="grid gap-3 md:grid-cols-2">
                  <SummaryRow
                    label={side === "SELL" ? "You are selling" : "You are buying"}
                    value={brand}
                  />
                  <SummaryRow
                    label="Estimated cost"
                    value={estimatedCost !== null ? `£${estimatedCost.toFixed(2)}` : "—"}
                  />
                  <SummaryRow
                    label="Protection"
                    value={
                      slPlain
                        ? `Apex will sell automatically if it drops to ${slPlain}`
                        : "—"
                    }
                  />
                  <SummaryRow
                    label="Target"
                    value={
                      tpPlain
                        ? `Apex will sell when it reaches ${tpPlain}`
                        : "—"
                    }
                  />
                  <SummaryRow
                    label="Exchange fees"
                    value="Free (Alpaca charges nothing)"
                  />
                </div>
              </div>

              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="text-xs font-semibold text-dark-200">Apex summary</div>
                <div className="mt-2 text-sm text-dark-200">
                  {apexSummary || "—"}
                </div>
              </div>
            </div>
          )}

          {/* self_taught */}
          {traderClass === "self_taught" && (
            <div className="space-y-3">
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="grid gap-3 md:grid-cols-2">
                  <SummaryRow label="Symbol" value={symbol || "—"} />
                  <SummaryRow label="Side" value={side} />
                  <SummaryRow
                    label="Quantity (shares)"
                    value={qty !== null ? String(qty) : "—"}
                  />
                  <SummaryRow
                    label="Estimated cost"
                    value={estimatedCost !== null ? `£${estimatedCost.toFixed(2)}` : "—"}
                  />
                  <SummaryRow
                    label="Stop-loss"
                    value={slPlain ? `${slPlain}` : "—"}
                  />
                  <SummaryRow
                    label="Take-profit"
                    value={tpPlain ? `${tpPlain}` : "—"}
                  />
                  <SummaryRow
                    label="Portfolio exposure"
                    value={
                      trade.portfolio_pct !== undefined && trade.portfolio_pct !== null
                        ? `${trade.portfolio_pct.toFixed(2)}% of your portfolio`
                        : "—"
                    }
                  />
                </div>
              </div>

              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="text-xs font-semibold text-dark-200">Reasoning</div>
                <div className="mt-2 text-sm text-dark-200">{apexSummary || "—"}</div>
              </div>
            </div>
          )}

          {/* experienced */}
          {traderClass === "experienced" && (
            <div className="space-y-3">
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="grid gap-2 md:grid-cols-3">
                  <SummaryRow label="Symbol" value={symbol || "—"} />
                  <SummaryRow label="Side" value={side} />
                  <SummaryRow label="Order type" value={trade.order_type || "Market"} />
                  <SummaryRow label="TIF" value={trade.tif || "DAY"} />
                  <SummaryRow
                    label="Qty"
                    value={qty !== null ? String(qty) : "—"}
                  />
                  <SummaryRow
                    label="Bid/Ask spread"
                    value={trade.spread_pct !== undefined ? formatPct(trade.spread_pct, 2) : "—"}
                  />
                  <SummaryRow
                    label="Slippage est."
                    value={trade.slippage_estimate !== undefined ? formatPct(trade.slippage_estimate, 2) : "—"}
                  />
                  <SummaryRow
                    label="Stop-loss"
                    value={sl !== null ? formatPrice(sl, symbol) : "—"}
                  />
                  <SummaryRow
                    label="Take-profit"
                    value={tp !== null ? formatPrice(tp, symbol) : "—"}
                  />
                </div>
              </div>
            </div>
          )}

          {/* semi_institutional */}
          {traderClass === "semi_institutional" && (
            <div className="space-y-3">
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="grid gap-2 md:grid-cols-3">
                  <SummaryRow label="Symbol" value={symbol || "—"} />
                  <SummaryRow label="Side" value={side} />
                  <SummaryRow label="Order type" value={trade.order_type || "Market"} />
                  <SummaryRow label="TIF" value={trade.tif || "DAY"} />
                  <SummaryRow
                    label="Qty"
                    value={qty !== null ? String(qty) : "—"}
                  />
                  <SummaryRow
                    label="Bid/Ask spread"
                    value={trade.spread_pct !== undefined ? formatPct(trade.spread_pct, 2) : "—"}
                  />
                  <SummaryRow
                    label="Slippage est."
                    value={trade.slippage_estimate !== undefined ? formatPct(trade.slippage_estimate, 2) : "—"}
                  />
                  <SummaryRow
                    label="Stop-loss"
                    value={sl !== null ? formatPrice(sl, symbol) : "—"}
                  />
                  <SummaryRow
                    label="Take-profit"
                    value={tp !== null ? formatPrice(tp, symbol) : "—"}
                  />
                  <SummaryRow
                    label="Expected market impact"
                    value={trade.expected_market_impact || "—"}
                  />
                  <SummaryRow
                    label="Estimated fill time"
                    value={trade.estimated_fill_time || "—"}
                  />
                </div>
              </div>

              <div className="rounded-xl border border-dark-800 bg-dark-950">
                <button
                  type="button"
                  onClick={() => setShowJson((v) => !v)}
                  className="flex w-full items-center justify-between px-4 py-3 text-left text-xs font-semibold text-dark-200"
                >
                  <span>View order JSON</span>
                  {showJson ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
                {showJson && (
                  <pre className="max-h-60 overflow-auto border-t border-dark-800 bg-dark-950 px-4 py-3 text-[11px] text-dark-300">
                    {JSON.stringify(trade.order_json ?? trade.alpaca_payload ?? trade, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          )}

          {/* crypto_native */}
          {traderClass === "crypto_native" && (
            <div className="space-y-3">
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="grid gap-2 md:grid-cols-3">
                  <SummaryRow label="Symbol" value={symbol || "—"} />
                  <SummaryRow label="Side" value={side} />
                  <SummaryRow
                    label="Price"
                    value={
                      trade.price_usd !== undefined && trade.price_gbp !== undefined
                        ? `$${Number(trade.price_usd).toFixed(2)} / £${Number(trade.price_gbp).toFixed(2)}`
                        : entry !== null
                          ? `${formatPrice(entry, symbol)}`
                          : "—"
                    }
                  />
                  <SummaryRow
                    label="Bid/Ask spread"
                    value={
                      trade.bid && trade.ask && trade.bid > 0
                        ? `${(((trade.ask - trade.bid) / trade.bid) * 100).toFixed(2)}%`
                        : trade.spread_pct !== undefined
                          ? formatPct(trade.spread_pct, 2)
                          : "—"
                    }
                  />
                  <SummaryRow
                    label="Exchange fee"
                    value={
                      trade.fee_amount_gbp !== undefined
                        ? `approx 0.6% (GBP ${Number(trade.fee_amount_gbp).toFixed(2)})`
                        : "approx 0.6% (GBP —)"
                    }
                  />
                  <SummaryRow
                    label="Stop-loss"
                    value={sl !== null ? formatPrice(sl, symbol) : "—"}
                  />
                  <SummaryRow
                    label="Take-profit"
                    value={tp !== null ? formatPrice(tp, symbol) : "—"}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Footer actions */}
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => {
                if (isSubmitting) return;
                onClose();
              }}
              className="btn-outline"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={async () => {
                if (isSubmitting) return;
                setError(null);
                setIsSubmitting(true);
                try {
                  if (isNative) {
                    await Haptics.impact({ style: ImpactStyle.Medium });
                  }
                  await onConfirm();
                  onClose();
                } catch (e: any) {
                  setError(
                    e?.response?.data?.detail ||
                      e?.message ||
                      "Could not submit trade. Please try again.",
                  );
                } finally {
                  setIsSubmitting(false);
                }
              }}
              className={clsx(
                "btn-primary inline-flex items-center justify-center gap-2",
              )}
              disabled={isSubmitting}
            >
              <CheckCircle2 size={16} />
              {isSubmitting ? "Submitting…" : confirmText}
            </button>
          </div>

          <div className="text-[10px] leading-relaxed text-dark-500">
            Market orders execute at the best available price and may differ slightly from
            estimates.
          </div>
        </div>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-dark-800 bg-dark-950 px-3 py-2">
      <div className="text-xs text-dark-400">{label}</div>
      <div className="text-xs font-semibold text-white">{value}</div>
    </div>
  );
}

