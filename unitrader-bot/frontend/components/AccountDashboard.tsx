"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/router";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Building2,
  Loader2,
  Pause,
  Play,
  Plus,
  ShieldAlert,
  Wallet,
  X,
} from "lucide-react";
import {
  exchangeApi,
  tradingAPI,
  authApi,
  type AccountBalance,
  type BackendTrade,
  type PerformanceData,
} from "../lib/api";
import { devLogError } from "../lib/devLog";
import ExchangeConnections from "@/components/ExchangeConnections";

type Exchange = "Alpaca" | "Coinbase" | "Binance" | "Kraken" | "Oanda";
type Mode = "paper" | "live";
type AccountStatus = "connected" | "disconnected" | "error";

type Trade = {
  id: string;
  trading_account_id?: string | null;
  exchange?: string | null;
  is_paper?: boolean | null;
  asset: string;
  direction: "buy" | "sell";
  amount: number;
  price: number;
  timestamp: string;
  reason: string;
  outcome?: "win" | "loss" | "open";
  pnl?: number;
};

type Account = {
  id: string;
  tradingAccountId?: string | null;
  accountLabel?: string | null;
  exchange: Exchange;
  /** Raw exchange id from API (e.g. alpaca, coinbase) — used for badge and capital aggregation. */
  rawExchange: string;
  /** Value from API; Coinbase is always shown as live regardless. */
  isPaperFromApi: boolean;
  mode: Mode;
  status: AccountStatus;
  balance: number;
  currency: string;
  apexActive: boolean;
  pnl: number;
  pnlPercent: number;
  trades: Trade[];
  oandaSubtype?: "Practice" | "Live";
};

/** Badge display only — Coinbase is always live; paper only when API says paper (e.g. Alpaca paper). */
type TradingAccountBadgeInput = { exchange: string; is_paper: boolean };

function getAccountBadge(account: TradingAccountBadgeInput) {
  if (account.exchange.toLowerCase() === "coinbase") {
    return { label: "Live" as const, color: "green" as const };
  }
  if (account.is_paper) {
    return { label: "Paper" as const, color: "amber" as const };
  }
  return { label: "Live" as const, color: "green" as const };
}

/** Dashboard capital totals: live = Coinbase or any account with is_paper false. */
function countsTowardLiveCapital(account: Account): boolean {
  if (account.rawExchange.toLowerCase() === "coinbase") return true;
  return !account.isPaperFromApi;
}

/** Paper summary total: Alpaca paper only. */
function countsTowardPaperValue(account: Account): boolean {
  return account.rawExchange.toLowerCase() === "alpaca" && account.isPaperFromApi;
}

function isDisplayPaper(account: Account): boolean {
  return getAccountBadge({ exchange: account.rawExchange, is_paper: account.isPaperFromApi }).label === "Paper";
}

function mapExchangeName(raw: string): Exchange {
  const m: Record<string, Exchange> = {
    alpaca: "Alpaca",
    coinbase: "Coinbase",
    binance: "Binance",
    kraken: "Kraken",
    oanda: "Oanda",
  };
  return m[raw.toLowerCase()] ?? ("Alpaca" as Exchange);
}

function backendTradeToTrade(t: BackendTrade): Trade {
  const pnl = (t.profit ?? 0) - (t.loss ?? 0);
  let outcome: "win" | "loss" | "open" = "open";
  if (t.status === "closed") outcome = pnl >= 0 ? "win" : "loss";
  return {
    id: t.id,
    trading_account_id: t.trading_account_id,
    exchange: t.exchange,
    is_paper: t.is_paper,
    asset: t.symbol,
    direction: t.side?.toLowerCase() === "sell" ? "sell" : "buy",
    amount: t.quantity,
    price: t.entry_price,
    timestamp: t.created_at ?? new Date().toISOString(),
    reason: t.market_condition ?? "",
    outcome,
    pnl: t.status === "closed" ? pnl : 0,
  };
}

const fxToUsd: Record<string, number> = {
  USD: 1,
  GBP: 1.28,
  EUR: 1.09,
  JPY: 0.0067,
};

const statusDotClass: Record<AccountStatus, string> = {
  connected: "bg-emerald-400",
  disconnected: "bg-red-500",
  error: "bg-orange-400",
};

const modeBadgeClass: Record<Mode, string> = {
  paper: "bg-amber-400/15 text-amber-300 border border-amber-300/30",
  live: "bg-emerald-400/15 text-emerald-300 border border-emerald-300/30",
};

function formatCurrency(value: number, currency: string) {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPnl(value: number, currency: string) {
  const abs = Math.abs(value);
  const text = formatCurrency(abs, currency);
  return value >= 0 ? `+${text}` : `-${text}`;
}

function normalizeAssetKey(asset: string) {
  return asset
    .toUpperCase()
    .replace(/\s*\(CFD\)\s*/g, "")
    .replace(/\s*CFD\s*/g, "")
    .replace(/\s+/g, "")
    .replace(/-/g, "/");
}

function exchangeTone(exchange: Exchange) {
  if (exchange === "Alpaca") return "from-sky-500/20 to-blue-500/10";
  if (exchange === "Coinbase") return "from-indigo-500/20 to-cyan-500/10";
  if (exchange === "Binance") return "from-amber-500/20 to-yellow-500/10";
  if (exchange === "Kraken") return "from-violet-500/20 to-purple-500/10";
  return "from-emerald-500/20 to-teal-500/10";
}

export default function AccountDashboard() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>("");
  const [preferredTradingAccountId, setPreferredTradingAccountId] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [liveSwitchTargetId, setLiveSwitchTargetId] = useState<string | null>(null);
  const [confirmLiveText, setConfirmLiveText] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAccounts = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [balancesRes, positionsRes, historyRes] = await Promise.all([
        exchangeApi.balances(),
        tradingAPI.getOpenPositions(),
        tradingAPI.getTradeHistory({ limit: 100 }),
      ]);

      const balances: AccountBalance[] = balancesRes.data?.data ?? [];
      const openPositions: BackendTrade[] = positionsRes.data?.data?.positions ?? [];
      const closedTrades: BackendTrade[] = historyRes.data?.data?.trades ?? [];

      const allTrades = [...openPositions, ...closedTrades].map(backendTradeToTrade);
      const perfResults = await Promise.all(
        balances.map(async (b) => {
          const perfRes = await tradingAPI.getPerformance({
            trading_account_id: b.trading_account_id ?? undefined,
            exchange: b.exchange,
            is_paper: b.is_paper,
          });
          return perfRes.data?.data ?? {};
        }),
      );

      const mapped: Account[] = balances.map((b, index) => {
        const rawExchange = b.exchange ?? "";
        const isPaperFromApi = !!b.is_paper;
        const exchange = mapExchangeName(b.exchange);
        const mode: Mode = isPaperFromApi ? "paper" : "live";
        const id = b.trading_account_id ?? `${b.exchange}-${mode}`;
        const currency = b.currency || "USD";
        const balance = b.balance ?? 0;
        const perf: PerformanceData = perfResults[index] ?? {};
        const accountTrades = allTrades.filter((trade) => {
          if (b.trading_account_id && trade.trading_account_id) {
            return trade.trading_account_id === b.trading_account_id;
          }
          return trade.exchange === b.exchange && trade.is_paper === isPaperFromApi;
        });
        const accountPnl = perf.net_pnl_usd ?? 0;
        const accountPnlPct = balance > 0 ? (accountPnl / balance) * 100 : 0;

        return {
          id,
          tradingAccountId: b.trading_account_id,
          accountLabel: b.account_label,
          exchange,
          rawExchange,
          isPaperFromApi,
          mode,
          status: b.error ? "error" as AccountStatus : "connected" as AccountStatus,
          balance,
          currency,
          apexActive: true,
          pnl: Math.round(accountPnl * 100) / 100,
          pnlPercent: Math.round(accountPnlPct * 100) / 100,
          trades: accountTrades,
          ...(exchange === "Oanda" && { oandaSubtype: mode === "paper" ? "Practice" as const : "Live" as const }),
        };
      });

      setAccounts(mapped);
      setSelectedAccountId((prev) => {
        if (mapped.length > 0 && !mapped.find((a) => a.id === prev)) {
          return mapped[0].id;
        }
        return prev;
      });
    } catch (err) {
      devLogError("Failed to fetch account data", err);
      setError("Failed to load account data. Please check your connection.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAccounts();
  }, [fetchAccounts]);

  // Load preferred trading account so dashboard selection persists across sessions
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await authApi.getSettings();
        const id = (res.data?.preferred_trading_account_id as string | null | undefined) ?? null;
        if (!mounted) return;
        setPreferredTradingAccountId(id);
      } catch {
        // ignore
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const selectedAccount =
    accounts.find((account) => account.id === selectedAccountId) ??
    (preferredTradingAccountId
      ? accounts.find((a) => a.tradingAccountId === preferredTradingAccountId) ?? null
      : null) ??
    accounts[0] ??
    null;

  // If we have a preferred trading account, align selectedAccountId to it
  useEffect(() => {
    if (!preferredTradingAccountId) return;
    if (!accounts.length) return;
    const match = accounts.find((a) => a.tradingAccountId === preferredTradingAccountId);
    if (match && match.id !== selectedAccountId) setSelectedAccountId(match.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preferredTradingAccountId, accounts.length]);

  const summary = useMemo(() => {
    const liveCapitalAccounts = accounts.filter(countsTowardLiveCapital);
    const paperValueAccounts = accounts.filter(countsTowardPaperValue);

    const toUsd = (value: number, currency: string) => value * (fxToUsd[currency] ?? 1);

    const totalLiveUsd = liveCapitalAccounts.reduce(
      (sum, account) => sum + toUsd(account.balance, account.currency),
      0
    );
    const totalPaperUsd = paperValueAccounts.reduce(
      (sum, account) => sum + toUsd(account.balance, account.currency),
      0
    );
    const totalLivePnlUsd = liveCapitalAccounts.reduce(
      (sum, account) => sum + toUsd(account.pnl, account.currency),
      0
    );

    return {
      totalLiveUsd,
      totalPaperUsd,
      totalLivePnlUsd,
      liveCount: liveCapitalAccounts.length,
      paperCount: paperValueAccounts.length,
    };
  }, [accounts]);

  const overlapWarnings = useMemo(() => {
    const exposureMap = new Map<
      string,
      {
        label: string;
        accountIds: Set<string>;
        combinedAmount: number;
      }
    >();

    accounts
      .filter((account) => countsTowardLiveCapital(account) && account.status === "connected")
      .forEach((account) => {
        account.trades
          .filter((trade) => trade.outcome === "open")
          .forEach((trade) => {
            const key = normalizeAssetKey(trade.asset);
            const current = exposureMap.get(key) ?? {
              label: trade.asset.toUpperCase(),
              accountIds: new Set<string>(),
              combinedAmount: 0,
            };
            current.accountIds.add(account.id);
            current.combinedAmount += Math.abs(trade.amount);
            exposureMap.set(key, current);
          });
      });

    return Array.from(exposureMap.entries())
      .filter(([, row]) => row.accountIds.size >= 2)
      .map(([key, row]) => ({
        key,
        label: row.label,
        combinedAmount: row.combinedAmount,
      }));
  }, [accounts]);

  const targetAccount =
    liveSwitchTargetId == null
      ? null
      : accounts.find((account) => account.id === liveSwitchTargetId) ?? null;

  function toggleUnitrader(accountId: string) {
    setAccounts((prev) =>
      prev.map((account) =>
        account.id === accountId ? { ...account, apexActive: !account.apexActive } : account
      )
    );
  }

  function openGoLiveModal(accountId: string) {
    setLiveSwitchTargetId(accountId);
    setConfirmLiveText("");
  }

  function confirmGoLive() {
    if (!targetAccount || confirmLiveText !== "GO LIVE") return;

    setAccounts((prev) =>
      prev.map((account) => {
        if (account.id !== targetAccount.id) return account;
        return {
          ...account,
          mode: "live",
          isPaperFromApi: false,
          oandaSubtype: account.exchange === "Oanda" ? "Live" : account.oandaSubtype,
        };
      })
    );

    setLiveSwitchTargetId(null);
    setConfirmLiveText("");
  }

  if (loading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center rounded-2xl border border-slate-800 bg-slate-950 p-6 text-slate-100">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-sky-400" />
        Loading accounts...
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-950 p-6 text-slate-100">
        <p className="text-rose-300">{error}</p>
        <button
          type="button"
          onClick={fetchAccounts}
          className="mt-3 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 hover:border-slate-600"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!selectedAccount) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-950 p-6 text-slate-100">
        <p>No connected exchange accounts found.</p>
        <p className="mt-1 text-sm text-slate-400">Connect an exchange in Settings to get started.</p>
      </div>
    );
  }

  const livePnlPositive = summary.totalLivePnlUsd >= 0;
  const selectedPnlPositive = selectedAccount.pnl >= 0;
  const selectedBadge = getAccountBadge({
    exchange: selectedAccount.rawExchange,
    is_paper: selectedAccount.isPaperFromApi,
  });

  return (
    <div className="w-full rounded-2xl border border-slate-800 bg-slate-950 text-slate-100 shadow-2xl shadow-black/30">
      <div className="border-b border-slate-800 bg-gradient-to-r from-slate-900 to-slate-950 p-4 sm:p-6">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard
            label="~ Total Live Capital"
            value={formatCurrency(summary.totalLiveUsd, "USD")}
            subText="Approx. real-money deployed"
            tone="text-emerald-300"
          />
          <SummaryCard
            label="~ Total Paper Value"
            value={formatCurrency(summary.totalPaperUsd, "USD")}
            subText="Approx. simulation balance"
            tone="text-amber-300"
          />
          <SummaryCard
            label="~ Live P&L"
            value={`${summary.totalLivePnlUsd >= 0 ? "+" : "-"}${formatCurrency(
              Math.abs(summary.totalLivePnlUsd),
              "USD"
            )}`}
            subText="Across all live accounts"
            tone={livePnlPositive ? "text-emerald-300" : "text-rose-300"}
          />
          <SummaryCard
            label="Accounts"
            value={`${summary.liveCount} Live / ${summary.paperCount} Paper`}
            subText="Modes are tracked separately"
            tone="text-sky-300"
          />
        </div>
      </div>

      {overlapWarnings.length > 0 && (
        <div className="mx-4 mt-4 rounded-xl border border-orange-400/30 bg-orange-400/10 p-3 sm:mx-6">
          <div className="flex items-start gap-2 text-sm text-orange-200">
            <ShieldAlert className="mt-0.5 h-4 w-4 flex-none" />
            <div className="space-y-1">
              {overlapWarnings.map((warning) => (
                <p key={warning.key}>
                  Unitrader is holding {warning.label} across multiple live accounts - your total exposure is {warning.combinedAmount.toLocaleString()} units.
                </p>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-col xl:flex-row">
        <aside className="w-full border-b border-slate-800 bg-slate-900/60 xl:w-80 xl:border-b-0 xl:border-r">
          <div className="p-4 sm:p-5">
            <h2 className="mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
              Connected Accounts
            </h2>

            <div className="space-y-2">
              {accounts.map((account) => {
                const active = account.id === selectedAccount.id;
                const badge = getAccountBadge({
                  exchange: account.rawExchange,
                  is_paper: account.isPaperFromApi,
                });
                return (
                  <button
                    key={account.id}
                    type="button"
                    onClick={async () => {
                      setSelectedAccountId(account.id);
                      if (!account.tradingAccountId) return;
                      setPreferredTradingAccountId(account.tradingAccountId);
                      try {
                        await authApi.updateSettings({ preferred_trading_account_id: account.tradingAccountId });
                      } catch {
                        // non-fatal: keep local selection, backend will remain unchanged
                      }
                    }}
                    className={`w-full rounded-xl border p-3 text-left transition ${
                      active
                        ? "border-sky-400/60 bg-slate-800"
                        : "border-slate-800 bg-slate-900 hover:border-slate-700"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <div
                          className={`flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br ${exchangeTone(
                            account.exchange
                          )}`}
                        >
                          <Building2 className="h-4 w-4 text-slate-100" />
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold text-slate-100">
                            {account.exchange}
                          </div>
                          {account.exchange === "Oanda" && (
                            <div className="text-xs text-slate-400">
                              {account.oandaSubtype ?? (account.mode === "paper" ? "Practice" : "Live")} Account
                            </div>
                          )}
                        </div>
                      </div>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          badge.color === "amber" ? modeBadgeClass.paper : modeBadgeClass.live
                        }`}
                      >
                        {badge.label}
                      </span>
                    </div>

                    <div className="mt-3 flex items-center justify-between text-xs">
                      <span className="text-slate-400">{formatCurrency(account.balance, account.currency)}</span>
                      <span className="inline-flex items-center gap-1.5 text-slate-300">
                        <span className={`h-2 w-2 rounded-full ${statusDotClass[account.status]}`} />
                        {account.status}
                      </span>
                    </div>
                    {(account.exchange === "Coinbase" || account.exchange === "Kraken") && (
                      <p className="mt-2 text-left text-[10px] leading-snug text-slate-500">
                        Real balance — your own {account.exchange} account
                      </p>
                    )}
                  </button>
                );
              })}
            </div>

            <button
              type="button"
              onClick={() => setShowAddModal(true)}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 transition hover:border-slate-500 hover:text-white"
            >
              <Plus className="h-4 w-4" />
              Add Account
            </button>
          </div>
        </aside>

        <main className="min-w-0 flex-1 p-4 sm:p-6">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-semibold text-white">{selectedAccount.exchange} Account</h1>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                      selectedBadge.color === "amber" ? modeBadgeClass.paper : modeBadgeClass.live
                    }`}
                  >
                    {selectedBadge.label}
                  </span>
                  {!isDisplayPaper(selectedAccount) &&
                    selectedAccount.exchange !== "Coinbase" &&
                    selectedAccount.exchange !== "Kraken" && (
                    <span className="rounded-full border border-emerald-300/30 bg-emerald-400/15 px-2.5 py-1 text-xs font-semibold text-emerald-300">
                      Live Trading - real funds
                    </span>
                  )}
                  {selectedAccount.exchange === "Oanda" && (
                    <span className="rounded-full border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs text-slate-300">
                      Base Currency: {selectedAccount.currency}
                    </span>
                  )}
                </div>

                {(selectedAccount.exchange === "Coinbase" || selectedAccount.exchange === "Kraken") && (
                  <p className="mt-2 text-sm text-slate-400">
                    Real balance — your own {selectedAccount.exchange} account
                  </p>
                )}

                {isDisplayPaper(selectedAccount) && (
                  <div className="mt-3 rounded-lg border border-amber-300/30 bg-amber-400/10 px-3 py-2 text-sm text-amber-200">
                    You&apos;re in Paper Trading mode - no real money at risk
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => toggleUnitrader(selectedAccount.id)}
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 hover:border-slate-600"
                >
                  {selectedAccount.apexActive ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  {selectedAccount.apexActive ? "Pause Unitrader" : "Resume Unitrader"}
                </button>

                {isDisplayPaper(selectedAccount) && (
                  <button
                    type="button"
                    onClick={() => openGoLiveModal(selectedAccount.id)}
                    className="rounded-lg border border-emerald-300/30 bg-emerald-400/15 px-3 py-2 text-sm font-semibold text-emerald-200 hover:bg-emerald-400/20"
                  >
                    {selectedAccount.exchange === "Oanda" ? "Switch to Live Account" : "Switch to Live"}
                  </button>
                )}
              </div>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <MetricCard
                icon={<Wallet className="h-4 w-4" />}
                label="Balance"
                value={formatCurrency(selectedAccount.balance, selectedAccount.currency)}
                tone="text-sky-300"
              />
              <MetricCard
                icon={<BarChart3 className="h-4 w-4" />}
                label="P&L"
                value={`${selectedPnlPositive ? "+" : "-"}${formatCurrency(
                  Math.abs(selectedAccount.pnl),
                  selectedAccount.currency
                )} (${selectedAccount.pnlPercent.toFixed(2)}%)`}
                tone={selectedPnlPositive ? "text-emerald-300" : "text-rose-300"}
              />
              <MetricCard
                icon={<Activity className="h-4 w-4" />}
                label="Unitrader Status"
                value={selectedAccount.apexActive ? "Active" : "Paused"}
                tone={selectedAccount.apexActive ? "text-emerald-300" : "text-amber-300"}
                pulse={selectedAccount.apexActive}
              />
            </div>
          </div>

          <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-900/40 p-3 sm:p-5">
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-400">
              Trade History
            </h3>

            <div className="table-container overflow-x-auto">
              <table className="min-w-[860px] border-separate border-spacing-y-2 text-sm md:min-w-full">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-[0.14em] text-slate-500">
                    <th className="px-3 py-2">Asset</th>
                    <th className="px-3 py-2">Direction</th>
                    <th className="px-3 py-2">Amount</th>
                    <th className="px-3 py-2">Price</th>
                    <th className="px-3 py-2">Time</th>
                    <th className="px-3 py-2">Unitrader Reason</th>
                    <th className="px-3 py-2">Outcome</th>
                    <th className="px-3 py-2">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedAccount.trades.map((trade) => {
                    const rowTone =
                      trade.outcome === "win"
                        ? "bg-emerald-500/10 border-emerald-400/20"
                        : trade.outcome === "loss"
                          ? "bg-rose-500/10 border-rose-400/20"
                          : "bg-slate-800/70 border-slate-700";
                    const directionTone =
                      trade.direction === "buy"
                        ? "text-emerald-300 border-emerald-400/30 bg-emerald-500/10"
                        : "text-rose-300 border-rose-400/30 bg-rose-500/10";

                    return (
                      <tr key={trade.id} className={`rounded-xl border ${rowTone}`}>
                        <td className="rounded-l-xl px-3 py-3">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-slate-100">{trade.asset}</span>
                            {isDisplayPaper(selectedAccount) && (
                              <span className="rounded border border-amber-300/40 bg-amber-400/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                                P
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold uppercase ${directionTone}`}>
                            {trade.direction}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-slate-200">{trade.amount.toLocaleString()}</td>
                        <td className="px-3 py-3 text-slate-200">{formatCurrency(trade.price, selectedAccount.currency)}</td>
                        <td className="px-3 py-3 text-slate-300">
                          {new Date(trade.timestamp).toLocaleString("en-GB", {
                            day: "2-digit",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </td>
                        <td className="max-w-[360px] px-3 py-3 text-slate-300">{trade.reason}</td>
                        <td className="px-3 py-3">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                              trade.outcome === "win"
                                ? "bg-emerald-500/15 text-emerald-300"
                                : trade.outcome === "loss"
                                  ? "bg-rose-500/15 text-rose-300"
                                  : "bg-slate-700 text-slate-200"
                            }`}
                          >
                            {trade.outcome ?? "open"}
                          </span>
                        </td>
                        <td className="rounded-r-xl px-3 py-3 font-semibold">
                          <span
                            className={
                              (trade.pnl ?? 0) > 0
                                ? "text-emerald-300"
                                : (trade.pnl ?? 0) < 0
                                  ? "text-rose-300"
                                  : "text-slate-300"
                            }
                          >
                            {trade.pnl == null
                              ? "-"
                              : trade.pnl === 0
                                ? "0"
                                : formatPnl(trade.pnl, selectedAccount.currency)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="mt-3 text-xs text-slate-500">
              {selectedAccount.exchange === "Oanda" &&
                "Oanda account: forex and CFD instruments are shown with FX pair formatting when applicable."}
              {selectedAccount.exchange === "Alpaca" &&
                "Alpaca account: stock tickers shown in standard symbol format."}
              {(selectedAccount.exchange === "Coinbase" ||
                selectedAccount.exchange === "Binance" ||
                selectedAccount.exchange === "Kraken") &&
                "Crypto account: assets shown as crypto pairs (e.g. BTC/USD)."}
            </div>
          </div>
        </main>
      </div>

      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
            <div className="flex shrink-0 items-center justify-between border-b border-slate-800 px-5 py-4">
              <div>
                <h4 className="text-lg font-semibold text-white">Add Account</h4>
                <p className="mt-0.5 text-xs text-slate-400">
                  Connect another exchange or add a paper account. Keys are encrypted and never shown again after save.
                </p>
              </div>
              <button
                type="button"
                className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
                onClick={() => setShowAddModal(false)}
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              <ExchangeConnections
                onConnected={() => {
                  setShowAddModal(false);
                  void fetchAccounts();
                }}
              />
            </div>
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-slate-800 px-5 py-3">
              <button
                type="button"
                onClick={() => {
                  setShowAddModal(false);
                  void router.push("/connect-exchange");
                }}
                className="text-xs text-sky-400 hover:text-sky-300"
              >
                Open full connect page
              </button>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 hover:border-slate-600"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {targetAccount && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-emerald-300/30 bg-slate-900 p-6 shadow-2xl">
            <div className="mb-3 flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-emerald-300" />
              <div>
                <h4 className="text-lg font-semibold text-white">
                  {targetAccount.exchange === "Oanda" ? "Switch to Oanda Live Account" : "Switch to Live Trading"}
                </h4>
                <p className="mt-1 text-sm text-slate-300">
                  {targetAccount.exchange === "Oanda"
                    ? "You are about to switch from Oanda Practice to Oanda Live. Unitrader will trade with real funds from your Oanda Live account."
                    : "You are about to enable real-money trading for this account. Unitrader will execute using live funds."}
                </p>
              </div>
            </div>

            <div className="mt-4 rounded-lg border border-slate-700 bg-slate-800/60 p-3 text-sm text-slate-300">
              Type <span className="font-semibold text-white">GO LIVE</span> to confirm.
            </div>

            <input
              value={confirmLiveText}
              onChange={(event) => setConfirmLiveText(event.target.value)}
              placeholder="GO LIVE"
              className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none ring-sky-400 placeholder:text-slate-500 focus:ring-2"
            />

            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setLiveSwitchTargetId(null);
                  setConfirmLiveText("");
                }}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:border-slate-600"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={confirmLiveText !== "GO LIVE"}
                onClick={confirmGoLive}
                className="rounded-lg border border-emerald-300/30 bg-emerald-500/20 px-3 py-2 text-sm font-semibold text-emerald-200 disabled:cursor-not-allowed disabled:opacity-45"
              >
                Confirm Live Mode
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  subText,
  tone,
}: {
  label: string;
  value: string;
  subText: string;
  tone: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
      <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${tone}`}>{value}</div>
      <div className="text-xs text-slate-500">{subText}</div>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  tone,
  pulse = false,
}: {
  icon: JSX.Element;
  label: string;
  value: string;
  tone: string;
  pulse?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-slate-500">
        <span className={pulse ? "relative" : ""}>
          {icon}
          {pulse && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 animate-ping rounded-full bg-emerald-400" />}
        </span>
        {label}
      </div>
      <div className={`mt-1.5 text-base font-semibold ${tone}`}>{value}</div>
    </div>
  );
}
