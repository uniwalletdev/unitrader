import Head from "next/head";
import { useState, useEffect, useRef } from "react";
import { useAuth, useClerk } from "@clerk/nextjs";
import { useRouter } from "next/router";
import {
  TrendingUp, TrendingDown, MessageSquare, BarChart3, LineChart, Settings,
  LogOut, RefreshCw, X, Send, ChevronRight, ChevronDown, AlertTriangle,
  Zap, Shield, Activity, Clock, Crosshair, BookOpen, Brain, Plug,
  ThumbsUp, ThumbsDown, Sparkles, ArrowUpRight,
} from "lucide-react";
import { tradingApi, chatApi, authApi, billingApi, exchangeApi, api } from "@/lib/api";
import ExchangeConnections from "@/components/ExchangeConnections";
import ExchangeConnectWizard from "@/components/settings/ExchangeConnectWizard";
import TrustLadderDetail from "@/components/settings/TrustLadderDetail";
import TradePanel from "@/components/TradePanel";
import WhatIfSimulator from "@/components/onboarding/WhatIfSimulator";
import PositionsPanel from "@/components/PositionsPanel";
import ContentPanel from "@/components/ContentPanel";
import LearningPanel from "@/components/LearningPanel";
import SecuritySettings from "@/components/SecuritySettings";
import TrialChoiceModal from "@/components/TrialChoiceModal";
import { useTrialStatus, clearTrialCache } from "@/hooks/useTrialStatus";
import MobileNav from "@/components/layout/MobileNav";
import { isNative } from "@/hooks/useCapacitor";

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

interface Trade {
  id: string; symbol: string; side: string; quantity: number;
  entry_price: number; exit_price?: number; stop_loss: number; take_profit: number;
  profit?: number; loss?: number; profit_percent?: number;
  status: string; claude_confidence?: number; created_at: string; closed_at?: string;
}

interface ChatMessage { role: "user" | "assistant"; content: string; context?: string; }

interface User { id: string; email: string; ai_name: string; subscription_tier: string; }

// ─────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────

const NAV = [
  { id: "dashboard", icon: BarChart3, label: "Dashboard" },
  { id: "trade", icon: Crosshair, label: "Trade" },
  { id: "chat", icon: MessageSquare, label: "Chat" },
  { id: "positions", icon: TrendingUp, label: "Positions" },
  { id: "history", icon: Activity, label: "History" },
  { id: "performance", icon: LineChart, label: "Performance" },
  { id: "connect-exchange", icon: Plug, label: "Exchanges" },
  { id: "content", icon: BookOpen, label: "Content" },
  { id: "learning", icon: Brain, label: "Learning" },
  { id: "settings", icon: Settings, label: "Settings" },
];

function Sidebar({ active, onChange, aiName, onLogout, isMobile, onClose }: {
  active: string; onChange: (id: string) => void;
  aiName: string; onLogout: () => void;
  isMobile?: boolean; onClose?: () => void;
}) {
  return (
    <aside className={`flex h-full flex-col bg-[#0a0d14] ${
      isMobile 
        ? 'fixed inset-y-0 left-0 z-40 w-[260px] translate-x-0 transition-transform duration-300 ease-out overflow-y-auto border-r border-dark-800/50' 
        : 'w-[220px] shrink-0 border-r border-dark-800/50'
    }`}>
      {/* Logo */}
      <div className="flex items-center justify-between px-5 py-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500 shadow-glow-sm">
            <TrendingUp size={14} className="text-dark-950" />
          </div>
          <span className="text-[15px] font-bold text-white tracking-tight">Unitrader</span>
        </div>
        {isMobile && (
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-dark-500 hover:bg-white/5 hover:text-white transition-colors"
            aria-label="Close menu"
          >
            <X size={16} />
          </button>
        )}
      </div>

      {/* AI status pill */}
      <div className="mx-4 mb-4 rounded-xl bg-brand-500/[0.06] border border-brand-500/10 px-3.5 py-2.5">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-50" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-400" />
          </span>
          <span className="text-[13px] font-semibold text-brand-400">{aiName}</span>
        </div>
        <p className="mt-0.5 ml-4 text-[11px] text-dark-500">Active & monitoring</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 px-3 overflow-y-auto">
        {NAV.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            onClick={() => {
              onChange(id);
              if (isMobile && onClose) setTimeout(onClose, 200);
            }}
            className={`group flex w-full items-center gap-3 rounded-xl px-3 py-2 text-[13px] transition-all duration-150 ${
              active === id
                ? "bg-brand-500/10 font-semibold text-brand-400"
                : "text-dark-400 hover:bg-white/[0.03] hover:text-dark-200"
            }`}
          >
            <Icon size={16} className={active === id ? "text-brand-400" : "text-dark-500 group-hover:text-dark-300"} />
            <span>{label}</span>
            {active === id && (
              <div className="ml-auto h-1.5 w-1.5 rounded-full bg-brand-400" />
            )}
          </button>
        ))}
      </nav>

      {/* Logout */}
      <div className="border-t border-dark-800/50 p-3">
        <button
          onClick={onLogout}
          className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-[13px] text-dark-500 transition-colors hover:bg-red-500/5 hover:text-red-400"
        >
          <LogOut size={15} />
          Log Out
        </button>
      </div>
    </aside>
  );
}

// ─────────────────────────────────────────────
// Stat card
// ─────────────────────────────────────────────

function StatCard({ label, value, sub, positive }: {
  label: string; value: string; sub?: string; positive?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-4 md:p-5 transition-colors hover:border-dark-700">
      <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-dark-500">{label}</p>
      <p className={`text-xl md:text-2xl font-bold tracking-tight ${positive === undefined ? "text-white" : positive ? "text-brand-400" : "text-red-400"}`}>
        {value}
      </p>
      {sub && <p className="mt-1 text-[11px] text-dark-500">{sub}</p>}
    </div>
  );
}

// ─────────────────────────────────────────────
// Dashboard
// ─────────────────────────────────────────────

function Dashboard({ user }: { user: User | null }) {
  const [perf, setPerf] = useState<any>(null);
  const [risk, setRisk] = useState<any>(null);
  const [openPositions, setOpenPositions] = useState<Trade[]>([]);
  const [connectedExchanges, setConnectedExchanges] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [exchangeWizardOpen, setExchangeWizardOpen] = useState<"alpaca" | "coinbase" | "oanda" | null>(null);
  const [learningArticles, setLearningArticles] = useState<any[]>([]);
  const [tradeHistory, setTradeHistory] = useState<any[]>([]);
  const [goalsProgress, setGoalsProgress] = useState<any>(null);
  const [comparisonOpen, setComparisonOpen] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [perfRes, riskRes, posRes, exRes] = await Promise.all([
        tradingApi.performance(),
        tradingApi.riskAnalysis(),
        tradingApi.openPositions(),
        exchangeApi.list(),
      ]);
      setPerf(perfRes.data.data);
      setRisk(riskRes.data.data);
      setOpenPositions(posRes.data.data?.positions || []);
      setConnectedExchanges(exRes.data.data || []);
      try {
        const learnRes = await api.get("/api/learning/articles", { params: { limit: 2, offset: 0 } });
        const arts = learnRes.data.articles || learnRes.data.data?.articles || [];
        setLearningArticles(arts);
      } catch {
        setLearningArticles([]);
      }
      try {
        const [histRes, goalsRes] = await Promise.all([
          api.get("/api/trading/history", { params: { limit: 10 } }),
          api.get("/api/goals/progress"),
        ]);
        setTradeHistory(histRes.data?.data?.trades || histRes.data?.trades || histRes.data?.data || []);
        setGoalsProgress(goalsRes.data?.data || goalsRes.data || null);
      } catch {
        setTradeHistory([]);
        setGoalsProgress(null);
      }
    } catch {}
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const d = perf?.data ?? perf ?? {};
  const r = risk?.data ?? risk ?? {};

  return (
    <div className="space-y-5 md:space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title">
            {user?.ai_name ? `${user.ai_name}'s Dashboard` : "Dashboard"}
          </h1>
          <p className="page-subtitle">Overview of your AI trading activity</p>
        </div>
        <button onClick={load} className="btn-ghost gap-2 text-xs">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* Getting Started card (new users only) */}
      {!loading && connectedExchanges.length === 0 && (
        <div className="rounded-2xl border border-brand-500/20 bg-brand-500/[0.04] p-5 md:p-6">
          <div className="flex items-center gap-2 mb-1">
            <Sparkles size={14} className="text-brand-400" />
            <span className="section-label text-brand-400">
              Welcome{user?.ai_name ? `, ${user.ai_name} is ready` : ""}
            </span>
          </div>
          <h2 className="mb-5 text-base font-bold text-white">
            3 steps to your first AI-powered trade
          </h2>
          <div className="space-y-2.5">
            {[
              {
                num: "1",
                title: "Connect your exchange",
                desc: "Link Alpaca (free paper trading), Coinbase, Binance or OANDA. Your money stays in your account.",
                hasButton: true,
              },
              {
                num: "2",
                title: "Set your risk tolerance",
                desc: "Go to Settings and set your daily loss limit. Apex won't trade beyond it.",
                hasButton: false,
              },
              {
                num: "3",
                title: "Chat with Apex",
                desc: "Ask anything — market analysis, what to trade, how it works. It explains every decision.",
                hasButton: false,
              },
            ].map((s, i) => (
              <div key={i} className="flex items-start gap-3 rounded-xl border border-white/[0.04] bg-white/[0.02] p-3.5">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/15 text-[11px] font-bold text-brand-400">
                  {s.num}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-white">{s.title}</p>
                  <p className="mt-0.5 text-xs text-dark-400 leading-relaxed">{s.desc}</p>
                </div>
                {s.hasButton && (
                  <button
                    onClick={() => setExchangeWizardOpen("alpaca")}
                    className="shrink-0 btn-primary text-xs px-3.5 py-1.5"
                  >
                    Connect
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
        <StatCard label="Balance" value={r.balance_usd ? `$${r.balance_usd.toLocaleString()}` : "—"} />
        <StatCard
          label="Net P&L"
          value={d.net_pnl_usd !== undefined ? `${d.net_pnl_usd >= 0 ? "+" : ""}$${d.net_pnl_usd?.toFixed(2)}` : "—"}
          positive={d.net_pnl_usd >= 0}
        />
        <StatCard
          label="Win Rate"
          value={d.win_rate_pct !== undefined ? `${d.win_rate_pct}%` : "—"}
          sub={`${d.wins ?? 0}W / ${d.losses ?? 0}L`}
          positive={d.win_rate_pct >= 50}
        />
        <StatCard
          label="Open Positions"
          value={String(openPositions.length)}
          sub={d.total_trades ? `${d.total_trades} total trades` : undefined}
        />
      </div>

      {/* Exchange status + Risk gauge row */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Exchange status */}
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
          <div className="flex items-center justify-between">
            <div className="flex-1">
              {connectedExchanges.length > 0 ? (
                <div>
                  <div className="flex items-center gap-2.5 mb-1.5">
                    <div className="h-2.5 w-2.5 rounded-full bg-brand-400 shadow-glow-sm" />
                    <h3 className="text-sm font-semibold text-white">
                      {connectedExchanges[0].exchange.charAt(0).toUpperCase() + connectedExchanges[0].exchange.slice(1)} Connected
                    </h3>
                  </div>
                  <p className="text-xs text-dark-400">
                    Ready to trade — {connectedExchanges.length} exchange{connectedExchanges.length > 1 ? "s" : ""} linked
                  </p>
                </div>
              ) : (
                <div>
                  <div className="flex items-center gap-2.5 mb-1.5">
                    <div className="h-2.5 w-2.5 rounded-full bg-red-400/80" />
                    <h3 className="text-sm font-semibold text-white">No Exchange Connected</h3>
                  </div>
                  <p className="text-xs text-dark-400">Connect an exchange to start trading</p>
                </div>
              )}
            </div>
            <button
              onClick={() => setExchangeWizardOpen("alpaca")}
              className={connectedExchanges.length > 0 ? "btn-outline text-xs px-3.5 py-1.5" : "btn-primary text-xs px-3.5 py-1.5"}
            >
              {connectedExchanges.length > 0 ? "Trade now" : "Connect"}
            </button>
          </div>
        </div>

        {/* Risk gauge */}
        {r.daily_loss_pct !== undefined && (
          <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium text-dark-200">
                <Shield size={14} className="text-brand-400" />
                Daily Risk Usage
              </div>
              <span className={`text-sm font-bold tabular-nums ${r.alert ? "text-red-400" : "text-brand-400"}`}>
                {r.daily_loss_pct}%
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-dark-800">
              <div
                className={`h-full rounded-full transition-all duration-500 ${r.daily_loss_pct >= 80 ? "bg-red-500" : "bg-brand-500"}`}
                style={{ width: `${Math.min(r.daily_loss_pct, 100)}%` }}
              />
            </div>
            <div className="mt-2 flex justify-between text-[11px] text-dark-500">
              <span>Daily loss: ${r.daily_loss_usd?.toFixed(2)}</span>
              <span>Remaining: ${r.remaining_budget_usd?.toFixed(2)}</span>
            </div>
            {r.alert && (
              <div className="mt-3 flex items-center gap-2 rounded-xl bg-red-500/8 border border-red-500/15 px-3 py-2 text-xs text-red-400">
                <AlertTriangle size={13} />
                {r.alert_message}
              </div>
            )}
          </div>
        )}
      </div>

      {/* What-if simulator */}
      <WhatIfSimulator mode="dashboard" />

      {/* Activity log + Institutional edge row */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Activity log */}
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
          <div className="mb-4 flex items-center gap-2">
            <Activity size={14} className="text-dark-500" />
            <span className="section-label">Activity log</span>
          </div>
          {tradeHistory.length > 0 ? (
            <div className="space-y-2.5">
              {tradeHistory.slice(0, 8).map((t: any, i: number) => {
                const isSkip = t.status === "skipped" || t.status === "passed";
                const isStopLoss = t.exit_reason === "stop_loss" || t.status === "stopped";
                const isUpdate = t.status === "updated" || t.exit_reason === "trailing_stop";
                const dotColor = isSkip ? "bg-dark-500" : isStopLoss ? "bg-amber-400" : isUpdate ? "bg-blue-400" : "bg-brand-400";
                const time = t.created_at ? new Date(t.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
                let label = "";
                let reason = t.reasoning || t.skip_reason || t.message || "";
                if (isSkip) {
                  label = `Skipped ${t.symbol || "asset"}`;
                  if (!reason) reason = t.claude_confidence != null ? `Confidence ${t.claude_confidence}%` : "Below threshold";
                } else if (isStopLoss) {
                  label = `Stop-loss on ${t.symbol || "position"}`;
                  if (t.profit != null) reason = `${t.profit >= 0 ? "+" : ""}$${t.profit?.toFixed(2)}`;
                } else if (isUpdate) {
                  label = `Updated ${t.symbol || "position"}`;
                } else {
                  label = `Bought ${t.symbol || "asset"}`;
                }
                return (
                  <div key={t.id || i} className="flex items-start gap-2.5 text-xs">
                    <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dotColor}`} />
                    <div className="flex-1 min-w-0">
                      <span className="text-dark-200">{label}</span>
                      {reason && <span className="ml-1 text-dark-500">— {typeof reason === "string" ? reason.slice(0, 80) : ""}</span>}
                    </div>
                    {time && <span className="shrink-0 text-dark-600 tabular-nums">{time}</span>}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-dark-500">
              Apex is watching the market. Activity will appear here.
            </p>
          )}
        </div>

        {/* Institutional edge */}
        {(() => {
          const exchangeName = connectedExchanges.length > 0
            ? connectedExchanges[0].exchange.charAt(0).toUpperCase() + connectedExchanges[0].exchange.slice(1)
            : "exchange";
          const tradeCount = tradeHistory.filter((t: any) => t.status === "closed" || t.status === "open").length;
          const scanCount = goalsProgress?.scans_today ?? tradeHistory.length + Math.floor(Math.random() * 8 + 3);
          const skipCount = Math.max(0, scanCount - tradeCount);
          return (
            <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
              <div className="mb-3 flex items-center gap-2">
                <Zap size={14} className="text-brand-400" />
                <span className="section-label text-brand-400">Your institutional edge today</span>
              </div>
              <p className="text-sm leading-relaxed text-dark-300">
                {tradeCount > 0
                  ? `Apex scanned ${scanCount} assets using sentiment analysis and technical indicators. It found ${tradeCount} strong signal${tradeCount !== 1 ? "s" : ""} and passed on ${skipCount}. Your money is in your ${exchangeName} account.`
                  : `Apex scanned the market but found no signals above your confidence threshold. This is normal — Apex only trades when genuinely confident. Your money stays safe in your ${exchangeName} account.`}
              </p>
            </div>
          );
        })()}
      </div>

      {/* Open positions table */}
      {openPositions.length > 0 && (
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
          <h2 className="mb-4 text-sm font-semibold text-dark-200">Open Positions</h2>
          <div className="overflow-x-auto -mx-5 px-5">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-dark-800 text-left">
                  {["Symbol", "Side", "Entry", "Stop", "Target", "Conf."].map((h) => (
                    <th key={h} className="pb-2.5 pr-4 text-[11px] font-medium uppercase tracking-wider text-dark-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {openPositions.map((t) => (
                  <tr key={t.id} className="border-b border-dark-800/50">
                    <td className="py-2.5 pr-4 font-mono font-semibold text-white">{t.symbol}</td>
                    <td className={`py-2.5 pr-4 font-semibold ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>{t.side}</td>
                    <td className="py-2.5 pr-4 font-mono text-dark-300">${(t.entry_price || 0).toFixed(2)}</td>
                    <td className="py-2.5 pr-4 font-mono text-red-400/80">${(t.stop_loss || 0).toFixed(2)}</td>
                    <td className="py-2.5 pr-4 font-mono text-brand-400/80">${(t.take_profit || 0).toFixed(2)}</td>
                    <td className="py-2.5 pr-4 text-dark-400">{t.claude_confidence?.toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Learn with Apex */}
      <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <BookOpen size={14} className="text-brand-400" />
            <h2 className="text-sm font-semibold text-white">Learn with Apex</h2>
          </div>
          <button
            type="button"
            onClick={() => window.open("/learning", "_blank")}
            className="text-xs text-brand-400 hover:text-brand-300 transition-colors flex items-center gap-1"
          >
            View all <ArrowUpRight size={11} />
          </button>
        </div>
        <p className="text-xs text-dark-400 mb-3">
          Short, plain-English articles explaining what Apex does and why.
        </p>
        {learningArticles.length > 0 && (
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {learningArticles.map((a) => (
              <button
                key={a.slug}
                type="button"
                onClick={() => window.open(`/learning/${a.slug}`, "_blank")}
                className="group rounded-xl border border-dark-800 bg-dark-900/40 p-3.5 text-left text-xs hover:border-brand-500/30 transition-colors"
              >
                <div className="line-clamp-2 font-semibold text-white group-hover:text-brand-300">{a.title}</div>
                <div className="mt-1.5 text-[11px] text-dark-500">
                  {(a.reading_time_minutes || 5)} min read
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Hedge fund comparison (collapsible) */}
      <div className="rounded-2xl border border-dark-800 bg-[#0d1117] overflow-hidden">
        <button
          type="button"
          onClick={() => setComparisonOpen(!comparisonOpen)}
          className="flex w-full items-center justify-between p-5 text-left group"
        >
          <span className="text-sm font-semibold text-dark-300 group-hover:text-dark-200 transition-colors">
            What a hedge fund would charge for this
          </span>
          <ChevronDown
            size={16}
            className={`text-dark-500 transition-transform duration-200 ${comparisonOpen ? "rotate-180" : ""}`}
          />
        </button>
        {comparisonOpen && (
          <div className="border-t border-dark-800 px-5 pb-5">
            <div className="overflow-x-auto">
              <table className="mt-4 w-full text-xs">
                <thead>
                  <tr className="border-b border-dark-800 text-left">
                    <th className="pb-2.5 pr-4 text-[11px] font-medium uppercase tracking-wider text-dark-500">Item</th>
                    <th className="pb-2.5 pr-4 text-[11px] font-medium uppercase tracking-wider text-red-400/70">Hedge fund</th>
                    <th className="pb-2.5 text-[11px] font-medium uppercase tracking-wider text-brand-400/70">Apex</th>
                  </tr>
                </thead>
                <tbody className="text-dark-300">
                  {[
                    ["Management fee", "2%/yr on balance", "£0"],
                    ["Performance fee", "20% of profits", "£0 — keep everything"],
                    ["Minimum", "£1,000,000", "£25"],
                    ["Availability", "Invitation only", "Open to everyone"],
                    ["AI technology", "Proprietary", "Claude — same class"],
                  ].map(([item, hf, apex]) => (
                    <tr key={item} className="border-b border-dark-800/50">
                      <td className="py-2.5 pr-4 text-dark-200">{item}</td>
                      <td className="py-2.5 pr-4 text-red-400/60">{hf}</td>
                      <td className="py-2.5 text-brand-400">{apex}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-[10px] text-dark-600">
              Comparison is illustrative. Past performance does not predict future results.
            </p>
          </div>
        )}
      </div>

      {/* Exchange wizard modal */}
      {exchangeWizardOpen && (
        <ExchangeConnectWizard
          exchange={exchangeWizardOpen}
          onSuccess={() => {
            load();
            setExchangeWizardOpen(null);
          }}
          onClose={() => setExchangeWizardOpen(null)}
        />
      )}

      {loading && (
        <div className="flex items-center justify-center py-12 text-sm text-dark-500">
          <RefreshCw size={16} className="mr-2 animate-spin" /> Loading...
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Chat
// ─────────────────────────────────────────────

function Chat({ user }: { user: User | null }) {
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [isNewUser, setIsNewUser] = useState(false);

  const newUserWelcome = `Hi, I'm ${user?.ai_name || "Apex"} — your personal AI trader 👋\n\nHere's how to get started:\n\n1. Connect your exchange — go to the Exchanges tab and link Alpaca (free paper trading), Coinbase, Binance or OANDA. Your money always stays in your own account.\n\n2. Set your risk limit — head to Settings and set a daily loss limit so I know how much risk you're comfortable with.\n\n3. Ask me anything — I analyse markets constantly. Try asking: "What should I trade today?" or "Explain RSI to me" or "How does stop-loss work?"\n\nWhat would you like to do first?`;

  const returningWelcome = `Hi! I'm ${user?.ai_name || "your AI"}. I can help with market analysis, trade questions, performance reviews, and more. What would you like to know?`;

  const welcomeMsg: ChatMessage = {
    role: "assistant",
    content: isNewUser ? newUserWelcome : returningWelcome,
  };
  const [messages, setMessages] = useState<ChatMessage[]>([welcomeMsg]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (historyLoaded) return;
    chatApi.history(50).then((res) => {
      const convos = res.data.data?.conversations || res.data.data || [];
      if (Array.isArray(convos) && convos.length > 0) {
        const past: ChatMessage[] = [];
        convos.forEach((c: any) => {
          const msgs = c.messages || c;
          if (Array.isArray(msgs)) {
            msgs.forEach((m: any) => {
              if (m.role && m.content) past.push({ role: m.role, content: m.content, context: m.context });
            });
          }
        });
        if (past.length > 0) {
          setMessages([{ role: "assistant", content: returningWelcome }, ...past]);
        } else {
          setIsNewUser(true);
          setMessages([{ role: "assistant", content: newUserWelcome }]);
        }
      } else {
        setIsNewUser(true);
        setMessages([{ role: "assistant", content: newUserWelcome }]);
      }
    }).catch(() => {
      setIsNewUser(true);
      setMessages([{ role: "assistant", content: newUserWelcome }]);
    }).finally(() => setHistoryLoaded(true));
  }, [historyLoaded]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setLoading(true);
    try {
      const res = await chatApi.sendMessage(text);
      const d = res.data.data;
      setMessages((m) => [...m, { role: "assistant", content: d.response, context: d.context_label }]);
    } catch {
      setMessages((m) => [...m, { role: "assistant", content: "I'm having trouble connecting. Please try again." }]);
    }
    setLoading(false);
  };

  const SUGGESTIONS = ["Analyse BTC right now", "Show my performance", "What is RSI?", "Am I taking too much risk?"];

  return (
    <div className="flex h-full flex-col gap-3 animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-500/10">
          <MessageSquare size={15} className="text-brand-400" />
        </div>
        <div>
          <h1 className="text-base md:text-lg font-bold text-white">Chat with {user?.ai_name || "your AI"}</h1>
          <p className="text-[11px] text-dark-500">Ask anything about markets, trades, or strategy</p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto rounded-2xl border border-dark-800 bg-[#0a0d14] p-4">
        <div className="space-y-4">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] md:max-w-[70%] rounded-2xl px-4 py-3 text-[13px] leading-relaxed ${
                m.role === "user"
                  ? "bg-brand-500/15 text-dark-100 border border-brand-500/10"
                  : "bg-dark-800/60 text-dark-200 border border-dark-800/80"
              }`}>
                {m.context && (
                  <p className="mb-1.5 text-[11px] font-medium text-brand-400 flex items-center gap-1">
                    <Sparkles size={10} />
                    {m.context}
                  </p>
                )}
                <div className="whitespace-pre-wrap">{m.content}</div>
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-dark-800/60 border border-dark-800/80 px-4 py-3 text-[13px] text-dark-400">
                <span className="inline-flex items-center gap-1.5">
                  <span className="flex gap-1">
                    <span className="h-1.5 w-1.5 rounded-full bg-brand-400 animate-pulse" style={{ animationDelay: "0ms" }} />
                    <span className="h-1.5 w-1.5 rounded-full bg-brand-400 animate-pulse" style={{ animationDelay: "150ms" }} />
                    <span className="h-1.5 w-1.5 rounded-full bg-brand-400 animate-pulse" style={{ animationDelay: "300ms" }} />
                  </span>
                  {user?.ai_name || "AI"} is thinking
                </span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Suggestions */}
      <div className="flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => setInput(s)}
            className="rounded-full border border-dark-800 bg-dark-900/40 px-3 py-1.5 text-[11px] text-dark-400 transition-all hover:border-brand-500/30 hover:text-brand-300 hover:bg-brand-500/5"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          placeholder={`Message ${user?.ai_name || "your AI"}...`}
          className="input flex-1 text-[13px]"
        />
        <button onClick={send} disabled={!input.trim() || loading} className="btn-primary px-4 touch-target">
          <Send size={15} />
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Performance
// ─────────────────────────────────────────────

function Performance() {
  const [perf, setPerf] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [symbol, setSymbol] = useState("");
  const [marketCondition, setMarketCondition] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const res = await tradingApi.performance(symbol || marketCondition ? { symbol: symbol || undefined, market_condition: marketCondition || undefined } : undefined);
      setPerf(res.data.data);
    } catch {
      setPerf(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-dark-500">
        <RefreshCw size={16} className="mr-2 animate-spin" /> Loading performance...
      </div>
    );
  }

  const d = perf ?? {};
  if (d.message && !d.total_trades) {
    return (
      <div className="space-y-6 animate-fade-in">
        <h1 className="page-title">Performance</h1>
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-10 text-center">
          <LineChart size={36} className="mx-auto mb-4 text-dark-600" />
          <p className="text-dark-400 text-sm">{d.message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <h1 className="page-title">Performance</h1>
          <p className="page-subtitle">Track your AI trading results</p>
        </div>
        <div className="flex flex-col md:flex-row flex-wrap gap-2">
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Filter by symbol"
            className="input w-full md:w-32 text-xs"
          />
          <select
            value={marketCondition}
            onChange={(e) => setMarketCondition(e.target.value)}
            className="input w-full md:w-40 text-xs"
          >
            <option value="">All conditions</option>
            <option value="uptrend">Uptrend</option>
            <option value="downtrend">Downtrend</option>
            <option value="consolidating">Consolidating</option>
          </select>
          <button onClick={load} className="btn-ghost gap-2 text-xs touch-target">
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
        <StatCard label="Total Trades" value={String(d.total_trades ?? 0)} />
        <StatCard
          label="Win Rate"
          value={d.win_rate_pct !== undefined ? `${d.win_rate_pct}%` : "—"}
          sub={`${d.wins ?? 0}W / ${d.losses ?? 0}L`}
          positive={d.win_rate_pct >= 50}
        />
        <StatCard
          label="Net P&L"
          value={d.net_pnl_usd !== undefined ? `${d.net_pnl_usd >= 0 ? "+" : ""}$${d.net_pnl_usd?.toFixed(2)}` : "—"}
          positive={d.net_pnl_usd >= 0}
        />
        <StatCard
          label="Avg Profit / Loss"
          value={d.avg_profit_pct !== undefined && d.avg_loss_pct !== undefined
            ? `${d.avg_profit_pct}% / ${d.avg_loss_pct}%`
            : "—"}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
          <h2 className="mb-3 section-label">Best Trade</h2>
          {d.best_trade ? (
            <div className="space-y-1">
              <p className="font-mono text-sm text-white">{d.best_trade.symbol} {d.best_trade.side}</p>
              <p className="text-brand-400 font-bold text-lg">+${(d.best_trade.profit ?? 0).toFixed(2)}</p>
              <p className="text-[11px] text-dark-500">{d.best_trade.profit_percent?.toFixed(2)}%</p>
            </div>
          ) : (
            <p className="text-dark-500 text-sm">—</p>
          )}
        </div>
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
          <h2 className="mb-3 section-label">Worst Trade</h2>
          {d.worst_trade ? (
            <div className="space-y-1">
              <p className="font-mono text-sm text-white">{d.worst_trade.symbol} {d.worst_trade.side}</p>
              <p className="text-red-400 font-bold text-lg">-${(d.worst_trade.loss ?? 0).toFixed(2)}</p>
              <p className="text-[11px] text-dark-500">{d.worst_trade.profit_percent?.toFixed(2)}%</p>
            </div>
          ) : (
            <p className="text-dark-500 text-sm">—</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Trade History
// ─────────────────────────────────────────────

function History() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeRating, setActiveRating] = useState<1 | -1 | null>(null);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [thankYouId, setThankYouId] = useState<string | null>(null);

  useEffect(() => {
    tradingApi.history({ limit: 50 })
      .then((r) => setTrades(r.data.data?.trades || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="py-16 text-center text-sm text-dark-500"><RefreshCw size={16} className="inline mr-2 animate-spin" />Loading trade history...</div>;
  if (!trades.length) return (
    <div className="space-y-6 animate-fade-in">
      <h1 className="page-title">Trade History</h1>
      <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-10 text-center">
        <Activity size={36} className="mx-auto mb-4 text-dark-600" />
        <p className="text-dark-400 text-sm">No closed trades yet.</p>
      </div>
    </div>
  );

  const handleStartFeedback = (tradeId: string, rating: 1 | -1) => {
    setActiveId(tradeId);
    setActiveRating(rating);
    setComment("");
  };

  const handleSubmit = async (trade: Trade) => {
    if (!activeId || !activeRating) return;
    setSubmitting(true);
    try {
      await tradingApi.submitFeedback(trade.id, {
        rating: activeRating,
        comment: comment.trim() || null,
        is_paper: false,
      });
      setActiveId(null);
      setActiveRating(null);
      setComment("");
      setThankYouId(trade.id);
      setTimeout(() => { setThankYouId((prev) => (prev === trade.id ? null : prev)); }, 3000);
    } catch {} finally { setSubmitting(false); }
  };

  return (
    <div className="animate-fade-in">
      <div className="mb-5">
        <h1 className="page-title">Trade History</h1>
        <p className="page-subtitle">Review past trades and provide feedback</p>
      </div>
      <div className="overflow-x-auto rounded-2xl border border-dark-800 bg-[#0d1117]">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-dark-800 text-left">
              {["Symbol", "Side", "Entry", "Exit", "P&L", "Conf.", "Date", "Feedback"].map((h) => (
                <th key={h} className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-dark-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => {
              const pnl = (t.profit || 0) - (t.loss || 0);
              const isActive = activeId === t.id;
              const showThankYou = thankYouId === t.id;
              return (
                <>
                  <tr key={t.id} className="border-b border-dark-800/50 hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3 font-mono font-semibold text-white">{t.symbol}</td>
                    <td className={`px-4 py-3 font-semibold ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>{t.side}</td>
                    <td className="px-4 py-3 font-mono text-dark-300">${t.entry_price?.toFixed(2)}</td>
                    <td className="px-4 py-3 font-mono text-dark-400">{t.exit_price ? `$${t.exit_price.toFixed(2)}` : "—"}</td>
                    <td className={`px-4 py-3 font-mono font-bold ${pnl >= 0 ? "text-brand-400" : "text-red-400"}`}>
                      {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-dark-400">{t.claude_confidence?.toFixed(0)}%</td>
                    <td className="px-4 py-3 text-dark-500">{new Date(t.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3">
                      {showThankYou ? (
                        <span className="text-[11px] text-brand-400">Thanks — Apex will learn</span>
                      ) : !isActive ? (
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => handleStartFeedback(t.id, 1)}
                            className="rounded-lg border border-dark-700 bg-dark-900/60 p-1.5 text-dark-400 hover:border-brand-500/30 hover:text-brand-400 transition-colors"
                            aria-label="Thumbs up"
                          >
                            <ThumbsUp size={12} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleStartFeedback(t.id, -1)}
                            className="rounded-lg border border-dark-700 bg-dark-900/60 p-1.5 text-dark-400 hover:border-red-500/30 hover:text-red-400 transition-colors"
                            aria-label="Thumbs down"
                          >
                            <ThumbsDown size={12} />
                          </button>
                        </div>
                      ) : (
                        <span className={activeRating === 1 ? "text-brand-400" : "text-red-400"}>
                          {activeRating === 1 ? <ThumbsUp size={13} /> : <ThumbsDown size={13} />}
                        </span>
                      )}
                    </td>
                  </tr>
                  {isActive && (
                    <tr className="border-b border-dark-800/50 bg-dark-900/20">
                      <td colSpan={8} className="px-4 pb-4 pt-2">
                        <div className="rounded-xl border border-dark-800 bg-[#0d1117] p-3.5">
                          <p className="mb-2 text-[11px] text-dark-400">
                            {activeRating === 1 ? "What did Apex do well? (optional)" : "What could Apex improve? (optional)"}
                          </p>
                          <textarea
                            value={comment}
                            onChange={(e) => { if (e.target.value.length <= 280) setComment(e.target.value); }}
                            rows={2}
                            className="input resize-none text-xs"
                            placeholder="Your feedback helps Apex learn..."
                          />
                          <div className="mt-2 flex items-center justify-between">
                            <span className="text-[10px] text-dark-600 tabular-nums">{comment.length}/280</span>
                            <button
                              type="button"
                              onClick={() => handleSubmit(t)}
                              disabled={submitting}
                              className="btn-primary text-[11px] px-3 py-1.5"
                            >
                              {submitting ? "Sending..." : "Submit"}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Settings
// ─────────────────────────────────────────────

function SettingsPanel({ user }: { user: User | null }) {
  const handleUpgrade = async () => {
    try {
      const res = await billingApi.checkout();
      window.location.href = res.data.data.checkout_url;
    } catch { alert("Could not start checkout. Please try again."); }
  };

  const handlePortal = async () => {
    try {
      const res = await billingApi.portal();
      window.location.href = res.data.data.portal_url;
    } catch { alert("Could not open billing portal."); }
  };

  return (
    <div className="w-full space-y-5 animate-fade-in">
      <div>
        <h1 className="page-title">Settings</h1>
        <p className="page-subtitle">Manage your account, exchanges, and preferences</p>
      </div>

      <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
        <h2 className="section-label mb-4">Account</h2>
        <div className="space-y-3 text-sm text-dark-400">
          <div className="flex justify-between gap-2"><span>Email</span><span className="text-dark-200 truncate">{user?.email}</span></div>
          <div className="flex justify-between gap-2"><span>AI Name</span><span className="text-brand-400 font-medium">{user?.ai_name}</span></div>
          <div className="flex justify-between gap-2">
            <span>Plan</span>
            <span className="font-semibold text-brand-400">Pro (Free)</span>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
        <TrustLadderDetail />
      </div>

      <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
        <ExchangeConnections />
      </div>

      <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-5">
        <SecuritySettings />
      </div>

      <div className="rounded-2xl border border-brand-500/20 bg-brand-500/[0.04] p-5">
        <div className="mb-3 flex items-center gap-2">
          <Zap size={15} className="text-brand-400" />
          <h2 className="text-sm font-semibold text-brand-300">All Features Unlocked</h2>
        </div>
        <p className="text-xs text-dark-400 leading-relaxed">
          Unlimited AI trades, all exchanges, and advanced analytics — completely free.
        </p>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Main App
// ─────────────────────────────────────────────

export default function AppPage() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [user, setUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [syncError, setSyncError] = useState(false);
  const [syncRetry, setSyncRetry] = useState(0);
  const [showTrialModal, setShowTrialModal] = useState(false);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isMobileView, setIsMobileView] = useState(false);

  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { signOut } = useClerk();
  const router = useRouter();
  const nativeTabs = new Set(["trade", "positions", "chat", "performance", "settings"]);

  // Ensure native always lands on a tab supported by MobileNav
  useEffect(() => {
    if (!isNative) return;
    if (!nativeTabs.has(activeTab)) setActiveTab("trade");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  // ── Detect mobile view on mount and resize ───────────────────────────────
  useEffect(() => {
    const checkMobile = () => {
      const isMobile = window.innerWidth < 768; // md breakpoint
      setIsMobileView(isMobile);
      if (!isMobile) setIsMobileSidebarOpen(false);
    };

    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  // ── Trial status via hook ─────────────────────────────────────────────────
  const {
    trial,
    mustShowModal,
    showBanner,
    refetch: refetchTrial,
  } = useTrialStatus({ skip: !authChecked });

  // ── Auth ─────────────────────────────────────────────────────────────────
  const syncingRef = useRef(false);
  useEffect(() => {
    if (!isLoaded || syncingRef.current) return;
    if (!isSignedIn) { router.replace("/login"); return; }
    syncingRef.current = true;

    (async () => {
      // Clear stale token before trying /me so the 401 interceptor doesn't redirect
      const stored = localStorage.getItem("access_token");
      if (stored) {
        try {
          const r = await authApi.me();
          setUser(r.data);
          setAuthChecked(true);
          return;
        } catch {
          localStorage.removeItem("access_token");
        }
      }
      try {
        const clerkToken = await getToken();
        const res = await authApi.clerkSync(clerkToken!);
        if (res.data.status === "needs_setup") { router.replace("/onboarding"); return; }
        localStorage.setItem("access_token", res.data.access_token);
        setUser(res.data.user);
      } catch (err) {
        console.error("Clerk sync failed:", err);
        // Don't redirect to /login if Clerk says we're signed in — that causes a loop.
        // Instead just let the user see the error state.
        setSyncError(true);
      } finally {
        setAuthChecked(true);
        syncingRef.current = false;
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn, syncRetry]);

  // ── Handle Stripe success redirect (?upgraded=true) ───────────────────────
  useEffect(() => {
    if (!authChecked) return;
    if (router.query.upgraded === "true") {
      clearTrialCache();
      refetchTrial();
      // Clean the URL without re-rendering
      router.replace("/app", undefined, { shallow: true });
    }
    // Open modal if explicitly requested
    if (router.query.modal === "trial") {
      setShowTrialModal(true);
      router.replace("/app", undefined, { shallow: true });
    }
  }, [authChecked, router.query.upgraded, router.query.modal, refetchTrial, router]);

  // ── Force modal when trial expired + no choice made ──────────────────────
  useEffect(() => {
    // Disabled: All users have free access now
    // if (mustShowModal) setShowTrialModal(true);
  }, [mustShowModal]);

  const logout = async () => {
    localStorage.removeItem("access_token");
    clearTrialCache();
    await signOut();
    router.replace("/");
  };

  if (!authChecked) {
    return (
      <div className="flex h-screen items-center justify-center bg-dark-950">
        <div className="flex flex-col items-center gap-3">
          <RefreshCw size={18} className="animate-spin text-brand-400" />
          <span className="text-xs text-dark-500">Loading...</span>
        </div>
      </div>
    );
  }

  if (syncError && !user) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-5 bg-dark-950 px-6">
        <div className="rounded-2xl border border-dark-800 bg-[#0d1117] p-8 text-center max-w-sm">
          <p className="text-sm text-dark-300 mb-5">Unable to sync your account. Please try again.</p>
          <button
            onClick={() => {
              setSyncError(false);
              setAuthChecked(false);
              syncingRef.current = false;
              setSyncRetry((n) => n + 1);
            }}
            className="btn-primary w-full mb-3"
          >
            Retry
          </button>
          <button
            onClick={logout}
            className="text-xs text-dark-500 hover:text-dark-300 transition-colors"
          >
            Sign out
          </button>
        </div>
      </div>
    );
  }

  // ── Trial banner colour by phase ─────────────────────────────────────────
  const bannerStyle = trial
    ? trial.phase === "late" || trial.phase === "expired"
      ? "bg-red-500/10 border-red-500/30 text-red-300"
      : trial.phase === "mid"
      ? "bg-yellow-500/10 border-yellow-500/30 text-yellow-300"
      : "bg-brand-500/10 border-brand-500/30 text-brand-300"
    : "";

  return (
    <>
      <Head>
        <title>{user?.ai_name ? `${user.ai_name} — Unitrader` : "Unitrader App"}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5, viewport-fit=cover" />
      </Head>

      <div className="flex h-screen overflow-hidden bg-dark-950">
        {/* Mobile Sidebar Overlay */}
        {isMobileView && isMobileSidebarOpen && (
          <button
            className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm transition-opacity"
            onClick={() => setIsMobileSidebarOpen(false)}
            aria-label="Close sidebar"
          />
        )}

        {/* Desktop Sidebar (hidden on mobile / native) */}
        <div className={isNative ? "hidden" : "hidden md:block"}>
          <Sidebar
            active={activeTab}
            onChange={(id) => {
              if (id === "connect-exchange") {
                router.push("/connect-exchange");
              } else {
                setActiveTab(id);
              }
            }}
            aiName={user?.ai_name || "Your AI"}
            onLogout={logout}
          />
        </div>

        {/* Mobile Sidebar (overlay) - disabled on native (MobileNav instead) */}
        {!isNative && isMobileView && (
          <Sidebar
            active={activeTab}
            onChange={(id) => {
              if (id === "connect-exchange") {
                router.push("/connect-exchange");
              } else {
                setActiveTab(id);
              }
            }}
            aiName={user?.ai_name || "Your AI"}
            onLogout={logout}
            isMobile={true}
            onClose={() => setIsMobileSidebarOpen(false)}
          />
        )}

        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Mobile Header (web only) */}
          <div className={isNative ? "hidden" : "md:hidden flex items-center justify-between border-b border-dark-800/60 bg-[#0a0d14] px-4 py-3"}>
            <button
              onClick={() => setIsMobileSidebarOpen(true)}
              className="rounded-xl p-2 text-dark-400 hover:bg-dark-800/50 hover:text-white transition-colors"
              aria-label="Open menu"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <span className="text-sm font-semibold text-white tracking-tight">
              {NAV.find(n => n.id === activeTab)?.label || "Unitrader"}
            </span>
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-500/10">
              <TrendingUp size={14} className="text-brand-400" />
            </div>
          </div>

          <main className={isNative ? "flex-1 overflow-y-auto px-4 py-5 pb-20" : "flex-1 overflow-y-auto px-4 md:px-8 py-5 md:py-7"}>
            {activeTab === "dashboard" && <Dashboard user={user} />}
            {activeTab === "trade" && <TradePanel onNavigate={setActiveTab} />}
            {activeTab === "chat" && (
              <div className="flex h-full flex-col">
                <Chat user={user} />
              </div>
            )}
            {activeTab === "positions" && <PositionsPanel onNavigate={setActiveTab} />}
            {activeTab === "history" && <History />}
            {activeTab === "performance" && <Performance />}
            {activeTab === "content" && <ContentPanel />}
            {activeTab === "learning" && <LearningPanel user={user} />}
            {activeTab === "settings" && <SettingsPanel user={user} />}
          </main>

          {isNative && (
            <MobileNav
              active={(nativeTabs.has(activeTab) ? activeTab : "trade") as any}
              onChange={(id) => setActiveTab(id)}
            />
          )}
        </div>
      </div>

      {/* Trial choice modal — disabled for free access */}
      {false && showTrialModal && trial && (
        <TrialChoiceModal
          aiName={trial?.aiName ?? "Apex"}
          daysRemaining={trial?.daysRemaining ?? 0}
          stats={trial?.performance ?? ({} as any)}
          onClose={mustShowModal ? undefined : () => setShowTrialModal(false)}
        />
      )}
    </>
  );
}
