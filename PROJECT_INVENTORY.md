# Unitrader — Project inventory (for review with project overview)

Use this list to cross-check with your project overview on Claude. It lists what exists in the repo as of the last review.

---

## 1. Backend — Core

| Item | Path | Purpose |
|------|------|--------|
| FastAPI app | `unitrader-bot/main.py` | Entry point, CORS, rate limit, security headers, lifespan, router includes |
| Config | `unitrader-bot/config.py` | Pydantic settings from env (DB, JWT, Stripe, exchanges, Clerk, etc.) |
| Database | `unitrader-bot/database.py` | Async SQLAlchemy engine, session, `create_tables` |
| Models | `unitrader-bot/models.py` | All ORM models (see §4) |
| Schemas | `unitrader-bot/schemas.py` | Pydantic request/response schemas |
| Security | `unitrader-bot/security.py` | Passwords (bcrypt), JWT, Fernet encryption, 2FA (TOTP) |

---

## 2. Backend — Routers (API surface)

All under prefix `/api/<domain>` unless noted.

### Auth — `routers/auth.py` (prefix `/api/auth`)

- `POST /register` — Create user + default settings
- `POST /verify-email` — Email verification
- `POST /login` — Login, returns access + refresh tokens
- `POST /logout` — Revoke refresh token
- `POST /refresh-token` — New access token from refresh
- `POST /2fa/setup` — Init TOTP 2FA
- `POST /2fa/verify` — Verify 2FA code
- `POST /password-reset-request` — Send reset email
- `POST /password-reset` — Set new password with token
- `GET /me` — Current user (JWT)
- `POST /clerk-sync` — Sync Clerk session → JWT (frontend)
- `POST /clerk-setup` — Post-onboarding setup (AI name, etc.)
- `POST /telegram/linking-code` — Generate Telegram link code
- `POST /telegram/link-account` — Link Telegram to user
- `POST /telegram/webhook` — Telegram bot webhook (may live under `/webhooks/telegram`)
- `GET /external-accounts` — List linked Telegram/WhatsApp
- `POST /unlink-external-account` — Unlink a platform
- `POST /whatsapp/linking-code` — WhatsApp link code
- `POST /whatsapp/link-account` — Link WhatsApp
- `POST /whatsapp/webhook` — WhatsApp webhook

### Trading — `routers/trading.py` (prefix `/api/trading`)

- `POST /execute` — Run analysis + execute trade (symbol + exchange); free tier 10 trades/month; no symbol restriction (all products per exchange)
- `GET /open-positions` — Open positions for user
- `GET /history` — Closed trades (symbol, from_date, to_date, outcome, limit, offset)
- `GET /performance` — Aggregated stats (optional symbol, market_condition)
- `POST /close-position` — Manual close (body: `trade_id`)
- `GET /risk-analysis` — Daily loss, remaining budget, loss limit status
- `POST /exchange-keys` — Save/validate encrypted exchange API keys (connect exchange)
- `GET /exchange-keys` — List connected exchanges (no secrets)
- `DELETE /exchange-keys/{exchange}` — Disconnect exchange

### Chat — `routers/chat.py` (prefix `/api/chat`)

- `POST /message` — Send message, get AI response (context-aware)
- `GET /history` — Conversation history
- `GET /sentiment` — Sentiment for recent messages
- `POST /rate` — Rate response (helpful/not)
- `DELETE /history` — Clear history

### Content — `routers/content.py` (prefix `/api/content`)

- `GET /topics` — Blog topics
- `GET /blog-posts` — List blog posts
- `GET /blog-posts/{slug}` — Single post
- `POST /generate-blog` — Generate blog (topic)
- `POST /blog-posts/{post_id}/publish` — Publish post
- `GET /social-calendar` — Social calendar
- `POST /generate-social` — Generate social posts (optional topic)
- `GET /social-posts` — List social posts

### Billing — `routers/billing.py` (prefix `/api/billing`)

- `GET /plans` — Available plans
- `GET /status` — Current subscription status
- `POST /checkout` — Start Stripe Checkout
- `POST /checkout-session` — Checkout session (e.g. trial choice)
- `POST /portal` — Stripe Customer Portal URL
- `POST /webhook` — Stripe webhook (subscription events)

### Trial — `routers/trial.py` (prefix `/api/trial`)

- `GET /status` — Trial status (days left, performance)
- `GET /choice-options` — Pro/Free/Cancel options
- `POST /make-choice` — User choice after trial (pro / free / cancel)

### Learning — `routers/learning.py` (prefix `/api/learning`)

- `GET /patterns` — Trading patterns
- `GET /instructions/{agent_name}` — Agent instructions
- `GET /outputs` — Agent outputs
- `GET /insights/{type}` — Insights by type
- `GET /dashboard` — Learning dashboard data
- `POST /trigger` — Trigger learning run

### Health — `routers/health.py`

- `GET /health` — Liveness
- `GET /health/database` — DB connectivity
- `GET /health/ai` — Anthropic API
- `GET /health/email` — Resend
- `GET /health/payment` — Stripe
- `GET /health/orchestrator` — Orchestrator/agent performance

### Other routers (webhooks / linking)

- Telegram webhooks + linking (e.g. under `/webhooks/telegram` or auth)
- WhatsApp webhooks + linking

---

## 3. Backend — Agents & orchestration

| Item | Path | Purpose |
|------|------|--------|
| Master orchestrator | `src/agents/orchestrator.py` | Routes TRADE_SIGNAL, USER_QUESTION, CONTENT_CREATE, etc.; trade workflow (shared memory → market analysis → decide → execute/skip) |
| Trading agent | `src/agents/core/trading_agent.py` | `analyze_market`, `decide_with_context`, `execute_trade`, `run_cycle`; Claude decisions; symbol normalisation before execution; returns `None` on routing/market failure |
| Conversation agent | `src/agents/core/conversation_agent.py` | Multi-context chat, sentiment, context detection |
| Content writer | `src/agents/marketing/content_writer.py` | Blog generation |
| Social media | `src/agents/marketing/social_media.py` | Social post generation |
| Shared memory | `src/agents/memory/shared_memory.py` | Context/outcomes for trading decisions |

---

## 4. Backend — Integrations & services

### Market data & symbol routing — `src/integrations/market_data.py`

- **Constants:** `EXCHANGE_CAPABILITIES`, `CRYPTO_SYMBOLS`, `FOREX_PAIRS`
- **Helpers:** `classify_asset(symbol)`, `normalise_symbol(symbol, exchange)`, `validate_exchange_for_symbol(symbol, exchange)`
- **Entry:** `fetch_market_data(symbol, exchange)` — validates, normalises, routes by exchange + asset type
- **Routing:** Alpaca crypto → `_fetch_alpaca_crypto` (v1beta3); Alpaca stock → `_fetch_alpaca_stock` (v2); Binance → `_fetch_binance`; OANDA → `_fetch_oanda` (symbol format `EUR_USD`)
- **OHLCV:** `fetch_ohlcv(symbol, exchange, limit)` — same routing; `_fetch_alpaca_crypto_closes`, `_fetch_alpaca_stock_closes`, `_fetch_oanda_closes`
- **Bundle:** `full_market_analysis(symbol, exchange)` — fetch + indicators + trend + support/resistance
- **Indicators:** RSI, MACD, MAs, support/resistance, trend detection

### Exchange execution — `src/integrations/exchange_client.py`

- Binance, Alpaca, OANDA clients (place_order, stop_loss, take_profit, balance, close_position, etc.)

### Other integrations

- `src/integrations/stripe_client.py` — Stripe API
- `src/integrations/telegram_bot.py` — Telegram bot
- `src/integrations/whatsapp_bot.py` — WhatsApp (Twilio)

### Services

- `src/services/subscription.py` — Checkout, portal, webhook sync; `check_trade_limit` (free 10/month); no symbol restriction
- `src/services/trade_monitoring.py` — Loss limits, monitoring loop
- `src/services/trade_execution.py` — Position sizing, trade params
- `src/services/context_detection.py` — Chat context classification
- `src/services/conversation_memory.py` — Chat history
- `src/services/learning_hub.py` — Patterns, instructions, insights, dashboard
- `src/services/email_sequences.py` — Trial emails, etc.

### Utils

- `src/utils/json_parser.py` — Parse Claude JSON

---

## 5. Database models (`models.py`)

| Model | Table | Purpose |
|-------|--------|--------|
| RefreshToken | refresh_tokens | JWT refresh tokens per session |
| User | users | Email, password, ai_name, subscription, trial, 2FA, Stripe ids |
| Trade | trades | Per-trade: symbol, side, qty, entry/exit, stop/target, P&L, status, exchange, claude_confidence, market_condition |
| Conversation | conversations | Chat message/response, context_type, sentiment |
| ExchangeAPIKey | exchange_api_keys | Encrypted keys per user per exchange (alpaca/binance/oanda) |
| UserSettings | user_settings | max_position_size, max_daily_loss, approved_assets, trading_hours, etc. |
| AuditLog | audit_logs | Event log (login, trade, etc.) |
| UserExternalAccount | user_external_accounts | Telegram/WhatsApp links |
| BotMessage | bot_messages | Bot message log |
| TelegramLinkingCode | telegram_linking_codes | Telegram link codes |
| Pattern | patterns | Learning patterns |
| AgentInstruction | agent_instructions | Learning instructions |
| AgentOutput | agent_outputs | Agent outputs for learning |
| BlogPost | blog_posts | Generated blog posts |
| SocialPost | social_posts | Generated social posts |
| AgentOutcomeModel | agent_outcomes | Outcomes for learning |
| SharedContextModel | shared_context | Shared context for trading |

---

## 6. Frontend — Pages

| Page | Path | Purpose |
|------|------|--------|
| Landing | `frontend/pages/index.tsx` | Marketing/landing |
| App shell | `frontend/pages/_app.tsx` | App wrapper, Clerk |
| Dashboard app | `frontend/pages/app.tsx` | Main app: sidebar nav, Dashboard, Trade, Chat, Positions, History, Performance, Exchanges, Content, Learning, Settings; trial banner; TrialChoiceModal |
| Login | `frontend/pages/login/[[...index]].tsx` | Clerk login catch-all |
| Register | `frontend/pages/register/[[...index]].tsx` | Clerk register catch-all |
| Onboarding | `frontend/pages/onboarding.tsx` | Post-signup (e.g. AI name) |
| Connect exchange | `frontend/pages/connect-exchange.tsx` | Add exchange API keys |
| Trial countdown | `frontend/pages/trial-countdown.tsx` | Trial countdown view |

---

## 7. Frontend — Components

| Component | Path | Purpose |
|-----------|------|--------|
| TradePanel | `frontend/components/TradePanel.tsx` | Execute trade: exchange + symbol, normalise symbol (e.g. BTC→BTCUSDT/BTC/USD), execute, show result/rejection/error; link to Settings if API key error |
| PositionsPanel | `frontend/components/PositionsPanel.tsx` | Open positions table, close position |
| ContentPanel | `frontend/components/ContentPanel.tsx` | Content/blog/social UI |
| LearningPanel | `frontend/components/LearningPanel.tsx` | Learning hub UI |
| SecuritySettings | `frontend/components/SecuritySettings.tsx` | Security/2FA, linked accounts |
| ExchangeConnections | `frontend/components/ExchangeConnections.tsx` | List/connect/disconnect exchanges (used in Settings) |
| TrialChoiceModal | `frontend/components/TrialChoiceModal.tsx` | Pro / Free / Cancel after trial |

---

## 8. Frontend — API client & types

- **API client:** `frontend/lib/api.ts`
  - Axios instance, JWT from localStorage, 401 → redirect to login
  - **authApi:** register, login, me, clerkSync, clerkSetup, 2FA, Telegram/WhatsApp codes, externalAccounts, unlinkAccount
  - **tradingApi:** openPositions, history, performance(params), riskAnalysis, execute(symbol, exchange) [timeout 90s], closePosition(trade_id)
  - **tradingAPI (typed):** getOpenPositions, getTradeHistory(params), getPerformance(params), closePosition(tradeId); BackendTrade, PerformanceData
  - **exchangeApi:** list, connect, disconnect
  - **chatApi:** sendMessage, history
  - **billingApi:** plans, status, checkout, checkoutSession, portal
  - **trialApi:** status, choiceOptions, makeChoice
  - **contentApi:** topics, blogPosts, blogPost, generateBlog, publishBlog, socialCalendar, generateSocial, socialPosts
  - **learningApi:** patterns, instructions, outputs, insights, dashboard, trigger
- **Trading types:** `frontend/types/trading.ts` — OpenPosition, Trade, AIAnalysis, PerformanceStats, UserTradingSettings, CircuitBreakerAlert, TradeExecutionNotification (optional/legacy; backend trade shape is in api.ts as BackendTrade)

---

## 9. Frontend — Hooks & config

- `frontend/hooks/useTrialStatus.ts` — Trial status, banner, modal
- `frontend/styles/globals.css` — Tailwind, design tokens (e.g. dark theme, brand)
- `frontend/middleware.ts` — Next middleware (e.g. auth)

---

## 10. Deployment & tests

| Item | Path | Purpose |
|------|------|--------|
| Production test script | `unitrader-bot/test_production.py` | Hits live backend: health, auth, chat, trading (open positions, performance, risk) — 11 checks |
| Railway config | `unitrader-bot/railway.toml` or `deployment/railway.toml` | Railway deployment |
| Vercel config | `frontend/vercel.json` or `deployment/vercel.json` | Frontend deployment |
| Docs | `unitrader-bot/DOCUMENTATION.md` | Full project docs (overview, stack, structure, API, DB, env, run, deploy) |

---

## 11. Exchange × asset matrix (current behaviour)

| Exchange | Stocks | Crypto | Forex | Symbol format |
|----------|--------|--------|--------|----------------|
| Alpaca | ✅ | ✅ | ❌ | AAPL, BTC/USD |
| Binance | ❌ | ✅ | ❌ | BTCUSDT |
| OANDA | ❌ | ❌ | ✅ | EUR_USD |

- **Symbol handling:** Backend normalises and validates in `market_data.py` and in the trading agent before execution (e.g. EUR/USD → EUR_USD for OANDA; BTC → BTCUSDT or BTC/USD by exchange).
- **Free tier:** 10 trades per calendar month; no symbol restriction (all products per exchange allowed).

---

## 12. Quick checklist for project overview

- [ ] All routers above match expected API surface
- [ ] All DB models match expected schema
- [ ] Frontend pages and components match expected UI
- [ ] Trading flow: execute → orchestrator → market_data (routing) → trading_agent (decide + execute_trade with normalised symbol)
- [ ] Auth: JWT + optional Clerk sync; 2FA; Telegram/WhatsApp linking
- [ ] Billing: Stripe checkout/portal/webhook; trial choice (pro/free/cancel)
- [ ] Exchanges: connect/list/delete keys; execute/positions/history/performance/close-position/risk-analysis
- [ ] Symbol routing: classify_asset, normalise_symbol, validate_exchange_for_symbol; Alpaca crypto vs stock; OANDA EUR_USD

---

*Generated for cross-review with project overview. Update this file when adding or removing features.*
