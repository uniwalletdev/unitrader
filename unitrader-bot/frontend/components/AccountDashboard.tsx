"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Building2,
  Pause,
  Play,
  Plus,
  ShieldAlert,
  Wallet,
  X,
} from "lucide-react";

type Exchange = "Alpaca" | "Coinbase" | "Binance" | "Oanda";
type Mode = "paper" | "live";
type AccountStatus = "connected" | "disconnected" | "error";

type Trade = {
  id: string;
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
  exchange: Exchange;
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

const INITIAL_ACCOUNTS: Account[] = [
  {
    id: "alpaca-paper-1",
    exchange: "Alpaca",
    mode: "paper",
    status: "connected",
    balance: 11480,
    currency: "USD",
    apexActive: true,
    pnl: 1284,
    pnlPercent: 12.59,
    trades: [
      {
        id: "ap1-t1",
        asset: "AAPL",
        direction: "buy",
        amount: 25,
        price: 189.2,
        timestamp: "2026-03-20T14:22:00Z",
        reason: "RSI oversold + positive earnings momentum",
        outcome: "win",
        pnl: 212,
      },
      {
        id: "ap1-t2",
        asset: "TSLA",
        direction: "buy",
        amount: 8,
        price: 174.5,
        timestamp: "2026-03-20T16:01:00Z",
        reason: "Breakout above resistance with rising volume",
        outcome: "open",
        pnl: 0,
      },
      {
        id: "ap1-t3",
        asset: "MSFT",
        direction: "sell",
        amount: 10,
        price: 418.3,
        timestamp: "2026-03-19T09:35:00Z",
        reason: "Mean reversion signal after RSI divergence",
        outcome: "win",
        pnl: 164,
      },
      {
        id: "ap1-t4",
        asset: "NVDA",
        direction: "buy",
        amount: 5,
        price: 868.4,
        timestamp: "2026-03-18T13:08:00Z",
        reason: "Momentum continuation + analyst upgrades",
        outcome: "loss",
        pnl: -96,
      },
      {
        id: "ap1-t5",
        asset: "AMZN",
        direction: "buy",
        amount: 14,
        price: 181.0,
        timestamp: "2026-03-17T11:45:00Z",
        reason: "MACD bullish crossover + strong sentiment",
        outcome: "win",
        pnl: 138,
      },
    ],
  },
  {
    id: "alpaca-live-1",
    exchange: "Alpaca",
    mode: "live",
    status: "connected",
    balance: 23950,
    currency: "USD",
    apexActive: true,
    pnl: 316,
    pnlPercent: 1.34,
    trades: [
      {
        id: "al1-t1",
        asset: "AAPL",
        direction: "buy",
        amount: 40,
        price: 190.1,
        timestamp: "2026-03-20T10:33:00Z",
        reason: "Trend support retest + strong breadth",
        outcome: "open",
        pnl: 0,
      },
      {
        id: "al1-t2",
        asset: "GOOGL",
        direction: "sell",
        amount: 12,
        price: 152.9,
        timestamp: "2026-03-19T15:11:00Z",
        reason: "Overbought RSI with weakening momentum",
        outcome: "win",
        pnl: 204,
      },
      {
        id: "al1-t3",
        asset: "META",
        direction: "buy",
        amount: 9,
        price: 493.4,
        timestamp: "2026-03-18T12:58:00Z",
        reason: "Breakout failure risk controlled with tight stop",
        outcome: "loss",
        pnl: -121,
      },
    ],
  },
  {
    id: "coinbase-live-1",
    exchange: "Coinbase",
    mode: "live",
    status: "connected",
    balance: 17120,
    currency: "USD",
    apexActive: false,
    pnl: -842,
    pnlPercent: -4.69,
    trades: [
      {
        id: "cb1-t1",
        asset: "BTC/USD",
        direction: "buy",
        amount: 0.22,
        price: 68320,
        timestamp: "2026-03-20T07:20:00Z",
        reason: "On-chain inflow slowdown + support bounce",
        outcome: "open",
        pnl: 0,
      },
      {
        id: "cb1-t2",
        asset: "ETH/USD",
        direction: "buy",
        amount: 3.4,
        price: 3685,
        timestamp: "2026-03-18T21:44:00Z",
        reason: "Funding normalized + positive sentiment reversal",
        outcome: "loss",
        pnl: -842,
      },
    ],
  },
  {
    id: "oanda-practice-1",
    exchange: "Oanda",
    mode: "paper",
    oandaSubtype: "Practice",
    status: "connected",
    balance: 9320,
    currency: "GBP",
    apexActive: true,
    pnl: 286,
    pnlPercent: 3.16,
    trades: [
      {
        id: "oa1-t1",
        asset: "EUR/USD",
        direction: "buy",
        amount: 25000,
        price: 1.0832,
        timestamp: "2026-03-20T06:40:00Z",
        reason: "DXY weakness + bullish macro sentiment",
        outcome: "win",
        pnl: 122,
      },
      {
        id: "oa1-t2",
        asset: "GBP/JPY",
        direction: "sell",
        amount: 12000,
        price: 196.43,
        timestamp: "2026-03-19T08:12:00Z",
        reason: "Bearish divergence + risk-off flow",
        outcome: "win",
        pnl: 98,
      },
      {
        id: "oa1-t3",
        asset: "XAU/USD",
        direction: "buy",
        amount: 7,
        price: 2191.4,
        timestamp: "2026-03-18T10:08:00Z",
        reason: "Safe-haven bid + breakout continuation",
        outcome: "open",
        pnl: 0,
      },
      {
        id: "oa1-t4",
        asset: "USD/CAD",
        direction: "buy",
        amount: 18000,
        price: 1.3571,
        timestamp: "2026-03-17T14:52:00Z",
        reason: "Rate differential widening signal",
        outcome: "loss",
        pnl: -46,
      },
    ],
  },
];

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
  return "from-emerald-500/20 to-teal-500/10";
}

export default function AccountDashboard() {
  const [accounts, setAccounts] = useState<Account[]>(INITIAL_ACCOUNTS);
  const [selectedAccountId, setSelectedAccountId] = useState<string>(INITIAL_ACCOUNTS[0].id);
  const [showAddModal, setShowAddModal] = useState(false);
  const [liveSwitchTargetId, setLiveSwitchTargetId] = useState<string | null>(null);
  const [confirmLiveText, setConfirmLiveText] = useState("");

  const selectedAccount =
    accounts.find((account) => account.id === selectedAccountId) ?? accounts[0] ?? null;

  const summary = useMemo(() => {
    const liveAccounts = accounts.filter((a) => a.mode === "live");
    const paperAccounts = accounts.filter((a) => a.mode === "paper");

    const toUsd = (value: number, currency: string) => value * (fxToUsd[currency] ?? 1);

    const totalLiveUsd = liveAccounts.reduce(
      (sum, account) => sum + toUsd(account.balance, account.currency),
      0
    );
    const totalPaperUsd = paperAccounts.reduce(
      (sum, account) => sum + toUsd(account.balance, account.currency),
      0
    );
    const totalLivePnlUsd = liveAccounts.reduce(
      (sum, account) => sum + toUsd(account.pnl, account.currency),
      0
    );

    return {
      totalLiveUsd,
      totalPaperUsd,
      totalLivePnlUsd,
      liveCount: liveAccounts.length,
      paperCount: paperAccounts.length,
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
      .filter((account) => account.mode === "live" && account.status === "connected")
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

  function toggleApex(accountId: string) {
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
          oandaSubtype: account.exchange === "Oanda" ? "Live" : account.oandaSubtype,
        };
      })
    );

    setLiveSwitchTargetId(null);
    setConfirmLiveText("");
  }

  if (!selectedAccount) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-950 p-6 text-slate-100">
        No accounts available.
      </div>
    );
  }

  const livePnlPositive = summary.totalLivePnlUsd >= 0;
  const selectedPnlPositive = selectedAccount.pnl >= 0;

  return (
    <div className="min-h-[820px] w-full rounded-2xl border border-slate-800 bg-slate-950 text-slate-100 shadow-2xl shadow-black/30">
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
                  Apex is holding {warning.label} across multiple live accounts - your total exposure is {warning.combinedAmount.toLocaleString()} units.
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
                const isPaperLike = account.mode === "paper";
                return (
                  <button
                    key={account.id}
                    type="button"
                    onClick={() => setSelectedAccountId(account.id)}
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
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${modeBadgeClass[account.mode]}`}>
                        {isPaperLike ? "Paper" : "Live"}
                      </span>
                    </div>

                    <div className="mt-3 flex items-center justify-between text-xs">
                      <span className="text-slate-400">{formatCurrency(account.balance, account.currency)}</span>
                      <span className="inline-flex items-center gap-1.5 text-slate-300">
                        <span className={`h-2 w-2 rounded-full ${statusDotClass[account.status]}`} />
                        {account.status}
                      </span>
                    </div>
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
                  <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${modeBadgeClass[selectedAccount.mode]}`}>
                    {selectedAccount.mode === "paper" ? "Paper" : "Live"}
                  </span>
                  {selectedAccount.mode === "live" && (
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

                {selectedAccount.mode === "paper" && (
                  <div className="mt-3 rounded-lg border border-amber-300/30 bg-amber-400/10 px-3 py-2 text-sm text-amber-200">
                    You&apos;re in Paper Trading mode - no real money at risk
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => toggleApex(selectedAccount.id)}
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 hover:border-slate-600"
                >
                  {selectedAccount.apexActive ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  {selectedAccount.apexActive ? "Pause Apex" : "Resume Apex"}
                </button>

                {selectedAccount.mode === "paper" && (
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
                label="Apex Status"
                value={selectedAccount.apexActive ? "Active" : "Paused"}
                tone={selectedAccount.apexActive ? "text-emerald-300" : "text-amber-300"}
                pulse={selectedAccount.apexActive}
              />
            </div>
          </div>

          <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-900/40 p-4 sm:p-5">
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-slate-400">
              Trade History
            </h3>

            <div className="overflow-x-auto">
              <table className="min-w-full border-separate border-spacing-y-2 text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-[0.14em] text-slate-500">
                    <th className="px-3 py-2">Asset</th>
                    <th className="px-3 py-2">Direction</th>
                    <th className="px-3 py-2">Amount</th>
                    <th className="px-3 py-2">Price</th>
                    <th className="px-3 py-2">Time</th>
                    <th className="px-3 py-2">Apex Reason</th>
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
                            {selectedAccount.mode === "paper" && (
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
              {(selectedAccount.exchange === "Coinbase" || selectedAccount.exchange === "Binance") &&
                "Crypto account: assets shown as crypto pairs (e.g. BTC/USD)."}
            </div>
          </div>
        </main>
      </div>

      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h4 className="text-lg font-semibold text-white">Add Account</h4>
              <button
                type="button"
                className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
                onClick={() => setShowAddModal(false)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="text-sm text-slate-300">
              Account onboarding modal stub. Wire this to your account connector flow (exchange selection, key validation, and mode setup).
            </p>
            <button
              type="button"
              onClick={() => setShowAddModal(false)}
              className="mt-4 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 hover:border-slate-600"
            >
              Close
            </button>
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
                    ? "You are about to switch from Oanda Practice to Oanda Live. Apex will trade with real funds from your Oanda Live account."
                    : "You are about to enable real-money trading for this account. Apex will execute using live funds."}
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
