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

  /** Exchange a Clerk session token for our internal JWT. */
  clerkSync: (clerk_token: string) =>
    api.post("/api/auth/clerk-sync", { clerk_token }),

  /** Set AI name for a new Clerk user (called after clerkSync returns needs_setup). */
  clerkSetup: (user_id: string, ai_name: string) =>
    api.post("/api/auth/clerk-setup", { user_id, ai_name }),
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
