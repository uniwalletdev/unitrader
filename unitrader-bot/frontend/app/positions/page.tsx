"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronUp,
  Loader2,
  Lock,
  Minus,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { api, authApi, exchangeApi, tradingApi, type AccountBalance } from "@/lib/api";
import RiskWarning from "@/components/layout/RiskWarning";
import { useLivePrice } from "@/hooks/useLivePrice";
import { formatPrice } from "@/utils/formatPrice";

type TraderClass =
  | "complete_novice"
  | "curious_saver"
  | "self_taught"
  | "experienced"
  | "semi_institutional"
  | "crypto_native";

type Position = {
  id: string;
  symbol: string;
  side: "BUY" | "SELL" | string;
  quantity: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  created_at: string | null;
  exchange?: string | null;
  // optional / future
  is_paper?: boolean;
  sector?: string | null;
  beta?: number | null;
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
};

function clsx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "bad" | "neutral";
}) {
  const color =
    tone === "good"
      ? "text-green-300"
      : tone === "bad"
        ? "text-red-300"
        : "text-white";
  return (
    <div className="rounded-xl border border-dark-800 bg-dark-950 p-4">
      <div className="text-xs text-dark-500">{label}</div>
      <div className={clsx("mt-1 text-lg font-bold tabular-nums", color)}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-dark-500">{sub}</div>}
    </div>
  );
}

function Sparkline({ points }: { points: number[] }) {
  const w = 68;
  const h = 18;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const scaleX = (i: number) =>
    points.length <= 1 ? 0 : (i / (points.length - 1)) * w;
  const scaleY = (v: number) => {
    if (max === min) return h / 2;
    return h - ((v - min) / (max - min)) * h;
  };
  const d = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"}${scaleX(i).toFixed(1)} ${scaleY(p).toFixed(1)}`,
    )
    .join(" ");
  const up = points[points.length - 1] >= points[0];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="opacity-90">
      <path
        d={d}
        fill="none"
        stroke={up ? "rgba(34,197,94,0.9)" : "rgba(239,68,68,0.9)"}
        strokeWidth={2}
      />
    </svg>
  );
}

function formatUSD(n: number) {
  const v = Number.isFinite(n) ? n : 0;
  const sign = v >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function toHoldTime(createdAtIso: string | null) {
  if (!createdAtIso) return "—";
  const t = new Date(createdAtIso).getTime();
  if (Number.isNaN(t)) return "—";
  const diffMin = Math.floor((Date.now() - t) / 60000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 48) return `${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d`;
}

function CloseConfirmModal({
  open,
  symbol,
  onClose,
  onConfirm,
}: {
  open: boolean;
  symbol: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-md rounded-2xl border border-dark-800 bg-dark-950 p-5 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-white">Close position</div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-dark-400 hover:bg-dark-900 hover:text-white"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <div className="mt-3 text-sm text-dark-200">
          Are you sure you want to close{" "}
          <span className="font-semibold text-white">{symbol}</span> at market?
        </div>
        <div className="mt-5 flex gap-2">
          <button type="button" onClick={onClose} className="btn-outline w-1/2">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} className="btn-primary w-1/2">
            Close now
          </button>
        </div>
      </div>
    </div>
  );
}

function PnlHelp({ value }: { value: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="inline-flex flex-col items-end gap-2">
      <div className="text-sm font-bold tabular-nums">{value}</div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded-md border border-dark-800 bg-dark-950 px-2 py-1 text-[11px] text-dark-300 hover:text-white"
      >
        What does this mean? {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <div className="max-w-xs rounded-xl border border-dark-800 bg-dark-950 p-3 text-xs text-dark-300">
          This is your profit/loss if you closed the position right now. It updates
          live as the market price moves.
        </div>
      )}
    </div>
  );
}

export default function PositionsPage() {
  const router = useRouter();
  const { isLoaded: authLoaded, isSignedIn, getToken } = useAuth();
  const [traderClass, setTraderClass] = useState<TraderClass>("complete_novice");
  const [positions, setPositions] = useState<Position[]>([]);
  const [accounts, setAccounts] = useState<AccountBalance[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState<{ open: boolean; id: string; symbol: string }>({
    open: false,
    id: "",
    symbol: "",
  });

  // semi_institutional bulk selection
  const [selectedIds, setSelectedIds] = useState<Record<string, boolean>>({});

  // Sparkline cache: positionId -> points
  const [sparks, setSparks] = useState<Record<string, number[]>>({});

  const load = async () => {
    setError(null);
    setLoading(true);
    try {
      // Ensure backend auth header is present for protected endpoints
      const token = await getToken();
      if (token) api.defaults.headers.common.Authorization = `Bearer ${token}`;

      const [balancesRes, settingsRes, posRes] = await Promise.all([
        exchangeApi.balances(),
        authApi.getSettings(),
        tradingApi.openPositions(
          selectedAccountId !== "all"
            ? { trading_account_id: selectedAccountId }
            : undefined,
        ),
      ]);
      setAccounts(balancesRes.data?.data ?? []);
      setTraderClass((settingsRes.data?.trader_class as TraderClass) || "complete_novice");

      const d = posRes.data?.data ?? posRes.data;
      const arr: Position[] = Array.isArray(d)
        ? d
        : Array.isArray(d?.positions)
          ? d.positions
          : [];
      setPositions(arr);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to load positions");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authLoaded) return;
    if (!isSignedIn) {
      setLoading(false);
      setError("Please sign in to view your positions.");
      return;
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoaded, isSignedIn, selectedAccountId]);

  const [livePositions, paperPositions] = useMemo(() => {
    const live: Position[] = [];
    const paper: Position[] = [];
    for (const p of positions) {
      if ((p as any).is_paper) paper.push(p);
      else live.push(p);
    }
    return [live, paper];
  }, [positions]);

  const stats = useMemo(() => {
    const openCount = livePositions.length;
    const best = livePositions[0]?.symbol ?? "—";
    const worst = livePositions[0]?.symbol ?? "—";
    return { openCount, best, worst };
  }, [livePositions]);

  // Load sparklines for saver/self_taught (5 points)
  useEffect(() => {
    if (!(traderClass === "curious_saver" || traderClass === "self_taught")) return;
    let mounted = true;
    (async () => {
      const toFetch = livePositions.filter((p) => !sparks[p.id]).slice(0, 20);
      await Promise.all(
        toFetch.map(async (p) => {
          try {
            if (p.symbol.includes("/") || p.symbol.includes("_")) return;
            const res = await api.get("/api/trading/ohlcv", {
              params: { symbol: p.symbol, days: 5, interval: "1day" },
            });
            const d = res.data?.data ?? res.data;
            const bars = Array.isArray(d) ? (d as any[]) : [];
            const pts = bars
              .map((b) => Number(b.close))
              .filter((n) => Number.isFinite(n));
            if (!pts.length) return;
            if (!mounted) return;
            setSparks((prev) => ({ ...prev, [p.id]: pts.slice(-5) }));
          } catch {
            // ignore
          }
        }),
      );
    })();
    return () => {
      mounted = false;
    };
  }, [traderClass, livePositions, sparks]);

  const emptyMessage = useMemo(() => {
    if (traderClass === "complete_novice") {
      return "No open positions yet — when Unitrader places a trade, it’ll show up here with live profit/loss.";
    }
    if (traderClass === "curious_saver") {
      return "No open positions yet — start a trade to track live P&L and hold time.";
    }
    if (traderClass === "self_taught") {
      return "No open positions yet — once you trade, you’ll see live P&L%, SL/TP context, and sparklines.";
    }
    if (traderClass === "crypto_native") {
      return "No open positions — set up a crypto trade to track live P&L and 24h moves.";
    }
    return "No open positions.";
  }, [traderClass]);

  const isSemi = traderClass === "semi_institutional";

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-dark-950">
        <Loader2 className="animate-spin text-brand-500" size={26} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-dark-950">
      <RiskWarning variant="bar" />
      <div className="border-b border-dark-800 bg-dark-950 px-4 py-4 md:px-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-base font-bold text-white md:text-xl">Positions</div>
            <div className="text-xs text-dark-400">Live monitoring of your open trades</div>
          </div>
          <div className="flex gap-2">
            <button onClick={() => load()} className="btn-outline gap-2 text-xs">
              <RefreshCw size={14} /> Refresh
            </button>
            <button onClick={() => router.push("/app")} className="btn-outline text-xs">
              Back
            </button>
          </div>
        </div>
        {accounts.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setSelectedAccountId("all")}
              className={clsx(
                "rounded-lg border px-3 py-1.5 text-xs",
                selectedAccountId === "all"
                  ? "border-brand-500/40 bg-brand-500/10 text-brand-300"
                  : "border-dark-800 bg-dark-950 text-dark-300",
              )}
            >
              All accounts
            </button>
            {accounts.map((account) => {
              const displayMode =
                String(account.exchange || "").toLowerCase() === "coinbase"
                  ? "live"
                  : account.is_paper
                    ? "paper"
                    : "live";
              const accountId = account.trading_account_id ?? `${account.exchange}-${displayMode}`;
              return (
                <button
                  key={accountId}
                  type="button"
                  onClick={() => setSelectedAccountId(accountId)}
                  className={clsx(
                    "rounded-lg border px-3 py-1.5 text-xs",
                    selectedAccountId === accountId
                      ? "border-brand-500/40 bg-brand-500/10 text-brand-300"
                      : "border-dark-800 bg-dark-950 text-dark-300",
                  )}
                >
                  {account.account_label || `${account.exchange} ${displayMode}`}
                  {typeof (account as any).balance_note === "string" &&
                    (account as any).balance_note.toLowerCase().includes("cached") && (
                    <span className="ml-2 text-[10px] text-dark-500">(cached)</span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 md:px-6">
        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
            <div className="flex items-start gap-2">
              <AlertCircle size={16} className="mt-0.5" />
              <div>{error}</div>
            </div>
          </div>
        )}

        {/* Header stat cards */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Total P&L" value="—" sub="Live (per position)" />
          <StatCard label="Open count" value={String(stats.openCount)} />
          <StatCard label="Best position" value={stats.best} />
          <StatCard label="Worst position" value={stats.worst} />
        </div>

        {isSemi && livePositions.length > 0 && (
          <div className="flex items-center justify-between gap-3 rounded-xl border border-dark-800 bg-dark-950 p-4">
            <div className="text-xs text-dark-400">
              Selected:{" "}
              <span className="font-semibold text-white">
                {Object.values(selectedIds).filter(Boolean).length}
              </span>
            </div>
            <button
              type="button"
              onClick={async () => {
                const ids = Object.entries(selectedIds)
                  .filter(([, v]) => v)
                  .map(([id]) => id);
                for (const id of ids) {
                  try {
                    await tradingApi.closePosition(id);
                  } catch {
                    // ignore
                  }
                }
                await load();
              }}
              className="btn-primary text-xs"
            >
              Close selected
            </button>
          </div>
        )}

        {/* Live positions */}
        <div className="rounded-2xl border border-dark-800 bg-dark-950">
          <div className="border-b border-dark-800 px-4 py-3">
            <div className="text-sm font-semibold text-white">Live positions</div>
            <div className="text-xs text-dark-400">Real-time prices update automatically</div>
          </div>

          {livePositions.length === 0 ? (
            <div className="p-8 text-center">
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-dark-900">
                <Minus size={18} className="text-dark-500" />
              </div>
              <div className="text-sm font-semibold text-white">No open positions</div>
              <div className="mt-1 text-xs text-dark-400">{emptyMessage}</div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px]">
                <thead className="bg-dark-900/40">
                  <tr className="text-left text-xs font-semibold text-dark-400">
                    {isSemi && <th className="px-4 py-3">Select</th>}
                    <th className="px-4 py-3">
                      {traderClass === "complete_novice" ? "Asset" : "Symbol"}
                    </th>
                    <th className="px-4 py-3">Side</th>
                    {(traderClass === "experienced" || traderClass === "semi_institutional") && (
                      <th className="px-4 py-3 text-right">Qty</th>
                    )}
                    <th className="px-4 py-3 text-right">Entry</th>
                    <th className="px-4 py-3 text-right">Current</th>
                    <th className="px-4 py-3 text-right">P&L</th>
                    {(traderClass === "curious_saver" ||
                      traderClass === "self_taught" ||
                      traderClass === "experienced" ||
                      traderClass === "semi_institutional" ||
                      traderClass === "crypto_native") && (
                      <th className="px-4 py-3 text-right">P&L %</th>
                    )}
                    {(traderClass === "curious_saver" || traderClass === "self_taught") && (
                      <th className="px-4 py-3">Hold</th>
                    )}
                    {(traderClass === "curious_saver" || traderClass === "self_taught") && (
                      <th className="px-4 py-3">Trend</th>
                    )}
                    {(traderClass === "experienced" || traderClass === "semi_institutional") && (
                      <>
                        <th className="px-4 py-3 text-right">SL dist %</th>
                        <th className="px-4 py-3 text-right">TP dist %</th>
                        <th className="px-4 py-3">Actions</th>
                      </>
                    )}
                    {traderClass === "semi_institutional" && (
                      <>
                        <th className="px-4 py-3">Sector</th>
                        <th className="px-4 py-3 text-right">Beta</th>
                      </>
                    )}
                    {traderClass === "crypto_native" && (
                      <>
                        <th className="px-4 py-3 text-right">24h</th>
                        <th className="px-4 py-3">Alerts</th>
                      </>
                    )}
                    {traderClass === "complete_novice" && <th className="px-4 py-3">Status</th>}
                    <th className="px-4 py-3 text-right">Close</th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-dark-800">
                  {livePositions.map((p) => (
                    <PositionRow
                      key={p.id}
                      p={p}
                      traderClass={traderClass}
                      sparkPoints={sparks[p.id]}
                      bulk={isSemi}
                      bulkChecked={!!selectedIds[p.id]}
                      onBulkChange={(v) => setSelectedIds((prev) => ({ ...prev, [p.id]: v }))}
                      onClose={() => setClosing({ open: true, id: p.id, symbol: p.symbol })}
                      onPatched={load}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Paper positions */}
        <div className="rounded-2xl border border-dark-800 bg-dark-950">
          <div className="border-b border-dark-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <Lock size={14} className="text-amber-300" />
              <div className="text-sm font-semibold text-white">Practice positions</div>
            </div>
            <div className="text-xs text-dark-400">Positions created with practice money</div>
          </div>
          {paperPositions.length === 0 ? (
            <div className="p-6 text-xs text-dark-400">No practice positions.</div>
          ) : (
            <div className="p-4 text-xs text-dark-300">
              This section is ready, but your backend must include an <code>is_paper</code> flag on positions for separation.
            </div>
          )}
        </div>
      </div>

      <CloseConfirmModal
        open={closing.open}
        symbol={closing.symbol}
        onClose={() => setClosing({ open: false, id: "", symbol: "" })}
        onConfirm={async () => {
          try {
            await tradingApi.closePosition(closing.id);
          } catch {
            // ignore
          } finally {
            setClosing({ open: false, id: "", symbol: "" });
            await load();
          }
        }}
      />
    </div>
  );
}

function PositionRow({
  p,
  traderClass,
  sparkPoints,
  bulk,
  bulkChecked,
  onBulkChange,
  onClose,
  onPatched,
}: {
  p: Position;
  traderClass: TraderClass;
  sparkPoints?: number[];
  bulk?: boolean;
  bulkChecked?: boolean;
  onBulkChange?: (v: boolean) => void;
  onClose: () => void;
  onPatched: () => void;
}) {
  const live = useLivePrice(p.symbol);
  const current = live.price ?? p.entry_price;
  const direction = (p.side || "").toUpperCase() === "SELL" ? -1 : 1;
  const pnl = (current - p.entry_price) * p.quantity * direction;
  const pnlPct = ((current - p.entry_price) / p.entry_price) * 100 * direction;
  const good = pnl >= 0;

  const slDistPct = ((current - p.stop_loss) / current) * 100;
  const tpDistPct = ((p.take_profit - current) / current) * 100;

  const [editOpen, setEditOpen] = useState(false);
  const [slPct, setSlPct] = useState("5");
  const [tpPct, setTpPct] = useState("10");
  const [saving, setSaving] = useState(false);

  const sideBadge =
    (p.side || "").toUpperCase() === "BUY" ? (
      <span className="inline-flex items-center gap-1 rounded-lg bg-brand-500/10 px-2 py-1 text-xs font-semibold text-brand-300">
        <TrendingUp size={13} /> BUY
      </span>
    ) : (
      <span className="inline-flex items-center gap-1 rounded-lg bg-red-500/10 px-2 py-1 text-xs font-semibold text-red-300">
        <TrendingDown size={13} /> SELL
      </span>
    );

  const symbolCell =
    traderClass === "complete_novice" ? (
      <div className="min-w-[160px]">
        <div className="text-sm font-semibold text-white">
          {BRAND_NAMES[p.symbol.toUpperCase()] ?? p.symbol.toUpperCase()}
        </div>
        <div className="text-xs text-dark-500">{p.symbol.toUpperCase()}</div>
      </div>
    ) : (
      <div className="text-sm font-semibold text-white">{p.symbol.toUpperCase()}</div>
    );

  const pnlText = formatUSD(pnl);

  return (
    <>
      <tr className="hover:bg-dark-900/40">
        {bulk && (
          <td className="px-4 py-3">
            <input
              type="checkbox"
              checked={!!bulkChecked}
              onChange={(e) => onBulkChange?.(e.target.checked)}
              className="h-4 w-4 accent-brand-500"
            />
          </td>
        )}
        <td className="px-4 py-3">{symbolCell}</td>
        <td className="px-4 py-3">{sideBadge}</td>

        {(traderClass === "experienced" || traderClass === "semi_institutional") && (
          <td className="px-4 py-3 text-right text-sm text-dark-200 tabular-nums">
            {p.quantity}
          </td>
        )}

        <td className="px-4 py-3 text-right text-sm text-dark-200 tabular-nums">
          {formatPrice(p.entry_price, p.symbol)}
        </td>

        <td className="px-4 py-3 text-right text-sm font-semibold tabular-nums">
          <span className={live.isConnected ? "text-white" : "text-dark-400"}>
            {formatPrice(current, p.symbol)}
          </span>
        </td>

        <td className={clsx("px-4 py-3 text-right", good ? "text-green-300" : "text-red-300")}>
          {traderClass === "complete_novice" ? (
            <PnlHelp value={pnlText} />
          ) : (
            <span className="text-sm font-bold tabular-nums">{pnlText}</span>
          )}
        </td>

        {(traderClass === "curious_saver" ||
          traderClass === "self_taught" ||
          traderClass === "experienced" ||
          traderClass === "semi_institutional" ||
          traderClass === "crypto_native") && (
          <td
            className={clsx(
              "px-4 py-3 text-right text-sm font-semibold tabular-nums",
              good ? "text-green-300" : "text-red-300",
            )}
          >
            {pnlPct >= 0 ? "+" : ""}
            {pnlPct.toFixed(2)}%
          </td>
        )}

        {(traderClass === "curious_saver" || traderClass === "self_taught") && (
          <td className="px-4 py-3 text-sm text-dark-300">{toHoldTime(p.created_at)}</td>
        )}

        {(traderClass === "curious_saver" || traderClass === "self_taught") && (
          <td className="px-4 py-3">
            {sparkPoints && sparkPoints.length >= 2 ? (
              <Sparkline points={sparkPoints} />
            ) : (
              <span className="text-xs text-dark-500">—</span>
            )}
          </td>
        )}

        {(traderClass === "experienced" || traderClass === "semi_institutional") && (
          <>
            <td className="px-4 py-3 text-right text-sm text-dark-200 tabular-nums">
              {Number.isFinite(slDistPct) ? `${slDistPct.toFixed(2)}%` : "—"}
            </td>
            <td className="px-4 py-3 text-right text-sm text-dark-200 tabular-nums">
              {Number.isFinite(tpDistPct) ? `${tpDistPct.toFixed(2)}%` : "—"}
            </td>
            <td className="px-4 py-3">
              <button
                type="button"
                onClick={() => setEditOpen((v) => !v)}
                className="rounded-lg border border-dark-800 bg-dark-950 px-3 py-2 text-xs font-semibold text-dark-200 hover:text-white"
              >
                Modify SL/TP
              </button>
            </td>
          </>
        )}

        {traderClass === "semi_institutional" && (
          <>
            <td className="px-4 py-3 text-sm text-dark-300">{p.sector ?? "—"}</td>
            <td className="px-4 py-3 text-right text-sm text-dark-200 tabular-nums">
              {p.beta === null || p.beta === undefined ? "—" : p.beta.toFixed(2)}
            </td>
          </>
        )}

        {traderClass === "crypto_native" && (
          <>
            <td className="px-4 py-3 text-right text-sm text-dark-200 tabular-nums">
              {live.changePct === null
                ? "—"
                : `${live.changePct >= 0 ? "+" : ""}${live.changePct.toFixed(2)}%`}
            </td>
            <td className="px-4 py-3">
              <button
                type="button"
                onClick={async () => {
                  const target = current * 1.02;
                  try {
                    await api.post("/api/notifications/price-alert", {
                      symbol: p.symbol,
                      target_price: target,
                      direction: "above",
                    });
                  } catch {
                    // ignore
                  }
                }}
                className="rounded-lg border border-dark-800 bg-dark-950 px-3 py-2 text-xs font-semibold text-dark-200 hover:text-white"
              >
                Set price alert
              </button>
            </td>
          </>
        )}

        {traderClass === "complete_novice" && (
          <td className="px-4 py-3 text-sm text-dark-300">
            <span className="inline-flex rounded-lg border border-dark-800 bg-dark-950 px-2 py-1 text-xs text-dark-300">
              Open
            </span>
          </td>
        )}

        <td className="px-4 py-3 text-right">
          <button type="button" onClick={onClose} className="btn-outline text-xs">
            Close position
          </button>
        </td>
      </tr>

      {(traderClass === "experienced" || traderClass === "semi_institutional") && editOpen && (
        <tr className="bg-dark-950">
          <td className="px-4 py-3" colSpan={bulk ? 12 : 11}>
            <div className="flex flex-wrap items-end gap-3 rounded-xl border border-dark-800 bg-dark-950 p-4">
              <div className="text-xs font-semibold text-white">Modify SL/TP</div>
              <div className="flex items-center gap-2">
                <label className="text-xs text-dark-400">New SL %</label>
                <input
                  value={slPct}
                  onChange={(e) => setSlPct(e.target.value)}
                  className="w-20 rounded-lg border border-dark-800 bg-dark-900 px-2 py-1 text-sm text-white"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs text-dark-400">New TP %</label>
                <input
                  value={tpPct}
                  onChange={(e) => setTpPct(e.target.value)}
                  className="w-20 rounded-lg border border-dark-800 bg-dark-900 px-2 py-1 text-sm text-white"
                />
              </div>
              <button
                type="button"
                disabled={saving}
                onClick={async () => {
                  setSaving(true);
                  try {
                    await api.patch(`/api/trading/positions/${p.id}`, {
                      stop_loss_pct: Number(slPct),
                      take_profit_pct: Number(tpPct),
                    });
                    setEditOpen(false);
                    await onPatched();
                  } catch {
                    // ignore
                  } finally {
                    setSaving(false);
                  }
                }}
                className="btn-primary text-xs"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                Save
              </button>
              <button type="button" onClick={() => setEditOpen(false)} className="btn-outline text-xs">
                Cancel
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

