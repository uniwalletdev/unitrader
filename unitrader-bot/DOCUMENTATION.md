# Unitrader — Complete Project Documentation

**Unitrader** is a Personal AI Trading Companion Platform. Users name their own AI, connect their trading exchanges, and let Claude AI analyse markets, execute trades, and enforce risk management 24/7 — automatically.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Project Structure](#3-project-structure)
4. [Week 1 — Foundation](#4-week-1--foundation)
5. [Week 2 — Trading Execution Agent](#5-week-2--trading-execution-agent)
6. [Week 3 — Conversation + Content Agents](#6-week-3--conversation--content-agents)
7. [Week 4 — Frontend + Payments + Deployment](#7-week-4--frontend--payments--deployment)
8. [API Reference](#8-api-reference)
9. [Database Models](#9-database-models)
10. [Environment Variables](#10-environment-variables)
11. [Running the Project](#11-running-the-project)
12. [Deployment Guide](#12-deployment-guide)
13. [Known Fixes Applied](#13-known-fixes-applied)

---

## 1. Project Overview

### What it does
- Users register and give their AI a custom name (e.g. "Apex", "Nova")
- Claude AI analyses markets every 5 minutes using RSI, MACD, moving averages, support/resistance
- AI executes trades on Binance, Alpaca, or OANDA automatically
- Hard safety guardrails enforce risk limits (max 2% per trade, daily loss limits, stop-loss)
- Users chat with their AI — it detects context and responds appropriately (educational, emotional support, market analysis, etc.)
- Marketing content (blog posts, social media posts) is auto-generated daily/weekly/monthly
- Stripe payments gate Pro features ($49/month, 7-day free trial)

### Core Philosophy
> "Your AI, your rules." — Users control everything: approved assets, position sizes, trading hours, and can pause the AI at any time.

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| **Backend Framework** | FastAPI (Python 3.11) |
| **AI** | Anthropic Claude 3 Haiku via `anthropic` SDK |
| **Database** | SQLite (dev) / PostgreSQL via asyncpg (prod) |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Authentication** | JWT (access + refresh tokens), bcrypt password hashing |
| **2FA** | TOTP via `pyotp` |
| **Encryption** | Fernet (symmetric) for API keys and sensitive fields |
| **Rate Limiting** | `slowapi` |
| **HTTP Client** | `httpx` (async) |
| **Email** | Resend API |
| **Payments** | Stripe (Checkout Sessions, Customer Portal, Webhooks) |
| **Error Tracking** | Sentry SDK |
| **Frontend** | Next.js 14 (TypeScript, Tailwind CSS) |
| **Deployment** | Railway (backend) + Vercel (frontend) + Docker |

---

## 3. Project Structure

```
unitrader-bot/
│
├── main.py                     # FastAPI app entry point, middleware, lifespan
├── config.py                   # Settings (pydantic-settings, env vars)
├── database.py                 # Async SQLAlchemy engine, session, init
├── models.py                   # All ORM models (9 tables)
├── schemas.py                  # Pydantic request/response schemas
├── security.py                 # Passwords, JWT, Fernet encryption, 2FA
├── requirements.txt            # Python dependencies
├── .env                        # Local environment variables (never commit)
├── .env.example                # Template for .env
├── .gitignore                  # Git ignore rules
├── Dockerfile                  # Multi-stage Python 3.11 container
├── .dockerignore               # Docker build exclusions
├── DOCUMENTATION.md            # This file
│
├── routers/
│   ├── __init__.py
│   ├── auth.py                 # Register, login, 2FA, password reset
│   ├── health.py               # Health checks (DB, AI, email, payments)
│   ├── trading.py              # Trade execution, positions, history, risk
│   ├── chat.py                 # AI conversation endpoints
│   ├── content.py              # Blog posts and social media endpoints
│   └── billing.py              # Stripe checkout, portal, webhook
│
├── src/
│   ├── agents/
│   │   ├── core/
│   │   │   ├── trading_agent.py       # Main trading AI agent
│   │   │   └── conversation_agent.py  # Multi-context chat AI agent
│   │   └── marketing/
│   │       ├── content_writer.py      # Blog post generation
│   │       └── social_media.py        # Social post generation
│   │
│   ├── integrations/
│   │   ├── exchange_client.py         # Binance, Alpaca, OANDA clients
│   │   ├── market_data.py             # Price data + technical indicators
│   │   └── stripe_client.py           # Stripe API wrapper
│   │
│   └── services/
│       ├── trade_execution.py         # Position sizing, stop/target math
│       ├── trade_monitoring.py        # Open position monitoring loop
│       ├── subscription.py            # Subscription lifecycle management
│       ├── context_detection.py       # Chat context classifier
│       └── conversation_memory.py     # Chat history + sentiment analysis
│
├── tests/
│   ├── test_trading.py                # Unit tests for trade execution + market data
│   ├── test_chat.py                   # Unit tests for context detection + sentiment
│   └── test_content.py                # Unit tests for content generation utilities
│
├── frontend/                          # Next.js 14 app
│   ├── pages/
│   │   ├── _app.tsx
│   │   ├── index.tsx                  # Landing page
│   │   ├── app.tsx                    # App dashboard
│   │   ├── login.tsx                  # Login page
│   │   └── register.tsx               # Registration page
│   ├── components/                    # Shared UI components
│   ├── lib/
│   │   └── api.ts                     # Typed Axios API client
│   ├── styles/
│   │   └── globals.css                # Tailwind + design tokens
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   └── Dockerfile.frontend
│
└── deployment/
    ├── docker-compose.yml             # Full stack (API + DB + Frontend + Nginx)
    ├── nginx.conf                     # Reverse proxy config
    ├── railway.toml                   # Railway deployment config
    └── vercel.json                    # Vercel frontend deployment config
```

---

## 4. Week 1 — Foundation

### Files Created
`main.py`, `config.py`, `database.py`, `models.py`, `schemas.py`, `security.py`, `requirements.txt`, `.env.example`, `.gitignore`, `routers/auth.py`, `routers/health.py`

### What Was Built

#### FastAPI Application (`main.py`)
- CORS, HTTPS redirect, Trusted Host, Security Headers middleware
- Request logging middleware (method, URL, status, response time)
- Rate limiting via `slowapi` (5 login attempts/15min, 100 req/min general, 10 req/min trading)
- Global exception handlers for validation errors and generic 500s
- `lifespan` context manager: initialises DB on startup, launches background tasks, graceful shutdown

#### Configuration (`config.py`)
- `Settings` class via pydantic-settings
- Loads all environment variables with defaults and validation
- Computed properties: `allowed_origins_list`, `is_production`
- Covers: app, server, database, auth, encryption, AI, payments, email, trading APIs, monitoring

#### Database (`database.py`)
- Async SQLAlchemy engine (SQLite for dev, PostgreSQL for prod)
- `get_db()` dependency injection for FastAPI routes
- `AsyncSessionLocal` for use in background tasks
- `init_db()` creates all tables idempotently on startup

#### Models (`models.py`) — 9 database tables
See [Section 9 — Database Models](#9-database-models) for full details.

#### Security (`security.py`)
| Function | Description |
|---|---|
| `hash_password` / `verify_password` | bcrypt hashing |
| `encrypt_api_key` / `decrypt_api_key` | Fernet encryption for exchange credentials |
| `encrypt_field` / `decrypt_field` | General-purpose field encryption |
| `create_access_token` | JWT with 1-hour expiry |
| `create_refresh_token` | JWT with 30-day expiry |
| `verify_token` | Validates JWT, checks type |
| `generate_2fa_secret` | TOTP secret via pyotp |
| `get_totp_uri` | QR code URI for authenticator apps |
| `verify_totp` | Validates TOTP code |
| `generate_backup_codes` | 8 one-time backup codes |

#### Auth Endpoints (`routers/auth.py`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/register` | Create account, send verification email |
| POST | `/api/auth/verify-email` | Verify email with token |
| POST | `/api/auth/login` | Login with optional 2FA challenge |
| POST | `/api/auth/logout` | Revoke refresh token |
| POST | `/api/auth/refresh-token` | Get new access token |
| POST | `/api/auth/2fa/setup` | Generate TOTP secret + QR code |
| POST | `/api/auth/2fa/verify` | Enable 2FA |
| POST | `/api/auth/password-reset-request` | Send reset email |
| POST | `/api/auth/password-reset` | Set new password with token |
| GET | `/api/auth/me` | Get current user profile |

---

## 5. Week 2 — Trading Execution Agent

### Files Created
`src/integrations/exchange_client.py`, `src/integrations/market_data.py`, `src/agents/core/trading_agent.py`, `src/services/trade_execution.py`, `src/services/trade_monitoring.py`, `routers/trading.py`, `tests/test_trading.py`

### Exchange Client (`src/integrations/exchange_client.py`)
Abstract base class `BaseExchangeClient` with concrete implementations for:
- **BinanceClient** — crypto trading (BTC, ETH, etc.)
- **AlpacaClient** — US stocks (paper trading supported)
- **OandaClient** — forex pairs

All clients implement:
```
get_account_balance()  → float
get_current_price(symbol) → float
place_order(symbol, side, quantity, price) → order_id
set_stop_loss(order_id, stop_price) → bool
set_take_profit(order_id, target_price) → bool
get_open_orders(symbol) → list
close_position(symbol) → bool
get_order_status(order_id) → dict
```

All API calls wrapped with `_with_retry` decorator: exponential backoff, 3 retries, timeout handling.

### Market Data (`src/integrations/market_data.py`)
| Function | Output |
|---|---|
| `fetch_market_data(symbol, exchange)` | Current price, 24h high/low, volume |
| `calculate_rsi(prices, period=14)` | RSI value 0–100 |
| `calculate_macd(prices)` | Line, signal, histogram |
| `calculate_moving_averages(prices)` | MA20, MA50, MA200 |
| `detect_trend(prices)` | `"uptrend"` / `"downtrend"` / `"consolidating"` |
| `calculate_support_resistance(prices)` | Support, resistance, pivot levels |
| `full_market_analysis(symbol, exchange)` | All of the above bundled |

### Trading Agent (`src/agents/core/trading_agent.py`)

**Flow for each trading cycle:**
```
analyze_market()
    → fetch_market_data + all indicators
    → get_claude_decision()
        → format market data as prompt
        → send to Claude: "BUY/SELL/WAIT + confidence 0-100 + reasoning"
        → parse JSON response
    → personalize_decision()
        → look up user's win rate for this setup
        → adjust position size up/down accordingly
    → _safety_checks()
        → enforce: max 2% position size
        → enforce: stop-loss present
        → enforce: daily loss limit not exceeded
        → enforce: sufficient balance
    → execute_trade()
        → place main order
        → place stop-loss order
        → place take-profit order
        → save Trade to database
        → notify user
```

### Trade Execution Service (`src/services/trade_execution.py`)
Pure calculation functions (fully unit tested):

| Confidence | Position Size |
|---|---|
| < 50% | No trade |
| 50–65% | 0.5% of account |
| 65–75% | 1.0% of account |
| 75–85% | 1.5% of account |
| 85%+ | 2.0% of account (maximum) |

- Stop-loss: 2% below entry (BUY) / 2% above entry (SELL)
- Take-profit: 6% above entry (BUY) / 6% below entry (SELL)
- Risk/reward ratio: always 3:1

### Trade Monitoring (`src/services/trade_monitoring.py`)
Background loop runs every 60 seconds:
- Checks all open positions against current prices
- Closes position if stop-loss hit
- Closes position if take-profit hit
- **Loss Limits:** Daily -5% → halt trading. Weekly -10% → reduce size. Monthly -15% → close all.
- **Circuit Breakers:** 3% loss in 1 hour, exchange downtime, unusual trade frequency

### Trading Endpoints (`routers/trading.py`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/trading/execute` | Trigger AI trade cycle for a symbol |
| GET | `/api/trading/open-positions` | All open trades for user |
| GET | `/api/trading/history` | Closed trades (filterable) |
| GET | `/api/trading/performance` | Win rate, P&L, stats |
| POST | `/api/trading/close-position` | Manually close a trade |
| GET | `/api/trading/risk-analysis` | Daily loss, remaining budget, alerts |

### Background Tasks
- **Trading loop**: every 5 minutes, runs `TradingAgent.run_cycle()` for all active users
- **Monitor loop**: every 60 seconds, checks all open positions

---

## 6. Week 3 — Conversation + Content Agents

### Files Created
`src/agents/core/conversation_agent.py`, `src/services/context_detection.py`, `src/services/conversation_memory.py`, `routers/chat.py`, `src/agents/marketing/content_writer.py`, `src/agents/marketing/social_media.py`, `routers/content.py`, `tests/test_chat.py`, `tests/test_content.py`

### Context Detection (`src/services/context_detection.py`)
Classifies user messages into 8 contexts using weighted regex scoring:

| Context | Trigger Words/Phrases | Claude's Tone |
|---|---|---|
| `friendly_chat` | "awesome", "love", "great", 🎉 | Warm, enthusiastic, match energy |
| `trading_question` | "should I", "buy", "sell", "enter" | Analytical, data-driven, show confidence |
| `technical_help` | "how do I", "error", "can't", "problem" | Patient, step-by-step |
| `market_analysis` | "predict", "trend", "outlook", "what will" | Professional analyst, objective |
| `ai_performance` | "why did", "performance", "stats", "loss" | Coach, honest, supportive |
| `educational` | "what is", "explain", "teach", "how does" | Educator, examples and analogies |
| `emotional_support` | "worried", "frustrated", "scared", "concerned" | Empathetic, normalise emotions |
| `general` | (default) | Helpful, friendly, professional |

### Conversation Agent (`src/agents/core/conversation_agent.py`)
- Loads user's custom AI name from database
- Detects context and selects appropriate system prompt
- Fetches last 20 conversation turns as context for Claude
- For `ai_performance` context: injects actual trading stats into prompt
- Calls Claude with `AsyncAnthropic` client
- Saves conversation + sentiment to `Conversation` table
- Falls back gracefully if Claude API is unavailable

### Conversation Memory (`src/services/conversation_memory.py`)
- `save_conversation()` — persists to DB with context type and sentiment
- `get_conversation_history()` — retrieves last N turns
- `get_recent_messages_for_claude()` — formats history as Claude message array
- `analyze_sentiment()` — rule-based positive/negative/neutral detection
- `rate_conversation()` — saves user feedback (thumbs up/down)

### Chat Endpoints (`routers/chat.py`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/chat/message` | Send message, get AI response |
| GET | `/api/chat/history` | Last 50 conversations |
| GET | `/api/chat/sentiment` | Test context + sentiment detection |
| POST | `/api/chat/rate` | Rate a conversation as helpful/not |
| DELETE | `/api/chat/history` | Clear conversation history |

### Content Writer (`src/agents/marketing/content_writer.py`)
Generates SEO-optimised blog posts using Claude:
- 1000+ word posts with Introduction, Key Points, Examples, Conclusion, CTA
- Includes real platform stats (user count, win rates, trade volume)
- Returns: title, slug, content, SEO keywords, estimated read time, word count

### Social Media Agent (`src/agents/marketing/social_media.py`)
Generates varied social posts per session:
- 2x Educational posts
- 1x Social Proof post
- 1x Call-to-Action post
- 1x Inspirational post
- Platform-aware: Twitter (280 chars), LinkedIn, Instagram, Facebook
- Includes hashtags and estimated engagement level

### Background Content Scheduler
| Cadence | Task |
|---|---|
| Daily | Generate 5 social media posts |
| Weekly (Mondays) | Generate 2 blog posts |
| Monthly (1st) | Generate 1 major trading guide |

### Content Endpoints (`routers/content.py`)
| Method | Path | Description |
|---|---|---|
| GET | `/api/content/topics` | List suggested blog topics |
| GET | `/api/content/blog-posts` | List published posts |
| GET | `/api/content/blog-posts/{slug}` | Get single post |
| POST | `/api/content/generate-blog` | Generate new blog post |
| POST | `/api/content/blog-posts/{id}/publish` | Publish a draft post |
| GET | `/api/content/social-calendar` | 30-day social media calendar |
| POST | `/api/content/generate-social` | Generate new social posts |
| GET | `/api/content/social-posts` | List all social posts |

---

## 7. Week 4 — Frontend + Payments + Deployment

### Files Created
`frontend/` (full Next.js app), `src/integrations/stripe_client.py`, `src/services/subscription.py`, `routers/billing.py`, `Dockerfile`, `.dockerignore`, `deployment/docker-compose.yml`, `deployment/nginx.conf`, `deployment/railway.toml`, `deployment/vercel.json`

### Landing Page (`frontend/pages/index.tsx`)
Dark-themed, modern trading aesthetic with:
- Sticky navbar with mobile menu
- Live price ticker bar (animated)
- Hero with animated stat counters (284k trades, 73% win rate, etc.)
- Features grid (6 cards with icons)
- How It Works (3-step visual)
- Testimonials (3 trader quotes)
- Pricing section (Free vs Pro, highlighted)
- FAQ (accordion)
- Final CTA section
- Footer with legal notice

### App Dashboard (`frontend/pages/app.tsx`)
Full authenticated dashboard with:
- Sidebar navigation (Dashboard, Chat, Positions, History, Settings)
- AI status indicator (name + live dot)
- Stats cards (Balance, P&L, Win Rate, Open Positions)
- Daily risk usage gauge with alert if approaching limit
- Open positions table (symbol, side, entry, stop, target, confidence)
- Full AI chat interface with suggestion chips
- Trade history table
- Settings panel with Upgrade to Pro / Billing Portal buttons

### Additional Pages
- `frontend/pages/login.tsx` — Email + password login, JWT storage
- `frontend/pages/register.tsx` — Registration with AI name input, auto-login

### API Client (`frontend/lib/api.ts`)
Typed Axios client covering all backend routes:
- Auto-attaches JWT from localStorage on every request
- Auto-redirects to `/login` on 401
- Modules: `authApi`, `tradingApi`, `chatApi`, `billingApi`

### Stripe Integration (`src/integrations/stripe_client.py`)
| Function | Description |
|---|---|
| `create_customer()` | Create Stripe customer on first checkout |
| `create_checkout_session()` | Hosted checkout with 7-day free trial |
| `create_portal_session()` | Billing management portal |
| `get_subscription()` | Retrieve subscription status |
| `cancel_subscription()` | Cancel at period end or immediately |
| `verify_webhook()` | Validate Stripe-Signature header |
| `parse_subscription_event()` | Extract fields from webhook events |

**Handled webhook events:**
- `customer.subscription.created/updated/deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`

### Subscription Service (`src/services/subscription.py`)
- `start_pro_checkout()` — Creates Stripe customer if needed, returns checkout URL
- `get_billing_portal_url()` — Returns portal URL for billing management
- `sync_subscription_from_webhook()` — Updates User tier in DB from webhook
- `is_pro()` — Feature gate check
- `check_trade_limit()` — Free tier: 10 trades/month limit
- `get_subscription_summary()` — Clean dict for API responses

### Billing Endpoints (`routers/billing.py`)
| Method | Path | Description |
|---|---|---|
| GET | `/api/billing/plans` | Public pricing info |
| GET | `/api/billing/status` | Current user subscription state |
| POST | `/api/billing/checkout` | Start Stripe Checkout (redirect URL) |
| POST | `/api/billing/portal` | Open billing management portal |
| POST | `/api/billing/webhook` | Receive Stripe webhook events |

### Deployment Files

**`Dockerfile`** — Multi-stage Python 3.11 build:
- Stage 1 (builder): install all deps including build tools
- Stage 2 (runtime): minimal image, copy installed packages
- Non-root user for security
- Healthcheck on `/health`

**`deployment/docker-compose.yml`** — Full stack:
- `api` — FastAPI backend
- `db` — PostgreSQL 16 with volume persistence
- `frontend` — Next.js app
- `nginx` — Reverse proxy with security headers
- All services networked together

**`deployment/railway.toml`** — One-click Railway deploy from Dockerfile

**`deployment/vercel.json`** — Vercel config with security headers and API proxy rewrites

---

## 8. API Reference

### Base URL
- Development: `http://localhost:8000`
- Production: `https://your-app.up.railway.app`
- Documentation: `http://localhost:8000/docs` (Swagger UI)

### Authentication
All protected endpoints require:
```
Authorization: Bearer <access_token>
```

Tokens expire after **1 hour**. Use `POST /api/auth/refresh-token` with your refresh token to get a new one.

### Response Format
All responses follow this envelope:
```json
{
  "status": "success | error | logged_in | ...",
  "data": { ... },
  "error": "Error message (only on errors)"
}
```

### Rate Limits
| Scope | Limit |
|---|---|
| Login | 5 requests / 15 minutes |
| Trading execute | 10 requests / minute |
| General API | 100 requests / minute |

---

## 9. Database Models

### `users`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| email | String(255) | Unique, indexed |
| password_hash | String(255) | bcrypt |
| ai_name | String(20) | User's custom AI name |
| subscription_tier | String(20) | `free` or `pro` |
| trial_end_date | DateTime | Nullable |
| email_verified | Boolean | Default False |
| two_fa_enabled | Boolean | Default False |
| two_fa_secret | String(512) | Fernet encrypted |
| stripe_customer_id | String(64) | Unique, indexed |
| stripe_subscription_id | String(64) | Indexed |
| stripe_subscription_status | String(20) | `active`, `trialing`, `past_due`, `canceled` |
| subscription_current_period_end | DateTime | Nullable |
| email_verification_token | String(128) | Nullable |
| password_reset_token | String(128) | Nullable |
| password_reset_expires | DateTime | Nullable |
| created_at | DateTime | Auto |
| updated_at | DateTime | Auto |
| last_login | DateTime | Nullable |
| is_active | Boolean | Default True |

### `refresh_tokens`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| token | String(512) | Unique, indexed |
| user_id | UUID | FK → users (cascade delete) |
| expires_at | DateTime | |
| is_revoked | Boolean | Default False |
| user_agent | Text | Nullable |
| ip_address | String(45) | Nullable |
| created_at | DateTime | Auto |

### `trades`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| symbol | String(20) | e.g. `BTC/USD` |
| side | String(10) | `BUY` or `SELL` |
| quantity | Float | |
| entry_price | Float | |
| exit_price | Float | Nullable |
| stop_loss | Float | |
| take_profit | Float | |
| profit | Float | Nullable |
| loss | Float | Nullable |
| profit_percent | Float | Nullable |
| status | String(10) | `open` or `closed` |
| claude_confidence | Float | 0–100 |
| market_condition | String(20) | `uptrend`, `downtrend`, `consolidating` |
| exchange | String(20) | |
| created_at | DateTime | Auto |
| closed_at | DateTime | Nullable |
| execution_time | Float | Milliseconds |

**Indexes:** `(user_id, status)`, `(user_id, created_at)`, `(user_id, symbol)`

### `conversations`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| message | Text | User's message |
| response | Text | AI's response |
| context_type | String(30) | e.g. `educational`, `friendly_chat` |
| sentiment | String(10) | `positive`, `negative`, `neutral` |
| is_helpful | Boolean | Nullable (user rating) |
| created_at | DateTime | Auto |

### `exchange_api_keys`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| exchange | String(20) | `binance`, `alpaca`, `oanda` |
| encrypted_api_key | String | Fernet encrypted |
| encrypted_api_secret | String | Fernet encrypted |
| key_hash | String(64) | For verification without decrypting |
| is_active | Boolean | Default True |
| key_version | Integer | For rotation tracking |
| last_used_at | DateTime | Nullable |
| rotated_at | DateTime | Nullable |
| created_at | DateTime | Auto |

### `user_settings`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | FK → users (unique) |
| max_position_size | Float | Default 2.0% |
| max_daily_loss | Float | Default 5.0% |
| approved_assets | JSON | Array of symbols |
| trading_hours_start | Time | |
| trading_hours_end | Time | |
| require_confirmation_above | Float | Nullable ($ threshold) |
| theme | String(10) | `light` or `dark` |
| updated_at | DateTime | |

### `audit_logs`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | Nullable (for system events) |
| event_type | String | `login`, `trade`, `api_key_rotated`, etc. |
| event_details | JSON | Structured event data |
| ip_address | String(45) | |
| user_agent | String | |
| timestamp | DateTime | Indexed |

**Indexes:** `(user_id, timestamp)`, `(event_type, timestamp)`

### `blog_posts`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| title | String(300) | |
| slug | String(350) | Unique, indexed |
| topic | String(300) | Source topic |
| content | Text | Full blog post |
| seo_keywords | JSON | Array of keywords |
| estimated_read_time | Integer | Minutes |
| word_count | Integer | |
| is_published | Boolean | Default False |
| created_at | DateTime | Auto |
| published_at | DateTime | Nullable |

### `social_posts`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| platform | String(20) | `twitter`, `linkedin`, `instagram`, `facebook` |
| content | Text | Post text |
| hashtags | JSON | Array of hashtags |
| post_type | String(20) | `educational`, `social_proof`, `call_to_action`, `inspirational` |
| topic | String(300) | Nullable |
| estimated_engagement | String(10) | `high`, `medium`, `low` |
| is_posted | Boolean | Default False |
| scheduled_for | DateTime | Nullable, indexed |
| created_at | DateTime | Auto |

---

## 10. Environment Variables

Copy `.env.example` to `.env` and fill in values. Run this to generate security keys:

```powershell
py -3.11 -c "import secrets; from cryptography.fernet import Fernet; print('JWT_SECRET_KEY=' + secrets.token_hex(32)); print('MASTER_ENCRYPTION_KEY=' + Fernet.generate_key().decode()); print('FIELD_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```

| Variable | Required | Description |
|---|---|---|
| `ENVIRONMENT` | Yes | `development` or `production` |
| `DATABASE_URL` | Yes | SQLite: `sqlite+aiosqlite:///./unitrader.db` or PostgreSQL asyncpg URL |
| `JWT_SECRET_KEY` | Yes | 64-char hex string |
| `MASTER_ENCRYPTION_KEY` | Yes | Fernet key (base64) |
| `FIELD_ENCRYPTION_KEY` | Yes | Fernet key (base64) |
| `ANTHROPIC_API_KEY` | Yes | `sk-ant-...` |
| `STRIPE_SECRET_KEY` | No | `sk_test_...` or `sk_live_...` |
| `STRIPE_PUBLIC_KEY` | No | `pk_test_...` |
| `STRIPE_WEBHOOK_SECRET` | No | `whsec_...` |
| `STRIPE_PRO_PRICE_ID` | No | `price_...` |
| `RESEND_API_KEY` | No | `re_...` |
| `BINANCE_API_KEY` / `SECRET` | No | Binance exchange keys |
| `ALPACA_API_KEY` / `SECRET` | No | Alpaca keys (`paper-api` URL for testing) |
| `OANDA_API_KEY` / `ACCOUNT_ID` | No | OANDA keys |
| `SENTRY_DSN` | No | Error tracking |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins |

---

## 11. Running the Project

### Prerequisites
- Python 3.11 (confirmed: `py -3.11 --version`)
- Node.js 20+ (for frontend)

### Backend

```powershell
# 1. Install dependencies
cd unitrader-bot
py -3.11 -m pip install -r requirements.txt

# 2. Configure environment
Copy-Item .env.example .env
# Edit .env with your keys (minimum: DATABASE_URL, JWT_SECRET_KEY, MASTER/FIELD keys, ANTHROPIC_API_KEY)

# 3. Start the server
py -3.11 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

URLs:
- API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### Frontend

```powershell
cd unitrader-bot/frontend
npm install
npm run dev
```

URL: http://localhost:3000

### Quick Health Check

```powershell
Invoke-WebRequest http://localhost:8000/health -UseBasicParsing
Invoke-WebRequest http://localhost:8000/health/database -UseBasicParsing
Invoke-WebRequest http://localhost:8000/health/ai -UseBasicParsing
```

---

## 12. Deployment Guide

### Backend → Railway

1. Push code to GitHub
2. Go to https://railway.app → New Project → Deploy from GitHub → select repo
3. Railway auto-detects `railway.toml` and `Dockerfile`
4. Add all environment variables from `.env` in Railway dashboard
5. Add a PostgreSQL add-on — Railway injects `DATABASE_URL` automatically
6. Get your Railway URL (e.g. `https://unitrader-abc123.up.railway.app`)

### Frontend → Vercel

1. Go to https://vercel.com → New Project → Import from GitHub
2. Set **Root Directory** to `frontend`
3. Add environment variables:
   - `NEXT_PUBLIC_API_URL` = your Railway URL
   - `NEXT_PUBLIC_STRIPE_PUBLIC_KEY` = your Stripe publishable key
4. Deploy — Vercel auto-builds on every push

### Stripe Webhooks

In Stripe Dashboard → Developers → Webhooks:
- Add endpoint: `https://your-railway-url.up.railway.app/api/billing/webhook`
- Select events: `customer.subscription.*`, `invoice.payment_succeeded`, `invoice.payment_failed`
- Copy the signing secret → add to Railway as `STRIPE_WEBHOOK_SECRET`

### Full Docker Stack (self-hosted)

```bash
cd deployment
cp ../.env .env  # copy your .env here
docker compose up -d
```

Services start on:
- Frontend: http://localhost:3000
- API: http://localhost:8000
- Via Nginx: http://localhost:80

---

## 13. Known Fixes Applied

These issues were discovered and fixed during development testing:

| Issue | Root Cause | Fix Applied |
|---|---|---|
| `resend==0.3.1` not found | Version yanked from PyPI | Updated to `resend>=2.0.0` |
| `supabase==1.2.2` not found | Version doesn't exist | Updated to `supabase>=2.0.0` (optional, commented out) |
| `httpx` version conflict | `supabase` required `<0.25`, `anthropic` required `>=0.23` | Unpinned `httpx` to `>=0.24.0,<1.0.0` |
| `email-validator` missing | Not in requirements but needed by pydantic `EmailStr` | Added via `pip install pydantic[email]` |
| Sentry crashes on startup | Placeholder DSN `project-id` is invalid | Added guard: skip Sentry if DSN is placeholder |
| `anthropic.Anthropic proxies` error | `anthropic==0.26.0` uses removed `httpx` `proxies` arg | Upgraded `anthropic` to `>=0.40.0` |
| `by_alias NoneType PyBool` error | pydantic `2.5.0` incompatible with `anthropic 0.84.0` | Upgraded pydantic to `>=2.7.0` |
| `claude-3-opus-20240229` → 404 | Model deprecated by Anthropic | Switched all agents to `claude-3-haiku-20240307` |
| Sync Claude in async endpoints | `asyncio.to_thread` with old sync client | Switched all agents to `AsyncAnthropic` and direct `await` |
| Port 8000 in use on restart | Old server process not fully terminated | Kill with `netstat -ano | findstr :8000` before restart |

---

## Summary Statistics

| Metric | Count |
|---|---|
| Python source files | ~25 |
| TypeScript/React files | ~10 |
| API endpoints | 38 |
| Database tables | 9 |
| Background tasks | 3 (trading loop, monitor loop, content scheduler) |
| Claude AI contexts | 8 |
| Test functions | ~40 unit tests |
| Lines of code (approx.) | ~6,000+ |

---

*Generated: February 2026 | Unitrader v0.1.0*
