/**
 * TrialChoiceModal — shown on Day 14 (or when trial expires).
 *
 * Layout matches design spec:
 *   ┌──────────────────────────────────────┐
 *   │  TradeMaster's Trial Ends Today!     │
 *   ├──────────────────────────────────────┤
 *   │  🎉 Your AI made you $567!           │
 *   │  Option 1: UPGRADE TO PRO ($9.99)    │
 *   │  Option 2: FREE TIER (Forever)       │
 *   │  Option 3: Say Goodbye               │
 *   └──────────────────────────────────────┘
 */
import { useState } from "react";
import { useRouter } from "next/router";
import { Check, X, Zap, AlertTriangle, TrendingUp } from "lucide-react";
import { trialApi, billingApi } from "@/lib/api";
import { clearTrialCache } from "@/hooks/useTrialStatus";

interface TrialStats {
  trades_made: number;
  win_rate_pct: number;
  net_pnl: number;
}

interface Props {
  aiName: string;
  daysRemaining: number;
  stats: TrialStats;
  onClose?: () => void; // only available when days > 0 (soft dismiss)
}

export default function TrialChoiceModal({ aiName, daysRemaining, stats, onClose }: Props) {
  const router = useRouter();
  const [loading, setLoading] = useState<"pro" | "free" | "cancel" | null>(null);
  const [error, setError] = useState("");
  const [cancelConfirm, setCancelConfirm] = useState(false);

  const isExpired = daysRemaining === 0;
  const pnlPositive = stats.net_pnl >= 0;
  const pnlAbs = Math.abs(stats.net_pnl).toFixed(2);
  const madeOrLost = pnlPositive ? "made you" : "lost";

  const handleChoice = async (choice: "pro" | "free" | "cancel") => {
    setLoading(choice);
    setError("");
    try {
      if (choice === "pro") {
        // Hit the dedicated checkout-session endpoint directly
        const res = await billingApi.checkoutSession();
        const url: string = res.data?.data?.checkout_url;
        if (url) {
          clearTrialCache();
          window.location.href = url;
          return;
        }
        // Fallback: let the trial router handle it
        const fallback = await trialApi.makeChoice("pro");
        if (fallback.data?.checkout_url) {
          clearTrialCache();
          window.location.href = fallback.data.checkout_url;
        }
      } else {
        await trialApi.makeChoice(choice);
        clearTrialCache();
        if (choice === "free") router.replace("/app");
        else router.replace("/");
      }
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || "Something went wrong. Please try again.");
      setLoading(null);
    }
  };

  // ── Heading copy ────────────────────────────────────────────────────────────
  const heading = isExpired
    ? `${aiName}'s Trial Has Ended`
    : daysRemaining === 1
    ? `${aiName}'s Trial Ends Today!`
    : `${aiName}'s Trial: ${daysRemaining} Days Left`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-dark-950/90 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-dark-600 bg-dark-900 shadow-2xl overflow-hidden">

        {/* ── Header ─────────────────────────────────────────────────────────── */}
        <div className="relative flex items-center justify-between border-b border-dark-700 bg-dark-950 px-6 py-4">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500/20">
              <TrendingUp size={15} className="text-brand-400" />
            </div>
            <h2 className="font-bold text-white">{heading}</h2>
          </div>
          {!isExpired && onClose && (
            <button
              onClick={onClose}
              className="text-dark-500 hover:text-dark-300 transition"
              aria-label="Dismiss"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* ── AI profit summary ───────────────────────────────────────────────── */}
        <div className="border-b border-dark-700 bg-gradient-to-br from-brand-500/10 to-transparent px-6 py-5">
          {stats.trades_made > 0 ? (
            <>
              <p className="text-2xl font-extrabold text-white mb-1">
                {pnlPositive ? "🎉" : "📉"}{" "}
                Your AI {madeOrLost}{" "}
                <span className={pnlPositive ? "text-brand-400" : "text-red-400"}>
                  ${pnlAbs}
                </span>
                !
              </p>
              <p className="text-sm text-dark-400">
                {stats.trades_made} trades · {stats.win_rate_pct}% win rate
              </p>
            </>
          ) : (
            <p className="text-base font-semibold text-dark-300">
              {aiName} is ready — connect an exchange to start trading!
            </p>
          )}
        </div>

        {/* ── Options ────────────────────────────────────────────────────────── */}
        <div className="divide-y divide-dark-800">

          {/* Option 1: Pro */}
          <div className="px-6 py-5">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-bold uppercase tracking-wider text-brand-400">
                Option 1
              </span>
              <div className="h-px flex-1 bg-brand-500/20" />
              <span className="rounded-full bg-brand-500 px-2 py-0.5 text-[10px] font-bold uppercase text-dark-950">
                Best Value
              </span>
            </div>

            <h3 className="text-base font-bold text-white mb-0.5">
              Upgrade to Pro{" "}
              <span className="text-brand-400 font-extrabold">($9.99/month)</span>
            </h3>
            <p className="text-xs text-dark-400 mb-4">
              Keep {aiName} trading 24/7 with full power
            </p>

            <ul className="space-y-1.5 mb-4">
              {[
                "Unlimited exchange connections",
                "Unlimited trading pairs",
                "Priority Claude AI decisions",
                "Advanced analytics & reports",
                "Email trade alerts",
              ].map((b) => (
                <li key={b} className="flex items-center gap-2 text-sm text-dark-300">
                  <Check size={13} className="shrink-0 text-brand-500" />
                  {b}
                </li>
              ))}
            </ul>

            <button
              onClick={() => handleChoice("pro")}
              disabled={!!loading}
              className="btn-primary w-full py-3 text-base font-bold disabled:opacity-50"
            >
              {loading === "pro" ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  Redirecting…
                </span>
              ) : (
                <>
                  <Zap size={15} className="mr-1.5 inline" />
                  Upgrade Now
                </>
              )}
            </button>
          </div>

          {/* Option 2: Free */}
          <div className="px-6 py-5">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-bold uppercase tracking-wider text-dark-400">
                Option 2
              </span>
              <div className="h-px flex-1 bg-dark-700" />
              <span className="text-xs text-dark-500">Always free</span>
            </div>

            <h3 className="text-base font-bold text-white mb-0.5">
              Free Tier{" "}
              <span className="text-dark-400 font-normal">(Forever)</span>
            </h3>
            <p className="text-xs text-dark-400 mb-4">
              Keep using {aiName} with limited access
            </p>

            <ul className="space-y-1.5 mb-4">
              {[
                "Trade 1 pair free (Bitcoin)",
                "10 AI trades per month",
                "1 exchange connection",
                "Basic performance dashboard",
              ].map((l) => (
                <li key={l} className="flex items-center gap-2 text-sm text-dark-400">
                  <Check size={13} className="shrink-0 text-dark-600" />
                  {l}
                </li>
              ))}
            </ul>

            <button
              onClick={() => handleChoice("free")}
              disabled={!!loading}
              className="btn-outline w-full py-2.5 disabled:opacity-50"
            >
              {loading === "free" ? "Saving…" : "Choose Free"}
            </button>
          </div>

          {/* Option 3: Cancel */}
          <div className="px-6 py-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-bold uppercase tracking-wider text-dark-600">
                Option 3
              </span>
              <div className="h-px flex-1 bg-dark-800" />
            </div>

            {!cancelConfirm ? (
              <button
                onClick={() => setCancelConfirm(true)}
                className="flex w-full items-center justify-between text-sm text-dark-500 hover:text-red-400 transition"
              >
                <span className="flex items-center gap-2">
                  <AlertTriangle size={14} />
                  Say Goodbye — Cancel Account
                </span>
                <X size={13} />
              </button>
            ) : (
              <div>
                <p className="mb-3 text-sm text-dark-400">
                  This permanently deletes your account and all trade history. Are you sure?
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setCancelConfirm(false)}
                    className="btn-outline flex-1 py-1.5 text-xs"
                  >
                    Keep account
                  </button>
                  <button
                    onClick={() => handleChoice("cancel")}
                    disabled={!!loading}
                    className="flex-1 rounded-lg border border-red-500/30 bg-red-500/10 py-1.5 text-xs text-red-400 transition hover:bg-red-500/20 disabled:opacity-50"
                  >
                    {loading === "cancel" ? "Cancelling…" : "Yes, delete everything"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Error ─────────────────────────────────────────────────────────── */}
        {error && (
          <div className="border-t border-dark-800 px-6 py-3">
            <p className="text-center text-sm text-red-400">{error}</p>
          </div>
        )}
      </div>
    </div>
  );
}
