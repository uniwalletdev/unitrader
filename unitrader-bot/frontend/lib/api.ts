import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
    // Skip auth-flow endpoints — the page handles 401 itself for these
    const isAuthEndpoint =
      url.includes("/clerk-sync") ||
      url.includes("/clerk-setup") ||
      url.includes("/api/auth/me");  // "me" is called during silent token check
    if (err.response?.status === 401 && typeof window !== "undefined" && !isAuthEndpoint) {
      localStorage.removeItem("access_token");
      window.location.href = "/login";
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
  }>) => api.patch("/api/auth/settings", data),
  acceptRiskDisclosure: () => api.post("/api/onboarding/accept-risk-disclosure", {}),
};

// ── Trading ──────────────────────────────────────────────────────────────────
export const tradingApi = {
  openPositions: () => api.get("/api/trading/open-positions"),
  history: (params?: object) => api.get("/api/trading/history", { params }),
  performance: (params?: { symbol?: string; market_condition?: string }) =>
    api.get("/api/trading/performance", { params }),
  riskAnalysis: () => api.get("/api/trading/risk-analysis"),
  execute: (symbol: string, exchange: string) =>
    api.post("/api/trading/execute", { symbol, exchange }, { timeout: 90000 }),
  closePosition: (trade_id: string) =>
    api.post("/api/trading/close-position", { trade_id }),
  submitFeedback: (trade_id: string, payload: { rating: 1 | -1; comment: string | null; is_paper: boolean }) =>
    api.post(`/api/trades/${trade_id}/feedback`, payload),
};

// ── Exchange Keys ────────────────────────────────────────────────────────────

export interface ConnectedExchange {
  exchange: string;
  connected_at: string | null;
  is_paper: boolean;
  last_used: string | null;
}

export interface ConnectExchangeResponse {
  exchange: string;
  connected_at: string;
  is_paper: boolean;
  balance_usd: number;
  message: string;
}

export interface AccountBalance {
  exchange: string;
  is_paper: boolean;
  connected_at: string | null;
  last_used: string | null;
  balance: number | null;
  currency: string;
  error: string | null;
}

export const exchangeApi = {
  list: () => api.get<{ status: string; data: ConnectedExchange[] }>("/api/trading/exchange-keys"),

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

  disconnect: (exchange: string) =>
    api.delete<{ status: string; data: { exchange: string; message: string } }>(
      `/api/trading/exchange-keys/${exchange}`
    ),
};

// ── Chat ─────────────────────────────────────────────────────────────────────
export const chatApi = {
  sendMessage: (message: string) => api.post("/api/chat/message", { message }, { timeout: 60000 }),
  history: (limit = 50) => api.get("/api/chat/history", { params: { limit } }),
};

// ── Billing ──────────────────────────────────────────────────────────────────
export const billingApi = {
  plans: () => api.get("/api/billing/plans"),
  status: () => api.get("/api/billing/status"),
  checkout: () => api.post("/api/billing/checkout"),
  /** Dedicated endpoint used by the trial choice modal. */
  checkoutSession: () => api.post("/api/billing/checkout-session"),
  portal: () => api.post("/api/billing/portal"),
};

// ── Trial ────────────────────────────────────────────────────────────────────
export const trialApi = {
  status: () => api.get("/api/trial/status"),
  choiceOptions: () => api.get("/api/trial/choice-options"),
  makeChoice: (choice: "pro" | "free" | "cancel") =>
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
  getOpenPositions: () =>
    api.get<{ status: string; data: { positions: BackendTrade[]; count: number } }>(
      "/api/trading/open-positions",
    ),

  getTradeHistory: (params?: {
    symbol?: string;
    from_date?: string;
    to_date?: string;
    outcome?: "profit" | "loss";
    limit?: number;
    offset?: number;
  }) =>
    api.get<{
      status: string;
      data: { trades: BackendTrade[]; total: number; limit: number; offset: number };
    }>("/api/trading/history", { params }),

  getPerformance: (params?: { symbol?: string; market_condition?: string }) =>
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

