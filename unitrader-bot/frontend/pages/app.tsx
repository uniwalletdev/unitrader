import Head from "next/head";
import { useState, useEffect, useRef } from "react";
import { useAuth, useClerk } from "@clerk/nextjs";
import { useRouter } from "next/router";
import {
  TrendingUp, TrendingDown, MessageSquare, BarChart3, Settings,
  LogOut, RefreshCw, X, Send, ChevronRight, AlertTriangle,
  Zap, Shield, Activity, Clock,
} from "lucide-react";
import { tradingApi, chatApi, authApi, billingApi } from "@/lib/api";
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
  { id: "chat", icon: MessageSquare, label: "Chat" },
  { id: "positions", icon: TrendingUp, label: "Positions" },
  { id: "history", icon: Activity, label: "History" },
  { id: "settings", icon: Settings, label: "Settings" },
];

function Sidebar({ active, onChange, aiName, onLogout }: {
  active: string; onChange: (id: string) => void;
  aiName: string; onLogout: () => void;
}) {
  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-dark-800 bg-dark-950">
      {/* Logo */}
      <div className="flex items-center gap-2 border-b border-dark-800 px-5 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500">
          <TrendingUp size={15} className="text-dark-950" />
        </div>
        <span className="font-bold text-white">Unitrader</span>
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
            onClick={() => onChange(id)}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
              active === id
                ? "bg-brand-500/10 font-medium text-brand-400"
                : "text-dark-400 hover:bg-dark-900 hover:text-dark-200"
            }`}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </nav>

      {/* Logout */}
      <button
        onClick={onLogout}
        className="flex items-center gap-3 border-t border-dark-800 px-6 py-4 text-sm text-dark-500 hover:text-red-400"
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
    <div className="rounded-xl border border-dark-800 bg-dark-950 p-5">
      <p className="mb-1 text-xs text-dark-500">{label}</p>
      <p className={`text-2xl font-bold ${positive === undefined ? "text-white" : positive ? "text-brand-400" : "text-red-400"}`}>
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-dark-500">{sub}</p>}
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
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [perfRes, riskRes, posRes] = await Promise.all([
        tradingApi.performance(),
        tradingApi.riskAnalysis(),
        tradingApi.openPositions(),
      ]);
      setPerf(perfRes.data.data);
      setRisk(riskRes.data.data);
      setOpenPositions(posRes.data.data?.positions || []);
    } catch {}
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const d = perf?.data ?? perf ?? {};
  const r = risk?.data ?? risk ?? {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">
          {user?.ai_name ? `${user.ai_name}'s Dashboard` : "Dashboard"}
        </h1>
        <button onClick={load} className="btn-outline gap-2 py-2 text-xs">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
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
        <div className="rounded-xl border border-dark-800 bg-dark-950 p-5">
          <h2 className="mb-4 text-sm font-semibold text-dark-200">Open Positions</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-dark-800 text-left text-dark-500">
                  {["Symbol", "Side", "Entry", "Stop", "Target", "Conf.", "Time"].map((h) => (
                    <th key={h} className="pb-2 pr-4 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {openPositions.map((t) => (
                  <tr key={t.id} className="border-b border-dark-900 text-dark-300">
                    <td className="py-2 pr-4 font-mono font-medium text-white">{t.symbol}</td>
                    <td className={`py-2 pr-4 font-semibold ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>{t.side}</td>
                    <td className="py-2 pr-4 font-mono">${t.entry_price?.toLocaleString()}</td>
                    <td className="py-2 pr-4 font-mono text-red-400">${t.stop_loss?.toLocaleString()}</td>
                    <td className="py-2 pr-4 font-mono text-brand-400">${t.take_profit?.toLocaleString()}</td>
                    <td className="py-2 pr-4">{t.claude_confidence?.toFixed(0)}%</td>
                    <td className="py-2 text-dark-500">{new Date(t.created_at).toLocaleTimeString()}</td>
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
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content: `Hi! I'm ${user?.ai_name || "your AI"}. I can help with market analysis, trade questions, performance reviews, and more. What would you like to know?`,
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

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
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-2">
        <MessageSquare size={18} className="text-brand-400" />
        <h1 className="text-xl font-bold text-white">Chat with {user?.ai_name || "your AI"}</h1>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto rounded-xl border border-dark-800 bg-dark-950 p-4">
        <div className="space-y-4">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[75%] rounded-xl px-4 py-3 text-sm leading-relaxed ${
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
              <div className="rounded-xl bg-dark-900 px-4 py-3 text-sm text-dark-400">
                <span className="animate-pulse">{user?.ai_name || "AI"} is thinking...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Suggestions */}
      <div className="my-3 flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => setInput(s)}
            className="rounded-full border border-dark-700 px-3 py-1 text-xs text-dark-400 transition hover:border-brand-500/50 hover:text-brand-400"
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
          className="input flex-1"
        />
        <button onClick={send} disabled={!input.trim() || loading} className="btn-primary px-4">
          <Send size={16} />
        </button>
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
      <h1 className="mb-6 text-xl font-bold text-white">Trade History</h1>
      <div className="overflow-x-auto rounded-xl border border-dark-800 bg-dark-950">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-dark-800 text-left text-dark-500">
              {["Symbol", "Side", "Entry", "Exit", "P&L", "Conf.", "Date"].map((h) => (
                <th key={h} className="px-4 py-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => {
              const pnl = (t.profit || 0) - (t.loss || 0);
              return (
                <tr key={t.id} className="border-b border-dark-900 hover:bg-dark-900/50">
                  <td className="px-4 py-3 font-mono font-medium text-white">{t.symbol}</td>
                  <td className={`px-4 py-3 font-semibold ${t.side === "BUY" ? "text-brand-400" : "text-red-400"}`}>{t.side}</td>
                  <td className="px-4 py-3 font-mono">${t.entry_price?.toLocaleString()}</td>
                  <td className="px-4 py-3 font-mono text-dark-400">{t.exit_price ? `$${t.exit_price.toLocaleString()}` : "—"}</td>
                  <td className={`px-4 py-3 font-mono font-bold ${pnl >= 0 ? "text-brand-400" : "text-red-400"}`}>
                    {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-dark-400">{t.claude_confidence?.toFixed(0)}%</td>
                  <td className="px-4 py-3 text-dark-500">{new Date(t.created_at).toLocaleDateString()}</td>
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
    <div className="max-w-lg space-y-6">
      <h1 className="text-xl font-bold text-white">Settings</h1>

      <div className="rounded-xl border border-dark-800 bg-dark-950 p-5">
        <h2 className="mb-3 text-sm font-semibold text-dark-200">Account</h2>
        <div className="space-y-2 text-sm text-dark-400">
          <div className="flex justify-between"><span>Email</span><span className="text-dark-200">{user?.email}</span></div>
          <div className="flex justify-between"><span>AI Name</span><span className="text-brand-400 font-medium">{user?.ai_name}</span></div>
          <div className="flex justify-between">
            <span>Plan</span>
            <span className={`font-semibold capitalize ${user?.subscription_tier === "pro" ? "text-brand-400" : "text-dark-200"}`}>
              {user?.subscription_tier}
            </span>
          </div>
        </div>
      </div>

      {user?.subscription_tier !== "pro" ? (
        <div className="rounded-xl border border-brand-500/30 bg-brand-500/5 p-5">
          <div className="mb-3 flex items-center gap-2">
            <Zap size={16} className="text-brand-400" />
            <h2 className="text-sm font-semibold text-brand-300">Upgrade to Pro</h2>
          </div>
          <p className="mb-4 text-xs text-dark-400">
            Unlimited AI trades, all exchanges, advanced analytics. 7-day free trial included.
          </p>
          <button onClick={handleUpgrade} className="btn-primary w-full">
            Start 7-Day Free Trial — $9.99/mo
          </button>
        </div>
      ) : (
        <div className="rounded-xl border border-dark-800 bg-dark-950 p-5">
          <h2 className="mb-3 text-sm font-semibold text-dark-200">Billing</h2>
          <p className="mb-4 text-xs text-dark-400">Manage subscription, invoices, and payment method.</p>
          <button onClick={handlePortal} className="btn-outline w-full">
            Open Billing Portal
          </button>
        </div>
      )}
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

  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { signOut } = useClerk();
  const router = useRouter();

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
    if (mustShowModal) setShowTrialModal(true);
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
      </Head>

      <div className="flex h-screen overflow-hidden bg-[#0d1117]">
        <Sidebar
          active={activeTab}
          onChange={setActiveTab}
          aiName={user?.ai_name || "Your AI"}
          onLogout={logout}
        />

        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Trial banner */}
          {showBanner && trial && (
            <div className={`flex items-center justify-between border-b px-5 py-2 text-xs ${bannerStyle}`}>
              <div className="flex items-center gap-2 min-w-0">
                <Clock size={13} className="shrink-0" />
                <span className="truncate">
                  {trial.phase === "expired"
                    ? `${trial.aiName}'s trial has ended — choose a plan to continue`
                    : trial.daysRemaining <= 1
                    ? `${trial.aiName}'s trial ends TODAY! Net P&L: ${trial.performance.net_pnl >= 0 ? "+" : ""}$${Math.abs(trial.performance.net_pnl).toFixed(2)}`
                    : trial.phase === "late"
                    ? `⏰ ${trial.daysRemaining} days left — ${trial.aiName} made ${trial.performance.net_pnl >= 0 ? "+" : ""}$${Math.abs(trial.performance.net_pnl).toFixed(2)} for you`
                    : trial.phase === "mid"
                    ? `${trial.aiName}: ${trial.daysRemaining} days left · ${trial.performance.trades_made} trades · ${trial.performance.net_pnl >= 0 ? "+" : ""}$${Math.abs(trial.performance.net_pnl).toFixed(2)}`
                    : `Trial active: ${trial.daysRemaining} days remaining — ${trial.aiName} is learning your style`}
                </span>
              </div>
              <button
                onClick={() => setShowTrialModal(true)}
                className="ml-4 shrink-0 rounded-md border border-current px-3 py-1 font-medium hover:opacity-80 transition whitespace-nowrap"
              >
                {trial.phase === "expired" || trial.daysRemaining <= 1 ? "Choose Plan →" : "View Options →"}
              </button>
            </div>
          )}

          <main className="flex-1 overflow-y-auto px-6 py-6">
            {activeTab === "dashboard" && <Dashboard user={user} />}
            {activeTab === "chat" && (
              <div className="flex h-full flex-col">
                <Chat user={user} />
              </div>
            )}
            {activeTab === "positions" && <Dashboard user={user} />}
            {activeTab === "history" && <History />}
            {activeTab === "settings" && <SettingsPanel user={user} />}
          </main>
        </div>
      </div>

      {/* Trial choice modal — forced open when expired+no choice, soft-close otherwise */}
      {showTrialModal && trial && (
        <TrialChoiceModal
          aiName={trial.aiName}
          daysRemaining={trial.daysRemaining}
          stats={trial.performance}
          onClose={mustShowModal ? undefined : () => setShowTrialModal(false)}
        />
      )}
    </>
  );
}
