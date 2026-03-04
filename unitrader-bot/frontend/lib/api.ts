import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_URL,
  headers: { "Content-Type": "application/json" },
});

// Attach JWT token from localStorage on every request
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-redirect to login on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && typeof window !== "undefined") {
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
};

// ── Trading ──────────────────────────────────────────────────────────────────
export const tradingApi = {
  openPositions: () => api.get("/api/trading/open-positions"),
  history: (params?: object) => api.get("/api/trading/history", { params }),
  performance: () => api.get("/api/trading/performance"),
  riskAnalysis: () => api.get("/api/trading/risk-analysis"),
  execute: (symbol: string, exchange: string) =>
    api.post("/api/trading/execute", { symbol, exchange }),
  closePosition: (trade_id: string) =>
    api.post("/api/trading/close-position", { trade_id }),
};

// ── Exchange Keys ────────────────────────────────────────────────────────────
export const exchangeApi = {
  list: () => api.get("/api/trading/exchange-keys"),
  connect: (exchange: string, api_key: string, api_secret: string) =>
    api.post("/api/trading/exchange-keys", { exchange, api_key, api_secret }),
  disconnect: (exchange: string) =>
    api.delete(`/api/trading/exchange-keys/${exchange}`),
};

// ── Chat ─────────────────────────────────────────────────────────────────────
export const chatApi = {
  sendMessage: (message: string) => api.post("/api/chat/message", { message }),
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
