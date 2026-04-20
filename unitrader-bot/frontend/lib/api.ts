import axios, { type InternalAxiosRequestConfig } from "axios";

import { devLogError } from "./devLog";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Clerk → /api/auth/clerk-sync refresh; registered by ApiAuthBridge (browser only). */
let jwtRefreshHandler: (() => Promise<void>) | null = null;

export function setApiTokenRefreshHandler(fn: (() => Promise<void>) | null): void {
  jwtRefreshHandler = fn;
}

export const api = axios.create({
  baseURL: API_URL,
  headers: { "Content-Type": "application/json" },
  timeout: 8000, // 8 seconds — prevents UI hangs on slow/cold Railway starts
});

// Attach JWT token from localStorage on every request
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-redirect to login on 401 (skip auth endpoints to avoid redirect loops)
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const url = err.config?.url || "";
    const detail = err.response?.data?.detail;
    const code =
      typeof detail === "object" && detail !== null && "code" in detail
        ? (detail as { code?: string }).code
        : null;

    // Skip auth-flow endpoints — the page handles 401 itself for these
    const isAuthEndpoint =
      url.includes("/clerk-sync") ||
      url.includes("/clerk-setup") ||
      url.includes("/api/auth/me");  // "me" is called during silent token check
    // IMPORTANT: Don't redirect from App Router pages. They use Clerk session cookies
    // and can be valid even when our legacy localStorage JWT is missing/expired.
    // Redirecting here causes login <-> trade loops.
    const isAppRouterPath =
      typeof window !== "undefined" &&
      (window.location.pathname === "/trade" ||
        window.location.pathname.startsWith("/trade/") ||
        window.location.pathname.startsWith("/learning") ||
        window.location.pathname.startsWith("/positions") ||
        window.location.pathname.startsWith("/performance"));

    if (err.response?.status === 401 && code === "TOKEN_EXPIRED" && typeof window !== "undefined") {
      if (url.includes("/clerk-sync")) {
        localStorage.removeItem("access_token");
        return Promise.reject(err);
      }
      const cfg = err.config as (InternalAxiosRequestConfig & { __jwtRetry?: boolean }) | undefined;
      if (cfg?.__jwtRetry) {
        localStorage.removeItem("access_token");
        if (!isAuthEndpoint && !isAppRouterPath) {
          window.location.href = "/login?expired=1";
        }
        return Promise.reject(err);
      }
      if (jwtRefreshHandler && cfg && !isAuthEndpoint) {
        return jwtRefreshHandler()
          .then(() => {
            const token = localStorage.getItem("access_token");
            const next: InternalAxiosRequestConfig & { __jwtRetry?: boolean } = {
              ...cfg,
              __jwtRetry: true,
            };
            if (token) {
              next.headers = next.headers ?? {};
              next.headers.Authorization = `Bearer ${token}`;
            }
            return api.request(next);
          })
          .catch(() => {
            localStorage.removeItem("access_token");
            if (!isAuthEndpoint && !isAppRouterPath) {
              window.location.href = "/login?expired=1";
            }
            return Promise.reject(err);
          });
      }
      localStorage.removeItem("access_token");
      if (!isAuthEndpoint && !isAppRouterPath) {
        window.location.href = "/login?expired=1";
      }
      return Promise.reject(err);
    }

    if (
      err.response?.status === 401 &&
      typeof window !== "undefined" &&
      !isAuthEndpoint &&
      !isAppRouterPath
    ) {
      localStorage.removeItem("access_token");
      window.location.href = "/login";
    }
    if (err.response && err.response.status >= 500) {
      devLogError("API 5xx", {
        status: err.response.status,
        url: err.config?.url,
        data: err.response.data,
      });
    }
    return Promise.reject(err);
  }
);

// ── Auth ─────────────────────────────────────────────────────────────────────
export const authApi = {
  register: (data: { email: string; password: string; ai_name: string }) =>
    api.post("/api/auth/register", data),
  login: (email: string, password: string) =>
    api.post("/api/auth/login", { email, password }),
  me: () => api.get("/api/auth/me"),
  clerkSync: (clerk_token: string) =>
    api.post("/api/auth/clerk-sync", { clerk_token }),
  clerkSetup: (user_id: string, ai_name: string) =>
    api.post("/api/auth/clerk-setup", { user_id, ai_name }),
  setup2FA: () => api.post("/api/auth/2fa/setup"),
  verify2FA: (code: string) => api.post("/api/auth/2fa/verify", { code }),
  telegramCode: () => api.post("/api/auth/telegram/linking-code"),
  whatsappCode: () => api.post("/api/auth/whatsapp/linking-code"),
  externalAccounts: () => api.get("/api/auth/external-accounts"),
  unlinkAccount: (platform: string) =>
    api.post("/api/auth/unlink-external-account", { platform }),
  getSettings: () => api.get("/api/auth/settings"),
  updateSettings: (data: Partial<{
    explanation_level?: string;
    trade_mode?: string;
    max_trade_amount?: number;
    max_daily_loss?: number;
    max_position_size?: number;
    trading_paused?: boolean;
    leaderboard_opt_out?: boolean;
    approved_assets?: string[];
    first_trade_done?: boolean;
    push_token?: string;
    onboarding_complete?: boolean;
    financial_goal?: string;
    risk_level_setting?: string;
    execution_mode?: string;
    watchlist?: string[];
    auto_trade_enabled?: boolean;
    auto_trade_threshold?: number;
    signal_notify_min_confidence?: number;
    auto_trade_max_per_scan?: number;
    guided_confidence_threshold?: number;
    apex_selects_max_trades?: number;
    apex_selects_asset_classes?: string[];
    autonomous_mode_unlocked?: boolean;
    autonomous_unlocked_at?: string | null;
    morning_briefing_enabled?: boolean;
    morning_briefing_time?: string;
    daily_digest_enabled?: boolean;
    preferred_trading_account_id?: string | null;
  }>) => api.patch("/api/auth/settings", data),
  acceptRiskDisclosure: () => api.post("/api/onboarding/accept-risk-disclosure", {}),
  completeWizard: (data?: {
    goal?: string;
    risk_level?: string;
    budget?: number;
    exchange?: string;
    trader_class?: string;
  }) => api.post("/api/onboarding/complete-wizard", data ?? {}),
  skipOnboarding: () => api.post("/api/onboarding/skip", {}),
  advanceTrustLadder: () => api.post("/api/onboarding/trust-ladder/advance", {}),
  trustLadderStatus: () => api.get("/api/onboarding/trust-ladder/status"),
  unlockAutonomous: () => api.post("/api/onboarding/unlock-autonomous", {}),
  botInfo: () => api.get("/health/bot-info"),
  claim: (claim_token: string, clerk_token: string) =>
    api.post("/api/auth/claim", { claim_token, clerk_token }),
};

// ── Trading ──────────────────────────────────────────────────────────────────
export const tradingApi = {
  openPositions: (params?: { trading_account_id?: string; exchange?: string; is_paper?: boolean }) =>
    api.get("/api/trading/open-positions", { params }),
  history: (params?: object) => api.get("/api/trading/history", { params }),
  performance: (params?: { symbol?: string; market_condition?: string; trading_account_id?: string; exchange?: string; is_paper?: boolean }) =>
    api.get("/api/trading/performance", { params }),
  riskAnalysis: () => api.get("/api/trading/risk-analysis"),
  /** Pure analysis — returns signal/confidence/explanations. No order placed. */
  analyze: (
    symbol: string,
    exchange: string,
    trader_class?: string,
    opts?: { trading_account_id?: string; is_paper?: boolean },
  ) =>
    api.post(
      "/api/trading/analyze",
      { symbol, exchange, trader_class, ...(opts ?? {}) },
      { timeout: 90000 },
    ),
  /** Full cycle — analyse + place real/paper order on exchange. */
  execute: (symbol: string, exchange: string, opts?: { trading_account_id?: string; is_paper?: boolean }) =>
    api.post("/api/trading/execute", { symbol, exchange, ...opts }, { timeout: 90000 }),
  closePosition: (trade_id: string) =>
    api.post("/api/trading/close-position", { trade_id }),
  submitFeedback: (trade_id: string, payload: { rating: 1 | -1; comment: string | null; is_paper: boolean }) =>
    api.post(`/api/trades/${trade_id}/feedback`, payload),
  /** Initialisation context for the AI Trader page — DB only, fast. */
  userContext: (params?: { asset_class?: string }) =>
    api.get("/api/trading/user-context", { params }),
};

// ── Exchange Keys ────────────────────────────────────────────────────────────

export interface ConnectedExchange {
  trading_account_id?: string | null;
  exchange: string;
  account_label?: string | null;
  connected_at: string | null;
  is_paper: boolean;
  last_used: string | null;
}

export interface ConnectExchangeResponse {
  exchange: string;
  trading_account_id?: string | null;
  account_label?: string | null;
  connected_at: string;
  is_paper: boolean;
  balance_usd: number;
  message: string;
}

export interface AccountBalance {
  trading_account_id?: string | null;
  exchange: string;
  account_label?: string | null;
  is_paper: boolean;
  connected_at: string | null;
  last_used: string | null;
  balance: number | null;
  balance_note?: string | null;
  currency: string;
  error: string | null;
}

export const exchangeApi = {
  list: (opts?: { timeout?: number }) =>
    api.get<{ status: string; data: ConnectedExchange[] }>("/api/trading/exchange-keys", {
      ...(opts?.timeout != null ? { timeout: opts.timeout } : {}),
    }),

  balances: () =>
    api.get<{ status: string; data: AccountBalance[] }>("/api/trading/account-balances", { timeout: 30000 }),

  testConnection: (exchange: string) =>
    api.get<{
      success: boolean;
      exchange?: string;
      account_id?: string;
      buying_power?: number;
      currency?: string;
      message?: string;
      error?: string;
    }>(`/api/exchanges/test-connection`, { params: { exchange } }),

  connect: (exchange: string, apiKey: string, secretKey: string, isPaper: boolean = true) =>
    api.post<{ status: string; data: ConnectExchangeResponse }>("/api/trading/exchange-keys", {
      exchange,
      api_key: apiKey,
      api_secret: secretKey,
      is_paper: isPaper,
    }),

  disconnect: (exchange: string, opts?: { trading_account_id?: string; is_paper?: boolean }) =>
    api.delete<{ status: string; data: { exchange: string; message: string } }>(
      `/api/trading/exchange-keys/${exchange}`,
      { params: opts }
    ),
};

// ── Chat ─────────────────────────────────────────────────────────────────────
export const chatApi = {
  sendMessage: (message: string) => api.post("/api/chat/message", { message }, { timeout: 60000 }),
  history: (limit = 50) => api.get("/api/chat/history", { params: { limit } }),
  bootstrap: () => api.get("/api/chat/bootstrap"),
};

// ── Billing ──────────────────────────────────────────────────────────────────
export const billingApi = {
  plans: () => api.get("/api/billing/plans"),
  status: () => api.get("/api/billing/status"),
  checkout: (plan: string = "pro") => api.post(`/api/billing/checkout?plan=${plan}`),
  /** Dedicated endpoint used by the trial choice modal. */
  checkoutSession: (plan: string = "pro") => api.post(`/api/billing/checkout-session?plan=${plan}`),
  portal: () => api.post("/api/billing/portal"),
};

// ── Trial ────────────────────────────────────────────────────────────────────
export const trialApi = {
  status: () => api.get("/api/trial/status"),
  choiceOptions: () => api.get("/api/trial/choice-options"),
  makeChoice: (choice: "pro" | "elite" | "free" | "cancel") =>
    api.post("/api/trial/make-choice", { choice }),
};

// ── Content ──────────────────────────────────────────────────────────────────
export const contentApi = {
  topics: () => api.get("/api/content/topics"),
  blogPosts: () => api.get("/api/content/blog-posts"),
  blogPost: (slug: string) => api.get(`/api/content/blog-posts/${slug}`),
  generateBlog: (topic: string) =>
    api.post("/api/content/generate-blog", { topic }),
  publishBlog: (postId: string) =>
    api.post(`/api/content/blog-posts/${postId}/publish`),
  socialCalendar: () => api.get("/api/content/social-calendar"),
  generateSocial: (topic?: string) =>
    api.post("/api/content/generate-social", { topic }),
  socialPosts: () => api.get("/api/content/social-posts"),
};

// ── Signals ──────────────────────────────────────────────────────────────────
export const signalApi = {
  stack: (opts?: { trading_account_id?: string | null }) =>
    api.get("/api/signals/stack", { params: { trading_account_id: opts?.trading_account_id ?? undefined } }),
  interact: (signalId: string, action: string, tradeId?: string | null) =>
    api.post(`/api/signals/${signalId}/interact`, { action, trade_id: tradeId ?? null }),
  updateSettings: (data: { execution_mode?: string; watchlist?: string[]; auto_trade_enabled?: boolean; auto_trade_threshold?: number; auto_trade_max_per_scan?: number; guided_confidence_threshold?: number; apex_selects_max_trades?: number; apex_selects_asset_classes?: string[]; morning_briefing_enabled?: boolean; morning_briefing_time?: string; daily_digest_enabled?: boolean }) =>
    api.patch("/api/signals/settings", data),
  accountSettings: (trading_account_id: string) =>
    api.get("/api/signals/account-settings", { params: { trading_account_id } }),
  updateAccountSettings: (data: { trading_account_id: string; watchlist?: string[]; auto_trade_enabled?: boolean; auto_trade_threshold?: number; auto_trade_max_per_scan?: number }) =>
    api.patch("/api/signals/account-settings", data),
  apexSelects: () => api.get("/api/signals/apex-selects"),
  approveApexSelects: (token: string) => api.post(`/api/signals/apex-selects/approve/${token}`),
};

// ── Notifications ─────────────────────────────────────────────────────────────
export const notificationApi = {
  list: (limit = 20, opts?: { type?: string }) =>
    api.get("/api/notifications", { params: { limit, ...(opts?.type ? { type: opts.type } : {}) } }),
  markRead: (id: string) => api.post(`/api/notifications/${id}/read`),
  markAllRead: () => api.post("/api/notifications/read-all"),
  settings: () => api.get("/api/notifications/settings"),
  updateSettings: (data: { telegram_notifications_enabled?: boolean; whatsapp_notifications_enabled?: boolean }) =>
    api.patch("/api/notifications/settings", data),
  undoTrade: (token: string) => api.post(`/api/trading/undo/${token}`),
};

// ── Learning ─────────────────────────────────────────────────────────────────
export const learningApi = {
  patterns: () => api.get("/api/learning/patterns"),
  instructions: (agent: string) =>
    api.get(`/api/learning/instructions/${agent}`),
  outputs: () => api.get("/api/learning/outputs"),
  insights: (type: string) => api.get(`/api/learning/insights/${type}`),
  dashboard: () => api.get("/api/learning/dashboard"),
  trigger: () => api.post("/api/learning/trigger"),
};

// ── Trading (typed, matches backend routers/trading.py) ────────────────────────
// Endpoints: execute, open-positions, history, performance, close-position, risk-analysis, exchange-keys

export const tradingAPI = {
  getOpenPositions: (params?: { trading_account_id?: string; exchange?: string; is_paper?: boolean }) =>
    api.get<{ status: string; data: { positions: BackendTrade[]; count: number } }>(
      "/api/trading/open-positions",
      { params }
    ),

  getTradeHistory: (params?: {
    symbol?: string;
    from_date?: string;
    to_date?: string;
    outcome?: "profit" | "loss";
    trading_account_id?: string;
    exchange?: string;
    is_paper?: boolean;
    limit?: number;
    offset?: number;
  }) =>
    api.get<{
      status: string;
      data: { trades: BackendTrade[]; total: number; limit: number; offset: number };
    }>("/api/trading/history", { params }),

  getPerformance: (params?: { symbol?: string; market_condition?: string; trading_account_id?: string; exchange?: string; is_paper?: boolean }) =>
    api.get<{
      status: string;
      data: PerformanceData;
    }>("/api/trading/performance", { params }),

  closePosition: (tradeId: string) =>
    api.post("/api/trading/close-position", { trade_id: tradeId }),
};

/** Backend trade shape from routers/trading._trade_to_dict */
export interface BackendTrade {
  id: string;
  trading_account_id?: string | null;
  exchange?: string | null;
  is_paper?: boolean | null;
  account_scope?: string | null;
  account_label?: string | null;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  stop_loss: number;
  take_profit: number;
  profit: number | null;
  loss: number | null;
  profit_percent: number | null;
  status: string;
  claude_confidence: number | null;
  market_condition: string | null;
  execution_time_ms: number | null;
  created_at: string | null;
  closed_at: string | null;
}

/** Backend performance response data */
export interface PerformanceData {
  message?: string;
  total_trades?: number;
  wins?: number;
  losses?: number;
  win_rate_pct?: number;
  total_profit_usd?: number;
  total_loss_usd?: number;
  net_pnl_usd?: number;
  avg_profit_pct?: number;
  avg_loss_pct?: number;
  best_trade?: BackendTrade;
  worst_trade?: BackendTrade;
}

// ── Admin ────────────────────────────────────────────────────────────────────
const adminHeaders = () => {
  const secret = typeof window !== "undefined" ? localStorage.getItem("admin_secret") : "";
  const author = typeof window !== "undefined" ? localStorage.getItem("admin_author") || "" : "";
  const h: Record<string, string> = { "X-Admin-Secret": secret || "" };
  if (author) h["X-Admin-Author"] = author;
  return h;
};

export const adminApi = {
  users: (params?: { page?: number; page_size?: number; search?: string; tier?: string }) =>
    api.get("/api/admin/users", { params, headers: adminHeaders() }),
  userDetail: (userId: string) =>
    api.get(`/api/admin/users/${userId}`, { headers: adminHeaders() }),
  updateUser: (userId: string, data: { subscription_tier?: string; trial_status?: string; trial_end_date?: string; trading_paused?: boolean; is_active?: boolean }) =>
    api.patch(`/api/admin/users/${userId}`, data, { headers: adminHeaders() }),
  deleteUser: (userId: string) =>
    api.delete(`/api/admin/users/${userId}`, { headers: adminHeaders() }),
  metrics: () =>
    api.get("/api/admin/metrics", { headers: adminHeaders() }),
  // ── Phase 13 backoffice ops ──
  panicStop: (userId: string, reason: string) =>
    api.post(`/api/admin/users/${userId}/panic-stop`, { reason }, { headers: adminHeaders() }),
  revokeExchangeKey: (userId: string, keyId: string, reason: string) =>
    api.post(
      `/api/admin/users/${userId}/exchange-keys/${keyId}/revoke`,
      { reason },
      { headers: adminHeaders() },
    ),
  listNotes: (userId: string) =>
    api.get(`/api/admin/users/${userId}/notes`, { headers: adminHeaders() }),
  addNote: (userId: string, body: string) =>
    api.post(`/api/admin/users/${userId}/notes`, { body }, { headers: adminHeaders() }),
};

// ── Token Management (admin) ─────────────────────────────────────────────────
export const tokenApi = {
  dashboard: () =>
    api.get("/api/token/dashboard", { headers: adminHeaders() }),
  budget: () =>
    api.get("/api/token/budget", { headers: adminHeaders() }),
  consumption: (agent?: string, days: number = 7) =>
    api.get("/api/token/consumption", {
      params: { agent, days },
      headers: adminHeaders(),
    }),
  rates: () =>
    api.get("/api/token/rates", { headers: adminHeaders() }),
};

// ── Data Governance (admin, Phase 12) ────────────────────────────────────────
export const governanceApi = {
  dashboard: () =>
    api.get("/api/governance/dashboard", { headers: adminHeaders() }),
  latest: () =>
    api.get("/api/governance/latest", { headers: adminHeaders() }),
  snapshots: (days: number = 30) =>
    api.get("/api/governance/snapshots", { params: { days }, headers: adminHeaders() }),
  approvals: (status?: string) =>
    api.get("/api/governance/approvals", {
      params: status ? { status } : {},
      headers: adminHeaders(),
    }),
  approve: (id: string) =>
    api.post(`/api/governance/approvals/${id}/approve`, {}, { headers: adminHeaders() }),
  deny: (id: string, reason?: string) =>
    api.post(`/api/governance/approvals/${id}/deny`, { reason }, { headers: adminHeaders() }),
  egress: (days: number = 7) =>
    api.get("/api/governance/egress", { params: { days }, headers: adminHeaders() }),
  allowlist: () =>
    api.get("/api/governance/allowlist", { headers: adminHeaders() }),
};

