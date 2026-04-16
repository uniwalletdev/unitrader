import Head from "next/head";
import { useState, useEffect, useCallback } from "react";
import {
  Users, BarChart3, Search, ChevronLeft, ChevronRight,
  Shield, X, Check, AlertTriangle, TrendingUp, RefreshCw,
  Cpu, DollarSign, Activity, Gauge,
} from "lucide-react";
import { adminApi, tokenApi } from "@/lib/api";

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

interface UserRow {
  id: string;
  email: string;
  ai_name: string;
  subscription_tier: string;
  trial_status: string;
  trial_end_date: string | null;
  is_active: boolean;
  created_at: string | null;
  last_login: string | null;
  trade_count: number;
  exchange_count: number;
}

interface ExchangeInfo {
  id: string;
  exchange: string;
  is_paper: boolean;
  account_label: string;
  is_active: boolean;
  auto_trade_enabled: boolean;
  last_known_balance_usd: number | null;
}

interface ChannelInfo {
  platform: string;
  external_username: string | null;
  is_linked: boolean;
}

interface UserDetail {
  id: string;
  email: string;
  ai_name: string;
  subscription_tier: string;
  stripe_customer_id: string | null;
  stripe_subscription_status: string | null;
  trial_status: string;
  trial_end_date: string | null;
  trial_started_at: string | null;
  is_active: boolean;
  email_verified: boolean;
  created_at: string | null;
  last_login: string | null;
  trading_paused: boolean;
  trade_count: number;
  exchanges: ExchangeInfo[];
  channels: ChannelInfo[];
}

interface Metrics {
  total_users: number;
  active_users: number;
  free_users: number;
  pro_users: number;
  elite_users: number;
  active_trials: number;
  expired_trials: number;
  converted_trials: number;
  conversion_rate: number;
  total_trades: number;
  trades_this_month: number;
  mrr_cents: number;
}

interface TokenBudgetInfo {
  month_start: string;
  month_end: string;
  budget_total: number;
  budget_used: number;
  pct_used: number;
  cost_total_usd: number;
  status: string;
  alerts: { "70": boolean; "85": boolean; "95": boolean };
}
interface AgentCostRow {
  agent_name: string;
  tokens: number;
  cost_usd: number;
  calls: number;
}
interface DashboardPayload {
  budget: TokenBudgetInfo;
  calls_last_24h: number;
  agents_by_cost: AgentCostRow[];
}
interface RateRow {
  agent_name: string;
  priority: string;
  tokens_per_minute: number;
  tokens_used_this_minute: number;
  last_reset: string | null;
}
interface ConsumptionPoint {
  day: string;
  agent_name: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  calls: number;
}

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

const tierBadge = (tier: string) => {
  const cls: Record<string, string> = {
    free: "bg-dark-800 text-dark-300",
    pro: "bg-brand-500/20 text-brand-400",
    elite: "bg-purple-500/20 text-purple-400",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold uppercase ${cls[tier] || cls.free}`}>
      {tier}
    </span>
  );
};

const trialBadge = (s: string) => {
  const cls: Record<string, string> = {
    active: "text-green-400",
    expired: "text-red-400",
    converted: "text-brand-400",
  };
  return <span className={`text-xs font-medium ${cls[s] || "text-dark-400"}`}>{s}</span>;
};

const fmt = (d: string | null) => (d ? new Date(d).toLocaleDateString() : "—");
const fmtMoney = (cents: number) => `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

// ─────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────

export default function AdminPage() {
  const [authed, setAuthed] = useState(false);
  const [secretInput, setSecretInput] = useState("");
  const [authError, setAuthError] = useState("");

  // Tab state
  const [tab, setTab] = useState<"users" | "metrics" | "tokens">("users");

  // User list
  const [users, setUsers] = useState<UserRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [tierFilter, setTierFilter] = useState("");
  const [loading, setLoading] = useState(false);

  // User detail
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editTier, setEditTier] = useState("");
  const [editPaused, setEditPaused] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  // Metrics
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);

  const PAGE_SIZE = 50;

  // ── Auth ─────────────────────────────────────

  useEffect(() => {
    const stored = localStorage.getItem("admin_secret");
    if (stored) setAuthed(true);
  }, []);

  const handleLogin = async () => {
    setAuthError("");
    localStorage.setItem("admin_secret", secretInput);
    try {
      await adminApi.metrics();
      setAuthed(true);
    } catch {
      localStorage.removeItem("admin_secret");
      setAuthError("Invalid admin secret");
    }
  };

  // ── Fetch users ──────────────────────────────

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminApi.users({ page, page_size: PAGE_SIZE, search, tier: tierFilter });
      const d = res.data;
      setUsers(d.users);
      setTotal(d.total);
    } catch {
      setUsers([]);
    }
    setLoading(false);
  }, [page, search, tierFilter]);

  useEffect(() => {
    if (authed && tab === "users") fetchUsers();
  }, [authed, tab, fetchUsers]);

  // ── Fetch metrics ────────────────────────────

  const fetchMetrics = useCallback(async () => {
    setMetricsLoading(true);
    try {
      const res = await adminApi.metrics();
      setMetrics(res.data);
    } catch {
      setMetrics(null);
    }
    setMetricsLoading(false);
  }, []);

  useEffect(() => {
    if (authed && tab === "metrics") fetchMetrics();
  }, [authed, tab, fetchMetrics]);

  // ── Token dashboard ──────────────────────────
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null);
  const [rates, setRates] = useState<RateRow[]>([]);
  const [consumption, setConsumption] = useState<ConsumptionPoint[]>([]);
  const [tokensLoading, setTokensLoading] = useState(false);

  const fetchTokens = useCallback(async () => {
    setTokensLoading(true);
    try {
      const [d, r, c] = await Promise.all([
        tokenApi.dashboard(),
        tokenApi.rates(),
        tokenApi.consumption(undefined, 7),
      ]);
      setDashboard(d.data);
      setRates(r.data?.agents || []);
      setConsumption(c.data?.series || []);
    } catch (e) {
      console.error("tokenApi fetch failed", e);
    } finally {
      setTokensLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authed && tab === "tokens") {
      fetchTokens();
      const iv = setInterval(fetchTokens, 30_000); // auto-refresh every 30s
      return () => clearInterval(iv);
    }
  }, [authed, tab, fetchTokens]);

  // ── User detail ──────────────────────────────

  const openDetail = async (userId: string) => {
    setDetailLoading(true);
    setSaveMsg("");
    try {
      const res = await adminApi.userDetail(userId);
      const d: UserDetail = res.data;
      setDetail(d);
      setEditTier(d.subscription_tier);
      setEditPaused(d.trading_paused);
    } catch {
      setDetail(null);
    }
    setDetailLoading(false);
  };

  const handleSave = async () => {
    if (!detail) return;
    setSaving(true);
    setSaveMsg("");
    try {
      const res = await adminApi.updateUser(detail.id, {
        subscription_tier: editTier,
        trading_paused: editPaused,
      });
      setDetail(res.data);
      setSaveMsg("Saved");
      fetchUsers(); // refresh list
    } catch {
      setSaveMsg("Save failed");
    }
    setSaving(false);
  };

  // ── Login gate ───────────────────────────────

  if (!authed) {
    return (
      <>
        <Head><title>Admin — Unitrader</title></Head>
        <div className="flex min-h-screen items-center justify-center bg-dark-950 p-4">
          <div className="w-full max-w-sm rounded-2xl border border-dark-700 bg-dark-900 p-8">
            <div className="mb-6 flex items-center gap-2">
              <Shield size={20} className="text-brand-400" />
              <h1 className="text-lg font-bold text-white">Admin Access</h1>
            </div>
            <input
              type="password"
              placeholder="Admin secret key"
              value={secretInput}
              onChange={(e) => setSecretInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
              className="mb-4 w-full rounded-lg border border-dark-600 bg-dark-800 px-4 py-2.5 text-sm text-white placeholder-dark-500 outline-none focus:border-brand-500"
            />
            {authError && <p className="mb-3 text-sm text-red-400">{authError}</p>}
            <button
              onClick={handleLogin}
              className="btn-primary w-full py-2.5 text-sm font-semibold"
            >
              Enter
            </button>
          </div>
        </div>
      </>
    );
  }

  // ── Main layout ──────────────────────────────

  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  return (
    <>
      <Head><title>Admin — Unitrader</title></Head>
      <div className="min-h-screen bg-dark-950 text-white">

        {/* Top bar */}
        <header className="flex items-center justify-between border-b border-dark-800 bg-dark-900 px-6 py-3">
          <div className="flex items-center gap-3">
            <Shield size={18} className="text-brand-400" />
            <span className="font-bold">Unitrader Admin</span>
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => setTab("users")}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${tab === "users" ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white"}`}
            >
              <Users size={14} /> Users
            </button>
            <button
              onClick={() => setTab("metrics")}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${tab === "metrics" ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white"}`}
            >
              <BarChart3 size={14} /> Metrics
            </button>
            <button
              onClick={() => setTab("tokens")}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${tab === "tokens" ? "bg-dark-700 text-white" : "text-dark-400 hover:text-white"}`}
            >
              <Cpu size={14} /> Tokens
            </button>
          </div>
          <button
            onClick={() => { localStorage.removeItem("admin_secret"); setAuthed(false); }}
            className="text-xs text-dark-500 hover:text-red-400 transition"
          >
            Logout
          </button>
        </header>

        {/* ── Users tab ─────────────────────────── */}
        {tab === "users" && (
          <div className="flex">
            {/* List panel */}
            <div className={`${detail ? "w-1/2" : "w-full"} border-r border-dark-800 transition-all`}>
              {/* Toolbar */}
              <div className="flex flex-wrap items-center gap-3 border-b border-dark-800 px-6 py-3">
                <div className="relative flex-1 min-w-[200px]">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-500" />
                  <input
                    type="text"
                    placeholder="Search email or AI name…"
                    value={search}
                    onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                    className="w-full rounded-lg border border-dark-700 bg-dark-800 py-2 pl-9 pr-3 text-sm text-white placeholder-dark-500 outline-none focus:border-brand-500"
                  />
                </div>
                <select
                  value={tierFilter}
                  onChange={(e) => { setTierFilter(e.target.value); setPage(1); }}
                  className="rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-white outline-none"
                >
                  <option value="">All tiers</option>
                  <option value="free">Free</option>
                  <option value="pro">Pro</option>
                  <option value="elite">Elite</option>
                </select>
                <button onClick={fetchUsers} className="text-dark-400 hover:text-white transition">
                  <RefreshCw size={14} />
                </button>
                <span className="text-xs text-dark-500">{total} users</span>
              </div>

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-dark-800 text-left text-[11px] uppercase tracking-wider text-dark-500">
                      <th className="px-6 py-3">Email</th>
                      <th className="px-3 py-3">AI Name</th>
                      <th className="px-3 py-3">Tier</th>
                      <th className="px-3 py-3">Trial</th>
                      <th className="px-3 py-3 text-right">Trades</th>
                      <th className="px-3 py-3 text-right">Exchanges</th>
                      <th className="px-3 py-3">Joined</th>
                    </tr>
                  </thead>
                  <tbody>
                    {loading ? (
                      <tr><td colSpan={7} className="px-6 py-12 text-center text-dark-500">Loading…</td></tr>
                    ) : users.length === 0 ? (
                      <tr><td colSpan={7} className="px-6 py-12 text-center text-dark-500">No users found</td></tr>
                    ) : (
                      users.map((u) => (
                        <tr
                          key={u.id}
                          onClick={() => openDetail(u.id)}
                          className={`cursor-pointer border-b border-dark-800/50 transition hover:bg-dark-800/50 ${detail?.id === u.id ? "bg-dark-800" : ""}`}
                        >
                          <td className="px-6 py-3 font-medium text-white">{u.email}</td>
                          <td className="px-3 py-3 text-dark-300">{u.ai_name}</td>
                          <td className="px-3 py-3">{tierBadge(u.subscription_tier)}</td>
                          <td className="px-3 py-3">{trialBadge(u.trial_status)}</td>
                          <td className="px-3 py-3 text-right text-dark-300">{u.trade_count}</td>
                          <td className="px-3 py-3 text-right text-dark-300">{u.exchange_count}</td>
                          <td className="px-3 py-3 text-dark-400">{fmt(u.created_at)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-4 border-t border-dark-800 px-6 py-3">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => p - 1)}
                    className="text-dark-400 hover:text-white disabled:opacity-30"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span className="text-xs text-dark-400">{page} / {totalPages}</span>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                    className="text-dark-400 hover:text-white disabled:opacity-30"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              )}
            </div>

            {/* Detail panel */}
            {detail && (
              <div className="w-1/2 overflow-y-auto" style={{ maxHeight: "calc(100vh - 57px)" }}>
                {detailLoading ? (
                  <div className="p-10 text-center text-dark-500">Loading…</div>
                ) : (
                  <div className="p-6">
                    {/* Close */}
                    <div className="mb-4 flex items-center justify-between">
                      <h2 className="text-base font-bold">{detail.email}</h2>
                      <button onClick={() => setDetail(null)} className="text-dark-400 hover:text-white">
                        <X size={16} />
                      </button>
                    </div>

                    {/* Info grid */}
                    <div className="mb-6 grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <span className="text-dark-500 block text-[11px] uppercase">AI Name</span>
                        <span className="text-white">{detail.ai_name}</span>
                      </div>
                      <div>
                        <span className="text-dark-500 block text-[11px] uppercase">Trades</span>
                        <span className="text-white">{detail.trade_count}</span>
                      </div>
                      <div>
                        <span className="text-dark-500 block text-[11px] uppercase">Trial Status</span>
                        {trialBadge(detail.trial_status)}
                      </div>
                      <div>
                        <span className="text-dark-500 block text-[11px] uppercase">Trial End</span>
                        <span className="text-dark-300">{fmt(detail.trial_end_date)}</span>
                      </div>
                      <div>
                        <span className="text-dark-500 block text-[11px] uppercase">Stripe Status</span>
                        <span className="text-dark-300">{detail.stripe_subscription_status || "—"}</span>
                      </div>
                      <div>
                        <span className="text-dark-500 block text-[11px] uppercase">Email Verified</span>
                        <span className={detail.email_verified ? "text-green-400" : "text-dark-500"}>
                          {detail.email_verified ? "Yes" : "No"}
                        </span>
                      </div>
                      <div>
                        <span className="text-dark-500 block text-[11px] uppercase">Joined</span>
                        <span className="text-dark-300">{fmt(detail.created_at)}</span>
                      </div>
                      <div>
                        <span className="text-dark-500 block text-[11px] uppercase">Last Login</span>
                        <span className="text-dark-300">{fmt(detail.last_login)}</span>
                      </div>
                    </div>

                    {/* Exchanges */}
                    <div className="mb-6">
                      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-dark-500">Exchanges ({detail.exchanges.length})</h3>
                      {detail.exchanges.length === 0 ? (
                        <p className="text-sm text-dark-500">None connected</p>
                      ) : (
                        <div className="space-y-2">
                          {detail.exchanges.map((e) => (
                            <div key={e.id} className="flex items-center justify-between rounded-lg border border-dark-800 bg-dark-900 px-4 py-2 text-sm">
                              <div>
                                <span className="font-medium text-white capitalize">{e.exchange}</span>
                                <span className="ml-2 text-xs text-dark-400">{e.account_label}</span>
                                {e.is_paper && <span className="ml-2 text-[10px] text-yellow-500 uppercase">Paper</span>}
                              </div>
                              <div className="flex items-center gap-3 text-xs text-dark-400">
                                {e.auto_trade_enabled && <span className="text-purple-400">Full Auto</span>}
                                {e.last_known_balance_usd != null && <span>${e.last_known_balance_usd.toLocaleString()}</span>}
                                <span className={e.is_active ? "text-green-400" : "text-red-400"}>
                                  {e.is_active ? "Active" : "Inactive"}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Channels */}
                    <div className="mb-6">
                      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-dark-500">Channels ({detail.channels.length})</h3>
                      {detail.channels.length === 0 ? (
                        <p className="text-sm text-dark-500">None linked</p>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          {detail.channels.map((c, i) => (
                            <span key={i} className="inline-flex items-center gap-1 rounded-full border border-dark-700 bg-dark-800 px-3 py-1 text-xs">
                              <span className="capitalize text-white">{c.platform}</span>
                              {c.external_username && <span className="text-dark-400">@{c.external_username}</span>}
                              {c.is_linked ? <Check size={10} className="text-green-400" /> : <X size={10} className="text-red-400" />}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Edit controls */}
                    <div className="rounded-xl border border-dark-700 bg-dark-900 p-5">
                      <h3 className="mb-4 text-xs font-bold uppercase tracking-wider text-dark-500">Override</h3>

                      <div className="mb-4">
                        <label className="mb-1 block text-xs text-dark-400">Subscription Tier</label>
                        <select
                          value={editTier}
                          onChange={(e) => setEditTier(e.target.value)}
                          className="w-full rounded-lg border border-dark-600 bg-dark-800 px-3 py-2 text-sm text-white outline-none focus:border-brand-500"
                        >
                          <option value="free">Free</option>
                          <option value="pro">Pro</option>
                          <option value="elite">Elite</option>
                        </select>
                      </div>

                      <div className="mb-5">
                        <label className="flex items-center gap-2 text-sm text-dark-300">
                          <input
                            type="checkbox"
                            checked={editPaused}
                            onChange={(e) => setEditPaused(e.target.checked)}
                            className="rounded border-dark-600"
                          />
                          Trading Paused
                        </label>
                      </div>

                      <div className="flex items-center gap-3">
                        <button
                          onClick={handleSave}
                          disabled={saving}
                          className="btn-primary px-5 py-2 text-sm font-semibold disabled:opacity-50"
                        >
                          {saving ? "Saving…" : "Save Changes"}
                        </button>
                        {saveMsg && (
                          <span className={`text-xs ${saveMsg === "Saved" ? "text-green-400" : "text-red-400"}`}>
                            {saveMsg}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Metrics tab ───────────────────────── */}
        {tab === "metrics" && (
          <div className="mx-auto max-w-5xl p-6">
            <div className="mb-6 flex items-center justify-between">
              <h2 className="text-lg font-bold">Dashboard Metrics</h2>
              <button onClick={fetchMetrics} className="text-dark-400 hover:text-white transition">
                <RefreshCw size={14} />
              </button>
            </div>

            {metricsLoading || !metrics ? (
              <div className="py-12 text-center text-dark-500">Loading…</div>
            ) : (
              <>
                {/* Top cards */}
                <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <MetricCard label="Total Users" value={metrics.total_users} />
                  <MetricCard label="Active Users" value={metrics.active_users} />
                  <MetricCard label="MRR" value={fmtMoney(metrics.mrr_cents)} accent />
                  <MetricCard label="Conversion Rate" value={`${metrics.conversion_rate}%`} />
                </div>

                {/* Tier breakdown */}
                <div className="mb-8">
                  <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-dark-500">Users by Tier</h3>
                  <div className="grid grid-cols-3 gap-4">
                    <TierCard tier="Free" count={metrics.free_users} total={metrics.active_users} color="dark-400" />
                    <TierCard tier="Pro" count={metrics.pro_users} total={metrics.active_users} color="brand-400" />
                    <TierCard tier="Elite" count={metrics.elite_users} total={metrics.active_users} color="purple-400" />
                  </div>
                </div>

                {/* Trial & trades */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="rounded-xl border border-dark-700 bg-dark-900 p-5">
                    <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-dark-500">Trials</h3>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between"><span className="text-dark-400">Active</span><span className="text-green-400">{metrics.active_trials}</span></div>
                      <div className="flex justify-between"><span className="text-dark-400">Expired</span><span className="text-red-400">{metrics.expired_trials}</span></div>
                      <div className="flex justify-between"><span className="text-dark-400">Converted</span><span className="text-brand-400">{metrics.converted_trials}</span></div>
                    </div>
                  </div>
                  <div className="rounded-xl border border-dark-700 bg-dark-900 p-5">
                    <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-dark-500">Trades</h3>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between"><span className="text-dark-400">Total</span><span className="text-white">{metrics.total_trades.toLocaleString()}</span></div>
                      <div className="flex justify-between"><span className="text-dark-400">This Month</span><span className="text-white">{metrics.trades_this_month.toLocaleString()}</span></div>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ── Tokens tab ────────────────────────── */}
        {tab === "tokens" && (
          <div className="mx-auto max-w-6xl p-6">
            <div className="mb-6 flex items-center justify-between">
              <h2 className="text-lg font-bold flex items-center gap-2">
                <Cpu size={18} /> Token Management
              </h2>
              <button
                onClick={fetchTokens}
                disabled={tokensLoading}
                className="flex items-center gap-1.5 rounded-lg bg-dark-800 px-3 py-1.5 text-xs font-medium text-dark-300 hover:text-white disabled:opacity-50"
              >
                <RefreshCw size={12} className={tokensLoading ? "animate-spin" : ""} />
                Refresh
              </button>
            </div>

            {!dashboard && tokensLoading && (
              <div className="py-12 text-center text-dark-400">Loading…</div>
            )}

            {dashboard && (
              <>
                {/* Budget gauge */}
                <div className="mb-6 rounded-xl border border-dark-800 bg-dark-900 p-5">
                  <div className="mb-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Gauge size={16} className="text-brand-400" />
                      <span className="text-sm font-semibold">Monthly Budget</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      {(["70", "85", "95"] as const).map((t) => (
                        <span
                          key={t}
                          className={`rounded-full px-2 py-0.5 font-bold ${
                            dashboard.budget.alerts[t]
                              ? t === "95"
                                ? "bg-red-500/20 text-red-400"
                                : t === "85"
                                ? "bg-orange-500/20 text-orange-400"
                                : "bg-yellow-500/20 text-yellow-400"
                              : "bg-dark-800 text-dark-500"
                          }`}
                        >
                          {dashboard.budget.alerts[t] ? "●" : "○"} {t}%
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="mb-2 flex items-end justify-between">
                    <div>
                      <div className="text-2xl font-bold">
                        {(dashboard.budget.pct_used * 100).toFixed(1)}%
                      </div>
                      <div className="text-xs text-dark-400">
                        {dashboard.budget.budget_used.toLocaleString()} /{" "}
                        {dashboard.budget.budget_total.toLocaleString()} tokens
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-xl font-bold text-brand-400">
                        ${dashboard.budget.cost_total_usd.toFixed(2)}
                      </div>
                      <div className="text-xs text-dark-400">spent this month</div>
                    </div>
                  </div>

                  <div className="h-3 w-full overflow-hidden rounded-full bg-dark-800">
                    <div
                      className={`h-full transition-all ${
                        dashboard.budget.pct_used >= 0.95
                          ? "bg-red-500"
                          : dashboard.budget.pct_used >= 0.85
                          ? "bg-orange-500"
                          : dashboard.budget.pct_used >= 0.70
                          ? "bg-yellow-500"
                          : "bg-brand-500"
                      }`}
                      style={{ width: `${Math.min(100, dashboard.budget.pct_used * 100)}%` }}
                    />
                  </div>
                </div>

                {/* Top agents + 24h stats */}
                <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
                  <div className="md:col-span-2 rounded-xl border border-dark-800 bg-dark-900 p-5">
                    <div className="mb-3 flex items-center gap-2">
                      <DollarSign size={16} className="text-brand-400" />
                      <span className="text-sm font-semibold">Top Agents by Cost (this month)</span>
                    </div>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs uppercase text-dark-500">
                          <th className="pb-2">Agent</th>
                          <th className="pb-2 text-right">Calls</th>
                          <th className="pb-2 text-right">Tokens</th>
                          <th className="pb-2 text-right">Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dashboard.agents_by_cost.length === 0 && (
                          <tr>
                            <td colSpan={4} className="py-4 text-center text-dark-500">
                              No calls yet this month
                            </td>
                          </tr>
                        )}
                        {dashboard.agents_by_cost.map((a) => (
                          <tr key={a.agent_name} className="border-t border-dark-800">
                            <td className="py-2 font-mono text-xs">{a.agent_name}</td>
                            <td className="py-2 text-right text-dark-300">{a.calls.toLocaleString()}</td>
                            <td className="py-2 text-right text-dark-300">{a.tokens.toLocaleString()}</td>
                            <td className="py-2 text-right font-bold text-brand-400">
                              ${a.cost_usd.toFixed(4)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="rounded-xl border border-dark-800 bg-dark-900 p-5">
                    <div className="mb-3 flex items-center gap-2">
                      <Activity size={16} className="text-brand-400" />
                      <span className="text-sm font-semibold">Last 24h</span>
                    </div>
                    <div className="space-y-3">
                      <div>
                        <div className="text-2xl font-bold">{dashboard.calls_last_24h.toLocaleString()}</div>
                        <div className="text-xs text-dark-400">API calls</div>
                      </div>
                      <div>
                        <div className="text-lg font-semibold text-dark-200">
                          {dashboard.budget.status}
                        </div>
                        <div className="text-xs text-dark-400">budget status</div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Rate limits */}
                <div className="mb-6 rounded-xl border border-dark-800 bg-dark-900 p-5">
                  <div className="mb-3 text-sm font-semibold">Rate Limits (per minute)</div>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs uppercase text-dark-500">
                        <th className="pb-2">Agent</th>
                        <th className="pb-2">Priority</th>
                        <th className="pb-2 text-right">Used</th>
                        <th className="pb-2 text-right">Limit</th>
                        <th className="pb-2">Usage</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rates.map((r) => {
                        const pct = r.tokens_per_minute
                          ? r.tokens_used_this_minute / r.tokens_per_minute
                          : 0;
                        const priorityColor =
                          r.priority === "p0"
                            ? "bg-red-500/20 text-red-400"
                            : r.priority === "p1"
                            ? "bg-yellow-500/20 text-yellow-400"
                            : "bg-green-500/20 text-green-400";
                        return (
                          <tr key={r.agent_name} className="border-t border-dark-800">
                            <td className="py-2 font-mono text-xs">{r.agent_name}</td>
                            <td className="py-2">
                              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${priorityColor}`}>
                                {r.priority}
                              </span>
                            </td>
                            <td className="py-2 text-right text-dark-300">
                              {r.tokens_used_this_minute.toLocaleString()}
                            </td>
                            <td className="py-2 text-right text-dark-300">
                              {r.tokens_per_minute.toLocaleString()}
                            </td>
                            <td className="py-2 w-32">
                              <div className="h-2 overflow-hidden rounded-full bg-dark-800">
                                <div
                                  className={`h-full ${pct >= 1 ? "bg-red-500" : pct >= 0.7 ? "bg-orange-500" : "bg-brand-500"}`}
                                  style={{ width: `${Math.min(100, pct * 100)}%` }}
                                />
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* 7-day chart */}
                <div className="rounded-xl border border-dark-800 bg-dark-900 p-5">
                  <div className="mb-3 flex items-center gap-2">
                    <TrendingUp size={16} className="text-brand-400" />
                    <span className="text-sm font-semibold">Daily Consumption (last 7 days)</span>
                  </div>
                  {consumption.length === 0 ? (
                    <div className="py-8 text-center text-dark-500 text-sm">No data yet</div>
                  ) : (
                    <TokenConsumptionChart points={consumption} />
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </>
  );
}

// ─────────────────────────────────────────────
// Token consumption chart (inline SVG, zero deps)
// ─────────────────────────────────────────────

function TokenConsumptionChart({ points }: { points: ConsumptionPoint[] }) {
  const byDay = new Map<string, number>();
  for (const p of points) {
    const d = p.day.slice(0, 10);
    byDay.set(d, (byDay.get(d) || 0) + p.tokens_in + p.tokens_out);
  }
  const sorted = Array.from(byDay.entries()).sort(([a], [b]) => a.localeCompare(b));
  const maxVal = Math.max(1, ...sorted.map(([, v]) => v));

  const W = 600;
  const H = 160;
  const PAD = 30;
  const barW = sorted.length > 0 ? (W - 2 * PAD) / sorted.length - 6 : 0;

  return (
    <svg viewBox={`0 0 ${W} ${H + 30}`} className="w-full h-40">
      {sorted.map(([day, val], i) => {
        const h = (val / maxVal) * (H - 2 * PAD);
        const x = PAD + i * ((W - 2 * PAD) / sorted.length);
        const y = H - PAD - h;
        return (
          <g key={day}>
            <rect
              x={x}
              y={y}
              width={barW}
              height={h}
              fill="rgb(56, 189, 248)"
              className="opacity-80 hover:opacity-100"
            >
              <title>{`${day}: ${val.toLocaleString()} tokens`}</title>
            </rect>
            <text
              x={x + barW / 2}
              y={H - PAD + 14}
              textAnchor="middle"
              fontSize="9"
              fill="rgb(148, 163, 184)"
            >
              {day.slice(5)}
            </text>
            <text
              x={x + barW / 2}
              y={y - 3}
              textAnchor="middle"
              fontSize="9"
              fill="rgb(203, 213, 225)"
            >
              {(val / 1000).toFixed(0)}k
            </text>
          </g>
        );
      })}
      <line
        x1={PAD}
        y1={H - PAD}
        x2={W - PAD}
        y2={H - PAD}
        stroke="rgb(51, 65, 85)"
        strokeWidth={1}
      />
    </svg>
  );
}

// ─────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────

function MetricCard({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div className="rounded-xl border border-dark-700 bg-dark-900 p-5">
      <p className="text-[11px] font-bold uppercase tracking-wider text-dark-500">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${accent ? "text-brand-400" : "text-white"}`}>{value}</p>
    </div>
  );
}

function TierCard({ tier, count, total, color }: { tier: string; count: number; total: number; color: string }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="rounded-xl border border-dark-700 bg-dark-900 p-5">
      <div className="flex items-center justify-between mb-2">
        <span className={`text-sm font-bold text-${color}`}>{tier}</span>
        <span className="text-xs text-dark-500">{pct}%</span>
      </div>
      <p className="text-2xl font-bold text-white">{count}</p>
      <div className="mt-2 h-1.5 rounded-full bg-dark-800 overflow-hidden">
        <div className={`h-full rounded-full bg-${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
