"use client";

import { useEffect, useMemo, useState } from "react";
import { api, authApi, tradingApi } from "@/lib/api";
import {
  BarChart3,
  Download,
  Loader2,
  Share2,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react";
import RiskWarning from "@/components/layout/RiskWarning";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

type PerfSummary = {
  total_return_gbp: number;
  total_return_pct: number;
  win_rate: number;
  total_trades: number;
  paper_trades: number;
  best_trade: any;
  worst_trade: any;
  monthly_summary: Record<string, number>;

  // novice/saver
  goal_progress_message?: string;
  trust_ladder_summary?: { stage: number; days_until_advance: number; paper_trades_count: number };
  encouragement?: string;

  // self_taught
  vs_buy_hold?: number;
  vs_spy?: number;
  avg_hold_time_days?: number;

  // experienced/semi
  sharpe_ratio?: number;
  max_drawdown?: number;
  calmar_ratio?: number;
  beta?: number;
  alpha?: number;
  sector_pnl?: Record<string, number>;
  win_rate_by_asset_class?: Record<string, number>;

  // crypto_native
  vs_bitcoin_hold?: number;
  best_crypto?: { symbol: string; pct_gain: number; pnl_gbp: number } | null;
  worst_crypto?: { symbol: string; pct_loss: number; pnl_gbp: number } | null;
  total_fees_paid?: number;
};

type TradeRow = {
  id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  profit: number | null;
  loss: number | null;
  profit_percent: number | null;
  created_at: string | null;
  closed_at: string | null;
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

const ACCOUNT_TYPE: Record<TraderClass, string> = {
  complete_novice: "Beginner investor",
  curious_saver: "Passive saver",
  self_taught: "Self-taught trader",
  experienced: "Experienced trader",
  semi_institutional: "Institutional trader",
  crypto_native: "Crypto trader",
};

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function formatGBP(n: number) {
  const v = Number.isFinite(n) ? n : 0;
  const sign = v >= 0 ? "+" : "-";
  return `${sign}£${Math.abs(v).toFixed(2)}`;
}

function dateShort(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
}

function pillTone(n: number) {
  return n >= 0 ? "text-green-300 bg-green-500/10 border-green-500/20" : "text-red-300 bg-red-500/10 border-red-500/20";
}

function StatCard({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "good" | "bad" | "neutral" }) {
  const c = tone === "good" ? "text-green-300" : tone === "bad" ? "text-red-300" : "text-white";
  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
      <div className="text-xs text-dark-500">{label}</div>
      <div className={clsx("mt-1 text-lg font-bold tabular-nums", c)}>{value}</div>
      {sub && <div className="mt-1 text-xs text-dark-400">{sub}</div>}
    </div>
  );
}

function FeedbackThumbs({ tradeId }: { tradeId: string }) {
  const [v, setV] = useState<"up" | "down" | null>(null);
  return (
    <div className="flex items-center justify-end gap-2">
      <button
        type="button"
        onClick={() => setV("up")}
        className={clsx(
          "rounded-lg border px-2 py-1 text-xs",
          v === "up" ? "border-brand-500/40 bg-brand-500/10 text-brand-300" : "border-dark-800 bg-dark-950 text-dark-300 hover:text-white",
        )}
        aria-label={`Thumbs up ${tradeId}`}
      >
        <ThumbsUp size={14} />
      </button>
      <button
        type="button"
        onClick={() => setV("down")}
        className={clsx(
          "rounded-lg border px-2 py-1 text-xs",
          v === "down" ? "border-red-500/30 bg-red-500/10 text-red-200" : "border-dark-800 bg-dark-950 text-dark-300 hover:text-white",
        )}
        aria-label={`Thumbs down ${tradeId}`}
      >
        <ThumbsDown size={14} />
      </button>
    </div>
  );
}

export default function PerformancePage() {
  const [traderClass, setTraderClass] = useState<TraderClass>("complete_novice");
  const [period, setPeriod] = useState<30 | 90 | 365>(30);
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<PerfSummary | null>(null);
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [taxOpen, setTaxOpen] = useState(false);
  const [feedbackStats, setFeedbackStats] = useState<{
    positive_pct: number;
    total_rated: number;
    trust_score: number;
    recent_comments: string[];
  } | null>(null);

  const load = async (days: number) => {
    setLoading(true);
    setError(null);
    try {
      const [settingsRes, summaryRes, histRes] = await Promise.all([
        authApi.getSettings(),
        api.get("/api/performance/summary", { params: { days } }),
        tradingApi.history({ limit: 200, offset: 0 }),
      ]);

      setTraderClass((settingsRes.data?.trader_class as TraderClass) || "complete_novice");

      const sumData = summaryRes.data?.data ?? summaryRes.data;
      setSummary(sumData as PerfSummary);

      const h = histRes.data?.data ?? histRes.data;
      const rows: TradeRow[] = Array.isArray(h?.trades) ? h.trades : Array.isArray(h) ? h : [];
      setTrades(rows);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to load performance");
      setSummary(null);
      setTrades([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(period);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  useEffect(() => {
    api
      .get("/api/performance/feedback-stats")
      .then((res) => setFeedbackStats(res.data))
      .catch(() => setFeedbackStats(null));
  }, []);

  const layout: "novice" | "self" | "pro" | "crypto" = useMemo(() => {
    if (traderClass === "complete_novice" || traderClass === "curious_saver") return "novice";
    if (traderClass === "self_taught") return "self";
    if (traderClass === "crypto_native") return "crypto";
    return "pro";
  }, [traderClass]);

  const monthPnl = summary?.total_return_gbp ?? 0;
  const monthTone = monthPnl >= 0 ? "good" : "bad";

  const periodLabel = period === 30 ? "30d" : period === 90 ? "90d" : "1y";

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-dark-950">
        <Loader2 size={26} className="animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-dark-950">
      <RiskWarning variant="bar" />
      <div className="px-4 py-6 md:px-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <BarChart3 size={18} className="text-brand-400" />
              <h1 className="text-lg font-bold text-white">Performance</h1>
            </div>
            <div className="mt-1 text-xs text-dark-400">
              Period: {periodLabel} · Trades: {summary?.total_trades ?? 0}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-xl border border-dark-800 bg-dark-950 p-1">
              {[30, 90, 365].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setPeriod(d as any)}
                  className={clsx(
                    "rounded-lg px-3 py-1.5 text-xs font-semibold",
                    period === d ? "bg-dark-800 text-white" : "text-dark-300 hover:text-white",
                  )}
                >
                  {d === 30 ? "30d" : d === 90 ? "90d" : "1y"}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={() => load(period)}
              className="btn-outline text-xs"
            >
              Refresh
            </button>

            <button type="button" onClick={() => setTaxOpen(true)} className="btn-outline text-xs">
              <Download size={14} /> Tax export
            </button>
            <button type="button" onClick={() => {}} className="btn-outline text-xs">
              <Share2 size={14} /> Share
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
            {error}
          </div>
        )}

        {/* Layout: novice / saver */}
        {layout === "novice" && summary && (
          <div className="space-y-6">
            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div
                className={clsx(
                  "text-2xl font-extrabold md:text-3xl",
                  monthPnl >= 0 ? "text-green-300" : "text-amber-200",
                )}
              >
                {monthPnl >= 0
                  ? `You are up ${formatGBP(monthPnl)} this month`
                  : `Apex is learning - down ${formatGBP(Math.abs(monthPnl))} this month`}
              </div>
              {summary.encouragement && (
                <div className="mt-2 text-sm text-dark-200">{summary.encouragement}</div>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5 md:col-span-2">
                <div className="text-sm font-semibold text-white">Progress toward your goal</div>
                <div className="mt-2 text-sm text-dark-200">
                  {summary.goal_progress_message || "Apex is tracking your progress."}
                </div>
              </div>

              <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
                <div className="text-sm font-semibold text-white">Trust Ladder</div>
                <div className="mt-2 text-sm text-dark-200">
                  Stage {summary.trust_ladder_summary?.stage ?? 1}
                </div>
                <div className="mt-1 text-xs text-dark-400">
                  Unlocks next in {summary.trust_ladder_summary?.days_until_advance ?? 0} days
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div className="text-sm font-semibold text-white">Apex weekly message</div>
              <div className="mt-3 max-w-3xl rounded-2xl border border-dark-800 bg-dark-900/30 p-4 text-sm text-dark-200">
                {Object.values(summary.monthly_summary || {})[0] !== undefined
                  ? "Apex: Keep building consistency — I’ll keep looking for clean setups and protect downside."
                  : "Apex: No closed trades yet — I’m watching the market for you."}
              </div>
            </div>

            <div className="rounded-2xl border border-dark-800 bg-dark-950">
              <div className="border-b border-dark-800 px-5 py-3">
                <div className="text-sm font-semibold text-white">Trades</div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px]">
                  <thead className="bg-dark-900/40">
                    <tr className="text-left text-xs font-semibold text-dark-400">
                      <th className="px-5 py-3">Date</th>
                      <th className="px-5 py-3">Company</th>
                      <th className="px-5 py-3 text-right">P&L (GBP)</th>
                      <th className="px-5 py-3 text-right">Feedback</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-dark-800">
                    {trades.slice(0, 50).map((t) => {
                      const pnl = (t.profit || 0) - (t.loss || 0);
                      const name = BRAND_NAMES[t.symbol?.toUpperCase()] ?? t.symbol?.toUpperCase();
                      return (
                        <tr key={t.id} className="hover:bg-dark-900/30">
                          <td className="px-5 py-3 text-sm text-dark-300">{dateShort(t.closed_at || t.created_at)}</td>
                          <td className="px-5 py-3 text-sm font-semibold text-white">{name}</td>
                          <td className={clsx("px-5 py-3 text-right text-sm font-bold tabular-nums", pnl >= 0 ? "text-green-300" : "text-red-300")}>
                            {formatGBP(pnl)}
                          </td>
                          <td className="px-5 py-3">
                            <FeedbackThumbs tradeId={t.id} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Your influence on Apex */}
            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div className="text-sm font-semibold text-white">Your influence on Apex</div>
              {feedbackStats ? (
                <>
                  {feedbackStats.total_rated === 0 ? (
                    <div className="mt-2 text-sm text-dark-200">
                      You haven&apos;t rated any trades yet. Head to History to give Apex feedback on its decisions.
                      <div className="mt-3">
                        <a
                          href="/app?tab=history"
                          className="inline-flex items-center rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-semibold text-black hover:bg-brand-400"
                        >
                          Go to History
                        </a>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="mt-2 text-sm text-dark-200">
                        You have rated {feedbackStats.total_rated} of Apex&apos;s decisions.{" "}
                        {feedbackStats.positive_pct.toFixed(1)}% were rated positively. Apex uses your ratings to refine
                        its strategy for you.
                      </div>
                      <div className="mt-4">
                        <div className="flex items-center justify-between text-xs text-dark-300">
                          <span>Trust score</span>
                          <span>{feedbackStats.trust_score}/100</span>
                        </div>
                        <div className="mt-1 h-2 w-full rounded-full bg-dark-900">
                          <div
                            className="h-2 rounded-full"
                            style={{
                              width: `${Math.max(0, Math.min(100, feedbackStats.trust_score))}%`,
                              backgroundColor:
                                feedbackStats.trust_score > 70
                                  ? "#22c55e"
                                  : feedbackStats.trust_score >= 40
                                  ? "#f59e0b"
                                  : "#ef4444",
                            }}
                          />
                        </div>
                      </div>
                      {feedbackStats.recent_comments && feedbackStats.recent_comments.length > 0 && (
                        <div className="mt-3">
                          <div className="text-xs font-semibold text-dark-300">Recent feedback</div>
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            {feedbackStats.recent_comments.map((c, idx) => (
                              <span
                                key={idx}
                                className="max-w-xs truncate rounded-full bg-dark-900 px-2 py-1 text-[11px] text-dark-200"
                                title={c}
                              >
                                {c.length > 60 ? `${c.slice(0, 57)}…` : c}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                  <div className="mt-3 text-[11px] text-dark-500">
                    The more you rate, the more personalised Apex becomes. Your feedback directly changes how Apex trades
                    for you.
                  </div>
                </>
              ) : (
                <div className="mt-2 text-sm text-dark-400">Loading your feedback influence…</div>
              )}
            </div>
          </div>
        )}

        {/* Layout: self_taught */}
        {layout === "self" && summary && (
          <div className="space-y-6">
            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div className="flex flex-wrap items-center gap-3">
                <div className="text-2xl font-extrabold text-white tabular-nums">
                  {summary.total_return_pct.toFixed(2)}%
                </div>
                <span
                  className={clsx(
                    "rounded-xl border px-3 py-1 text-xs font-semibold",
                    pillTone(summary.vs_spy ?? 0),
                  )}
                >
                  vs S&P 500: {formatPct(summary.vs_spy ?? 0)}
                </span>
              </div>
              <div className="mt-2 text-xs text-dark-400">
                Return vs buy-and-hold: {formatPct(summary.vs_buy_hold ?? 0)} · Avg hold time:{" "}
                {(summary.avg_hold_time_days ?? 0).toFixed(2)}d
              </div>
            </div>

            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div className="text-sm font-semibold text-white">Performance chart</div>
              <div className="mt-3 h-44 rounded-xl border border-dark-800 bg-dark-900/30" />
              <div className="mt-2 text-xs text-dark-500">
                Includes comparison line: “if you had held instead” (placeholder).
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              <StatCard label="Win rate" value={`${summary.win_rate.toFixed(1)}%`} />
              <StatCard label="Avg hold time" value={`${(summary.avg_hold_time_days ?? 0).toFixed(2)}d`} />
              <StatCard label="Return vs buy & hold" value={formatPct(summary.vs_buy_hold ?? 0)} />
            </div>

            <TradeListSelf trades={trades} />
          </div>
        )}

        {/* Layout: experienced / semi_institutional */}
        {layout === "pro" && summary && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatCard label="Total return" value={`${summary.total_return_pct.toFixed(2)}%`} tone={summary.total_return_pct >= 0 ? "good" : "bad"} />
              <StatCard label="Sharpe" value={(summary.sharpe_ratio ?? 0).toFixed(3)} />
              <StatCard label="Max drawdown" value={`${(summary.max_drawdown ?? 0).toFixed(3)}%`} />
              <StatCard label="Win rate" value={`${summary.win_rate.toFixed(1)}%`} />
            </div>

            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-white">Portfolio value</div>
                <button type="button" onClick={() => {}} className="btn-outline text-xs">
                  Log scale
                </button>
              </div>
              <div className="mt-3 h-52 rounded-xl border border-dark-800 bg-dark-900/30" />
              <div className="mt-2 text-xs text-dark-500">SPY overlay (placeholder).</div>
            </div>

            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div className="text-sm font-semibold text-white">Sector P&L breakdown</div>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[520px]">
                  <thead className="text-left text-xs font-semibold text-dark-400">
                    <tr>
                      <th className="py-2">Sector</th>
                      <th className="py-2 text-right">Trades</th>
                      <th className="py-2 text-right">P&L</th>
                      <th className="py-2 text-right">Win rate</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-dark-800 text-sm">
                    {Object.keys(summary.sector_pnl || {}).length === 0 ? (
                      <tr>
                        <td className="py-3 text-dark-400" colSpan={4}>
                          Sector P&L is unavailable until sectors are stored per trade.
                        </td>
                      </tr>
                    ) : (
                      Object.entries(summary.sector_pnl || {}).map(([sector, pnl]) => (
                        <tr key={sector}>
                          <td className="py-3 text-white">{sector}</td>
                          <td className="py-3 text-right text-dark-300">—</td>
                          <td className={clsx("py-3 text-right tabular-nums", pnl >= 0 ? "text-green-300" : "text-red-300")}>
                            {formatGBP(pnl)}
                          </td>
                          <td className="py-3 text-right text-dark-300">—</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div className="text-sm font-semibold text-white">Recent AI decisions</div>
              <div className="mt-2 text-xs text-dark-400">
                Last 10 decisions with signal/confidence/snippet (placeholder — requires backend endpoint).
              </div>
              <div className="mt-3 space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="rounded-xl border border-dark-800 bg-dark-950 p-3 text-xs text-dark-300">
                    BUY · 72% · “Momentum improving; risk managed with tight SL.”
                  </div>
                ))}
              </div>
            </div>

            <TradeListPro trades={trades} />
          </div>
        )}

        {/* Layout: crypto_native */}
        {layout === "crypto" && summary && (
          <div className="space-y-6">
            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div className="flex flex-wrap items-center gap-3">
                <div className="text-2xl font-extrabold text-white tabular-nums">
                  {summary.total_return_pct.toFixed(2)}%
                </div>
                <div className="rounded-xl border border-dark-800 bg-dark-950 px-3 py-1 text-xs font-semibold text-dark-200">
                  vs HODLing BTC: {formatPct(summary.vs_bitcoin_hold ?? 0)}
                </div>
              </div>
              <div className="mt-2 text-xs text-dark-400">
                Total fees paid: £{Number(summary.total_fees_paid ?? 0).toFixed(2)}
              </div>
            </div>

            <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
              <div className="text-sm font-semibold text-white">Portfolio chart</div>
              <div className="mt-3 h-52 rounded-xl border border-dark-800 bg-dark-900/30" />
              <div className="mt-2 text-xs text-dark-500">BTC reference line (placeholder).</div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="text-xs text-dark-500">Best crypto</div>
                <div className="mt-1 text-sm font-bold text-white">
                  {summary.best_crypto?.symbol ?? "—"}
                </div>
                <div className="mt-1 text-xs text-green-300 tabular-nums">
                  {summary.best_crypto ? `${summary.best_crypto.pct_gain.toFixed(2)}% · ${formatGBP(summary.best_crypto.pnl_gbp)}` : "—"}
                </div>
              </div>
              <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="text-xs text-dark-500">Worst crypto</div>
                <div className="mt-1 text-sm font-bold text-white">
                  {summary.worst_crypto?.symbol ?? "—"}
                </div>
                <div className="mt-1 text-xs text-red-300 tabular-nums">
                  {summary.worst_crypto ? `${summary.worst_crypto.pct_loss.toFixed(2)}% · ${formatGBP(summary.worst_crypto.pnl_gbp)}` : "—"}
                </div>
              </div>
              <StatCard label="Total fees paid" value={`£${Number(summary.total_fees_paid ?? 0).toFixed(2)}`} />
            </div>

            <TradeListCrypto trades={trades} />
          </div>
        )}
      </div>

      {/* Tax summary modal (Phase 27) */}
      {taxOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <div className="w-full max-w-lg rounded-2xl border border-dark-800 bg-dark-950 p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-white">Tax export</div>
                <div className="mt-1 text-xs text-dark-400">Account type: {ACCOUNT_TYPE[traderClass]}</div>
              </div>
              <button
                type="button"
                onClick={() => setTaxOpen(false)}
                className="rounded-lg p-2 text-dark-400 hover:bg-dark-900 hover:text-white"
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>

            <div className="mt-4 rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-200">
              <div className="flex justify-between gap-3">
                <span className="text-dark-400">Period</span>
                <span className="font-semibold text-white">{periodLabel}</span>
              </div>
              <div className="mt-2 flex justify-between gap-3">
                <span className="text-dark-400">Total trades</span>
                <span className="font-semibold tabular-nums text-white">{summary?.total_trades ?? 0}</span>
              </div>
              <div className="mt-2 flex justify-between gap-3">
                <span className="text-dark-400">Total return (GBP)</span>
                <span className={clsx("font-semibold tabular-nums", monthPnl >= 0 ? "text-green-300" : "text-red-300")}>
                  {formatGBP(monthPnl)}
                </span>
              </div>
              <div className="mt-2 text-xs text-dark-400">Account type: {ACCOUNT_TYPE[traderClass]}</div>
            </div>

            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setTaxOpen(false)} className="btn-outline">
                Close
              </button>
              <button
                type="button"
                onClick={() => {
                  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
                  const url = `${base}/api/trades/export?days=${period}`;
                  window.open(url, "_blank");
                }}
                className="btn-primary"
              >
                Download CSV
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}

function formatPct(n: number, dp: number = 2) {
  if (!Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(dp)}%`;
}

function TradeListSelf({ trades }: { trades: TradeRow[] }) {
  return (
    <div className="rounded-2xl border border-dark-800 bg-dark-950">
      <div className="border-b border-dark-800 px-5 py-3">
        <div className="text-sm font-semibold text-white">Trades</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px]">
          <thead className="bg-dark-900/40">
            <tr className="text-left text-xs font-semibold text-dark-400">
              <th className="px-5 py-3">Symbol</th>
              <th className="px-5 py-3 text-right">Entry</th>
              <th className="px-5 py-3 text-right">Exit</th>
              <th className="px-5 py-3 text-right">P&L GBP</th>
              <th className="px-5 py-3 text-right">P&L %</th>
              <th className="px-5 py-3">Hold</th>
              <th className="px-5 py-3 text-right">Feedback</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-dark-800">
            {trades.slice(0, 80).map((t) => {
              const pnl = (t.profit || 0) - (t.loss || 0);
              return (
                <tr key={t.id} className="hover:bg-dark-900/30">
                  <td className="px-5 py-3 text-sm font-semibold text-white">{t.symbol}</td>
                  <td className="px-5 py-3 text-right text-sm text-dark-200 tabular-nums">
                    {t.entry_price?.toFixed(2) ?? "—"}
                  </td>
                  <td className="px-5 py-3 text-right text-sm text-dark-200 tabular-nums">
                    {t.exit_price?.toFixed(2) ?? "—"}
                  </td>
                  <td className={clsx("px-5 py-3 text-right text-sm font-bold tabular-nums", pnl >= 0 ? "text-green-300" : "text-red-300")}>
                    {formatGBP(pnl)}
                  </td>
                  <td className={clsx("px-5 py-3 text-right text-sm font-semibold tabular-nums", pnl >= 0 ? "text-green-300" : "text-red-300")}>
                    {t.profit_percent !== null && t.profit_percent !== undefined ? `${t.profit_percent.toFixed(2)}%` : "—"}
                  </td>
                  <td className="px-5 py-3 text-sm text-dark-300">
                    {t.created_at && t.closed_at ? holdTime(t.created_at, t.closed_at) : "—"}
                  </td>
                  <td className="px-5 py-3">
                    <FeedbackThumbs tradeId={t.id} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TradeListPro({ trades }: { trades: TradeRow[] }) {
  return (
    <div className="rounded-2xl border border-dark-800 bg-dark-950">
      <div className="border-b border-dark-800 px-5 py-3">
        <div className="text-sm font-semibold text-white">Trade list</div>
        <div className="mt-1 text-xs text-dark-500">Sortable columns (placeholder — needs client-side sort state).</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px]">
          <thead className="bg-dark-900/40">
            <tr className="text-left text-xs font-semibold text-dark-400">
              <th className="px-5 py-3">Date</th>
              <th className="px-5 py-3">Symbol</th>
              <th className="px-5 py-3">Side</th>
              <th className="px-5 py-3 text-right">Qty</th>
              <th className="px-5 py-3 text-right">Entry</th>
              <th className="px-5 py-3 text-right">Exit</th>
              <th className="px-5 py-3 text-right">P&L</th>
              <th className="px-5 py-3 text-right">P&L %</th>
              <th className="px-5 py-3 text-right">Feedback</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-dark-800">
            {trades.slice(0, 100).map((t) => {
              const pnl = (t.profit || 0) - (t.loss || 0);
              return (
                <tr key={t.id} className="hover:bg-dark-900/30">
                  <td className="px-5 py-3 text-sm text-dark-300">{dateShort(t.closed_at || t.created_at)}</td>
                  <td className="px-5 py-3 text-sm font-semibold text-white">{t.symbol}</td>
                  <td className="px-5 py-3 text-sm text-dark-200">{t.side}</td>
                  <td className="px-5 py-3 text-right text-sm text-dark-200 tabular-nums">—</td>
                  <td className="px-5 py-3 text-right text-sm text-dark-200 tabular-nums">{t.entry_price?.toFixed(2) ?? "—"}</td>
                  <td className="px-5 py-3 text-right text-sm text-dark-200 tabular-nums">{t.exit_price?.toFixed(2) ?? "—"}</td>
                  <td className={clsx("px-5 py-3 text-right text-sm font-bold tabular-nums", pnl >= 0 ? "text-green-300" : "text-red-300")}>{formatGBP(pnl)}</td>
                  <td className={clsx("px-5 py-3 text-right text-sm font-semibold tabular-nums", pnl >= 0 ? "text-green-300" : "text-red-300")}>
                    {t.profit_percent !== null && t.profit_percent !== undefined ? `${t.profit_percent.toFixed(2)}%` : "—"}
                  </td>
                  <td className="px-5 py-3">
                    <FeedbackThumbs tradeId={t.id} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TradeListCrypto({ trades }: { trades: TradeRow[] }) {
  return (
    <div className="rounded-2xl border border-dark-800 bg-dark-950">
      <div className="border-b border-dark-800 px-5 py-3">
        <div className="text-sm font-semibold text-white">Trades</div>
        <div className="mt-1 text-xs text-dark-500">Fee impact per trade (placeholder — requires fee fields per trade).</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px]">
          <thead className="bg-dark-900/40">
            <tr className="text-left text-xs font-semibold text-dark-400">
              <th className="px-5 py-3">Date</th>
              <th className="px-5 py-3">Symbol</th>
              <th className="px-5 py-3">Side</th>
              <th className="px-5 py-3 text-right">P&L GBP</th>
              <th className="px-5 py-3 text-right">P&L %</th>
              <th className="px-5 py-3 text-right">Fees</th>
              <th className="px-5 py-3 text-right">Feedback</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-dark-800">
            {trades.slice(0, 100).map((t) => {
              const pnl = (t.profit || 0) - (t.loss || 0);
              return (
                <tr key={t.id} className="hover:bg-dark-900/30">
                  <td className="px-5 py-3 text-sm text-dark-300">{dateShort(t.closed_at || t.created_at)}</td>
                  <td className="px-5 py-3 text-sm font-semibold text-white">{t.symbol}</td>
                  <td className="px-5 py-3 text-sm text-dark-200">{t.side}</td>
                  <td className={clsx("px-5 py-3 text-right text-sm font-bold tabular-nums", pnl >= 0 ? "text-green-300" : "text-red-300")}>{formatGBP(pnl)}</td>
                  <td className={clsx("px-5 py-3 text-right text-sm font-semibold tabular-nums", pnl >= 0 ? "text-green-300" : "text-red-300")}>
                    {t.profit_percent !== null && t.profit_percent !== undefined ? `${t.profit_percent.toFixed(2)}%` : "—"}
                  </td>
                  <td className="px-5 py-3 text-right text-sm text-dark-300 tabular-nums">—</td>
                  <td className="px-5 py-3">
                    <FeedbackThumbs tradeId={t.id} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function holdTime(startIso: string, endIso: string) {
  const s = new Date(startIso).getTime();
  const e = new Date(endIso).getTime();
  if (Number.isNaN(s) || Number.isNaN(e) || e < s) return "—";
  const mins = Math.floor((e - s) / 60000);
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  if (h < 48) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

