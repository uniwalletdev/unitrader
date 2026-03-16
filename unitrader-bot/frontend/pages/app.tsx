import Head from "next/head";
import { useState, useEffect, useRef } from "react";
import { useAuth, useClerk } from "@clerk/nextjs";
import { useRouter } from "next/router";
import {
  TrendingUp, TrendingDown, MessageSquare, BarChart3, LineChart, Settings,
  LogOut, RefreshCw, X, Send, ChevronRight, AlertTriangle,
  Zap, Shield, Activity, Clock, Crosshair, BookOpen, Brain, Plug,
} from "lucide-react";
import { tradingApi, chatApi, authApi, billingApi, exchangeApi } from "@/lib/api";
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
    <aside className={`flex h-full flex-col border-r border-dark-800 bg-dark-950 ${
      isMobile 
        ? 'fixed inset-y-0 left-0 z-40 w-64 translate-x-0 transition-transform duration-300 ease-out overflow-y-auto' 
        : 'w-56 shrink-0'
    }`}>
      {/* Header with close button for mobile */}
      <div className="flex items-center justify-between border-b border-dark-800 px-5 py-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500">
            <TrendingUp size={15} className="text-dark-950" />
          </div>
          <span className="font-bold text-white">Unitrader</span>
        </div>
        {isMobile && (
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-dark-400 hover:bg-dark-800 hover:text-white"
            aria-label="Close menu"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {/* AI status */}
      <div className="border-b border-dark-800 px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 animate-pulse-slow rounded-full bg-brand-400" />
          <span className="text-sm font-medium text-brand-400">{aiName}</span>
        </div>
        <p className="mt-0.5 text-xs text-dark-500">AI is active</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 px-3 py-3">
        {NAV.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            onClick={() => {
              onChange(id);
              // Close mobile sidebar after selection
              if (isMobile && onClose) {
                setTimeout(onClose, 300);
              }
            }}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
              active === id
                ? "bg-brand-500/10 font-medium text-brand-400"
                : "text-dark-400 hover:bg-dark-900 hover:text-dark-200"
            }`}
          >
            <Icon size={16} />
            <span className="truncate">{label}</span>
          </button>
        ))}
      </nav>

      {/* Logout */}
      <button
        onClick={onLogout}
        className="flex items-center gap-3 border-t border-dark-800 px-6 py-4 text-sm text-dark-500 hover:text-red-400 w-full"
      >
        <LogOut size={16} />
        Log Out
      </button>
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
    <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-5">
      <p className="mb-1 text-xs text-dark-500 truncate">{label}</p>
      <p className={`text-lg md:text-2xl font-bold ${positive === undefined ? "text-white" : positive ? "text-brand-400" : "text-red-400"}`}>
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-dark-500 truncate">{sub}</p>}
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
    } catch {}
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const d = perf?.data ?? perf ?? {};
  const r = risk?.data ?? risk ?? {};

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <h1 className="text-lg md:text-xl font-bold text-white truncate">
          {user?.ai_name ? `${user.ai_name}'s Dashboard` : "Dashboard"}
        </h1>
        <button onClick={load} className="btn-outline gap-2 py-2 text-xs w-full md:w-auto">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 md:gap-4 lg:grid-cols-4">
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
          sub={d.total_trades ? `${d.total_trades} trades` : undefined}
        />
      </div>

      {/* Exchange status card */}
      <div className="rounded-xl border border-dark-800 bg-dark-950 p-4 md:p-5">
        <div className="flex items-center justify-between">
          <div className="flex-1">
            {connectedExchanges.length > 0 ? (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="h-2 w-2 rounded-full bg-brand-400" />
                  <h3 className="text-sm font-semibold text-white">
                    {connectedExchanges[0].exchange.charAt(0).toUpperCase() + connectedExchanges[0].exchange.slice(1)} Connected
                  </h3>
                </div>
                <p className="text-xs text-dark-400">
                  Ready to trade — {connectedExchanges.length} exchange{connectedExchanges.length > 1 ? "s" : ""} connected
                </p>
              </div>
            ) : (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="h-2 w-2 rounded-full bg-red-400" />
                  <h3 className="text-sm font-semibold text-white">No Exchange Connected</h3>
                </div>
                <p className="text-xs text-dark-400">
                  Connect an exchange to start trading with Apex
                </p>
              </div>
            )}
          </div>
          <button
            onClick={() => setExchangeWizardOpen("alpaca")}
            className={`flex-shrink-0 rounded-lg px-4 py-2 text-xs font-medium transition ${
              connectedExchanges.length > 0
                ? "border border-brand-500/30 text-brand-400 hover:bg-brand-500/10"
                : "bg-brand-500 text-white hover:bg-brand-600"
            }`}
          >
            {connectedExchanges.length > 0 ? "Trade now" : "Connect now"}
          </button>
        </div>
      </div>

      {/* What-if simulator card (always visible; varies by trader_class) */}
      <WhatIfSimulator mode="dashboard" />

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

      {/* Risk gauge */}
      {r.daily_loss_pct !== undefined && (
        <div className="rounded-xl border border-dark-800 bg-dark-950 p-5">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-medium text-dark-200">
              <Shield size={15} className="text-brand-400" />
              Daily Risk Usage
            </div>
            <span className={`text-sm font-bold ${r.alert ? "text-red-400" : "text-brand-400"}`}>
              {r.daily_loss_pct}%
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-dark-800">
            <div
              className={`h-full rounded-full transition-all ${r.daily_loss_pct >= 80 ? "bg-red-500" : "bg-brand-500"}`}
              style={{ width: `${Math.min(r.daily_loss_pct, 100)}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-xs text-dark-500">
            <span>Daily loss: ${r.daily_loss_usd?.toFixed(2)}</span>
            <span>Remaining: ${r.remaining_budget_usd?.toFixed(2)}</span>
          </div>
          {r.alert && (
            <div className="mt-3 flex items-center gap-2 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-400">
              <AlertTriangle size={13} />
              {r.alert_message}
            </div>
          )}
        </div>
      )}

      {/* Open positions */}
      {openPositions.length > 0 && (
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-5">
          <h2 className="mb-4 text-sm font-semibold text-dark-200">Open Positions</h2>
          <div className="overflow-x-auto -mx-3 md:mx-0">
            <table className="w-full text-xs md:text-sm px-3">
              <thead>
                <tr className="border-b border-dark-800 text-left text-dark-500">
                  {["Symbol", "Side", "Entry", "Stop", "Target", "Conf."].map((h) => (
                    <th key={h} className="pb-2 pr-3 md:pr-4 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {openPositions.map((t) => (
                  <tr key={t.id} className="border-b border-dark-900 text-dark-300">
                    <td className="py-2 pr-3 md:pr-4 font-mono font-medium text-white">{t.symbol}</td>
                    <td className={`py-2 pr-3 md:pr-4 font-semibold ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>{t.side}</td>
                    <td className="py-2 pr-3 md:pr-4 font-mono text-xs">${(t.entry_price || 0).toFixed(2)}</td>
                    <td className="py-2 pr-3 md:pr-4 font-mono text-xs text-red-400">${(t.stop_loss || 0).toFixed(2)}</td>
                    <td className="py-2 pr-3 md:pr-4 font-mono text-xs text-brand-400">${(t.take_profit || 0).toFixed(2)}</td>
                    <td className="py-2 pr-3 md:pr-4">{t.claude_confidence?.toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-10 text-sm text-dark-500">
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
  const welcomeMsg: ChatMessage = {
    role: "assistant",
    content: `Hi! I'm ${user?.ai_name || "your AI"}. I can help with market analysis, trade questions, performance reviews, and more. What would you like to know?`,
  };
  const [messages, setMessages] = useState<ChatMessage[]>([welcomeMsg]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load conversation history on mount
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
        if (past.length > 0) setMessages([welcomeMsg, ...past]);
      }
    }).catch(() => {}).finally(() => setHistoryLoaded(true));
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

  const SUGGESTIONS = ["Analyse BTC right now", "Show my performance", "What is RSI?", "Feeling worried about losses"];

  return (
    <div className="flex h-full flex-col gap-2 md:gap-4">
      <div className="flex items-center gap-2">
        <MessageSquare size={16} className="text-brand-400" />
        <h1 className="text-base md:text-xl font-bold text-white truncate">Chat with {user?.ai_name || "your AI"}</h1>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-4">
        <div className="space-y-3 md:space-y-4">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] md:max-w-[75%] rounded-lg md:rounded-xl px-3 md:px-4 py-2 md:py-3 text-xs md:text-sm leading-relaxed ${
                m.role === "user"
                  ? "bg-brand-500/20 text-dark-100"
                  : "bg-dark-900 text-dark-200"
              }`}>
                {m.context && (
                  <p className="mb-1 text-xs font-medium text-brand-400">{m.context}</p>
                )}
                {m.content}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="rounded-lg md:rounded-xl bg-dark-900 px-3 md:px-4 py-2 md:py-3 text-xs md:text-sm text-dark-400">
                <span className="animate-pulse">{user?.ai_name || "AI"} is thinking...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Suggestions */}
      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => setInput(s)}
            className="rounded-full border border-dark-700 px-2 md:px-3 py-1 text-xs text-dark-400 transition hover:border-brand-500/50 hover:text-brand-400 truncate"
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
          className="input flex-1 text-xs md:text-sm"
        />
        <button onClick={send} disabled={!input.trim() || loading} className="btn-primary px-3 md:px-4 touch-target">
          <Send size={16} />
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
      const params: Record<string, string> = {};
      if (symbol) params.symbol = symbol.toUpperCase();
      if (marketCondition) params.market_condition = marketCondition;
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
      <div className="space-y-6">
        <h1 className="text-xl font-bold text-white">Performance</h1>
        <div className="rounded-xl border border-dark-800 bg-dark-950 p-8 text-center">
          <LineChart size={40} className="mx-auto mb-3 text-dark-500" />
          <p className="text-dark-400">{d.message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 md:gap-4">
        <h1 className="text-base md:text-xl font-bold text-white">Performance</h1>
        <div className="flex flex-col md:flex-row flex-wrap gap-2">
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Filter by symbol"
            className="input w-full md:w-32 text-xs md:text-sm"
          />
          <select
            value={marketCondition}
            onChange={(e) => setMarketCondition(e.target.value)}
            className="input w-full md:w-40 text-xs md:text-sm"
          >
            <option value="">All conditions</option>
            <option value="uptrend">Uptrend</option>
            <option value="downtrend">Downtrend</option>
            <option value="consolidating">Consolidating</option>
          </select>
          <button onClick={load} className="btn-outline gap-2 py-2 text-xs touch-target w-full md:w-auto">
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 md:gap-4 lg:grid-cols-4">
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
          label="Avg Profit / Loss %"
          value={d.avg_profit_pct !== undefined && d.avg_loss_pct !== undefined
            ? `${d.avg_profit_pct}% / ${d.avg_loss_pct}%`
            : "—"}
        />
      </div>

      <div className="grid gap-2 md:gap-4 grid-cols-1 md:grid-cols-2">
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-5">
          <h2 className="mb-3 text-xs md:text-sm font-semibold text-dark-200">Best Trade</h2>
          {d.best_trade ? (
            <div className="space-y-1 text-xs md:text-sm">
              <p className="font-mono text-white">{d.best_trade.symbol} {d.best_trade.side}</p>
              <p className="text-brand-400 font-bold">+${(d.best_trade.profit ?? 0).toFixed(2)}</p>
              <p className="text-xs text-dark-500">{d.best_trade.profit_percent?.toFixed(2)}%</p>
            </div>
          ) : (
            <p className="text-dark-500 text-xs md:text-sm">—</p>
          )}
        </div>
        <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-5">
          <h2 className="mb-3 text-xs md:text-sm font-semibold text-dark-200">Worst Trade</h2>
          {d.worst_trade ? (
            <div className="space-y-1 text-xs md:text-sm">
              <p className="font-mono text-white">{d.worst_trade.symbol} {d.worst_trade.side}</p>
              <p className="text-red-400 font-bold">-${(d.worst_trade.loss ?? 0).toFixed(2)}</p>
              <p className="text-xs text-dark-500">{d.worst_trade.profit_percent?.toFixed(2)}%</p>
            </div>
          ) : (
            <p className="text-dark-500 text-xs md:text-sm">—</p>
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

  useEffect(() => {
    tradingApi.history({ limit: 50 })
      .then((r) => setTrades(r.data.data?.trades || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="py-10 text-center text-sm text-dark-500">Loading trade history...</div>;
  if (!trades.length) return <div className="py-10 text-center text-sm text-dark-500">No closed trades yet.</div>;

  return (
    <div>
      <h1 className="mb-6 text-base md:text-xl font-bold text-white">Trade History</h1>
      <div className="overflow-x-auto rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 -mx-3 md:mx-0">
        <table className="w-full text-xs md:text-sm">
          <thead>
            <tr className="border-b border-dark-800 text-left text-dark-500">
              {["Symbol", "Side", "Entry", "Exit", "P&L", "Conf.", "Date"].map((h) => (
                <th key={h} className="px-2 md:px-4 py-2 md:py-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => {
              const pnl = (t.profit || 0) - (t.loss || 0);
              return (
                <tr key={t.id} className="border-b border-dark-900 hover:bg-dark-900/50">
                  <td className="px-2 md:px-4 py-2 md:py-3 font-mono font-medium text-white">{t.symbol}</td>
                  <td className={`px-2 md:px-4 py-2 md:py-3 font-semibold ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>{t.side}</td>
                  <td className="px-2 md:px-4 py-2 md:py-3 font-mono text-xs md:text-sm">${t.entry_price?.toFixed(2)}</td>
                  <td className="px-2 md:px-4 py-2 md:py-3 font-mono text-dark-400 text-xs md:text-sm">{t.exit_price ? `$${t.exit_price.toFixed(2)}` : "—"}</td>
                  <td className={`px-2 md:px-4 py-2 md:py-3 font-mono font-bold text-xs md:text-sm ${pnl >= 0 ? "text-brand-400" : "text-red-400"}`}>
                    {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                  </td>
                  <td className="px-2 md:px-4 py-2 md:py-3 text-dark-400 text-xs md:text-sm">{t.claude_confidence?.toFixed(0)}%</td>
                  <td className="px-2 md:px-4 py-2 md:py-3 text-dark-500 text-xs md:text-sm">{new Date(t.created_at).toLocaleDateString()}</td>
                </tr>
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
    <div className="w-full space-y-4 md:space-y-6">
      <h1 className="text-base md:text-xl font-bold text-white">Settings</h1>

      <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-5">
        <h2 className="mb-3 text-xs md:text-sm font-semibold text-dark-200">Account</h2>
        <div className="space-y-2 text-xs md:text-sm text-dark-400">
          <div className="flex justify-between gap-2"><span>Email</span><span className="text-dark-200 text-right truncate">{user?.email}</span></div>
          <div className="flex justify-between gap-2"><span>AI Name</span><span className="text-brand-400 font-medium text-right">{user?.ai_name}</span></div>
          <div className="flex justify-between gap-2">
            <span>Plan</span>
            <span className={`font-semibold capitalize text-right text-brand-400`}>
              Pro (Free)
            </span>
          </div>
        </div>
      </div>

      {/* Trust Ladder (only complete_novice / curious_saver) */}
      <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-5">
        <TrustLadderDetail />
      </div>

      {/* Exchange Connections */}
      <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-5">
        <ExchangeConnections />
      </div>

      {/* Security & Connected Apps */}
      <div className="rounded-lg md:rounded-xl border border-dark-800 bg-dark-950 p-3 md:p-5">
        <SecuritySettings />
      </div>

      <div className="rounded-lg md:rounded-xl border border-brand-500/30 bg-brand-500/5 p-3 md:p-5">
        <div className="mb-3 flex items-center gap-2">
          <Zap size={16} className="text-brand-400" />
          <h2 className="text-xs md:text-sm font-semibold text-brand-300">All Features Unlocked</h2>
        </div>
        <p className="text-xs text-dark-400">
          You have access to unlimited AI trades, all exchanges, and advanced analytics — completely free.
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
  const [showTrialModal, setShowTrialModal] = useState(false);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isMobileView, setIsMobileView] = useState(false);

  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { signOut } = useClerk();
  const router = useRouter();

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
  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) { router.replace("/login"); return; }

    (async () => {
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
      } catch {
        router.replace("/login");
      } finally {
        setAuthChecked(true);
      }
    })();
  }, [isLoaded, isSignedIn, getToken, router]);

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
      <div className="flex h-screen items-center justify-center bg-dark-950 text-dark-400">
        <RefreshCw size={20} className="animate-spin" />
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

      <div className="flex h-screen overflow-hidden bg-[#0d1117]">
        {/* Mobile Sidebar Overlay */}
        {isMobileView && isMobileSidebarOpen && (
          <button
            className="fixed inset-0 z-30 bg-black/50 transition-opacity"
            onClick={() => setIsMobileSidebarOpen(false)}
            aria-label="Close sidebar"
          />
        )}

        {/* Desktop Sidebar (hidden on mobile) */}
        <div className="hidden md:block">
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

        {/* Mobile Sidebar (overlay) */}
        {isMobileView && (
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
          {/* Mobile Header */}
          <div className="md:hidden flex items-center justify-between border-b border-dark-800 bg-dark-950 px-4 py-3 gap-3">
            <button
              onClick={() => setIsMobileSidebarOpen(true)}
              className="rounded-lg p-2 text-dark-400 hover:bg-dark-800 hover:text-white touch-target"
              aria-label="Open menu"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <span className="text-sm font-semibold text-white flex-1 truncate">
              {NAV.find(n => n.id === activeTab)?.label || "Unitrader"}
            </span>
            <div className="flex h-6 w-6 items-center justify-center rounded bg-brand-500/20">
              <TrendingUp size={14} className="text-brand-400" />
            </div>
          </div>

          {/* Trial banner - disabled for free access */}
          {false && showBanner && trial && (
            <div className={`flex items-center justify-between border-b px-4 md:px-5 py-2 text-xs gap-2 ${bannerStyle}`}>
              <div className="flex items-center gap-2 min-w-0">
                <Clock size={13} className="shrink-0" />
                <span className="truncate text-xs md:text-sm">
                  {trial?.phase === "expired"
                    ? `${trial?.aiName ?? "Apex"}'s trial has ended — choose a plan to continue`
                    : (trial?.daysRemaining ?? 0) <= 1
                    ? `${trial?.aiName ?? "Apex"}'s trial ends TODAY! Net P&L: ${(trial?.performance?.net_pnl ?? 0) >= 0 ? "+" : ""}$${Math.abs(trial?.performance?.net_pnl ?? 0).toFixed(2)}`
                    : trial?.phase === "late"
                    ? `⏰ ${trial?.daysRemaining ?? "—"} days left — ${trial?.aiName ?? "Apex"} made ${(trial?.performance?.net_pnl ?? 0) >= 0 ? "+" : ""}$${Math.abs(trial?.performance?.net_pnl ?? 0).toFixed(2)} for you`
                    : trial?.phase === "mid"
                    ? `${trial?.aiName ?? "Apex"}: ${trial?.daysRemaining ?? "—"} days left · ${trial?.performance?.trades_made ?? 0} trades · ${(trial?.performance?.net_pnl ?? 0) >= 0 ? "+" : ""}$${Math.abs(trial?.performance?.net_pnl ?? 0).toFixed(2)}`
                    : `Trial active: ${trial?.daysRemaining ?? "—"} days remaining — ${trial?.aiName ?? "Apex"} is learning your style`}
                </span>
              </div>
              <button
                onClick={() => setShowTrialModal(true)}
                className="ml-2 shrink-0 rounded-md border border-current px-2 md:px-3 py-1 text-xs md:text-sm font-medium hover:opacity-80 transition whitespace-nowrap touch-target"
              >
                {trial?.phase === "expired" || (trial?.daysRemaining ?? 0) <= 1 ? "Choose →" : "View →"}
              </button>
            </div>
          )}

          <main className="flex-1 overflow-y-auto px-3 md:px-6 py-4 md:py-6">
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
