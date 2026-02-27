# Unitrader

**Personal AI Trading Companion Platform** — FastAPI backend.

---

## Prerequisites

- Python 3.11+
- PostgreSQL (production) or SQLite (local development — zero config)

---

## Installation

```bash
git clone <your-repo-url>
cd unitrader-bot

# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Environment Setup

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

Open `.env` and fill in the required values:

| Variable | Where to get it |
|---|---|
| `JWT_SECRET_KEY` | Run: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `MASTER_ENCRYPTION_KEY` | Run: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `FIELD_ENCRYPTION_KEY` | Same as above (generate a second, different key) |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `SUPABASE_URL` / Keys | [supabase.com](https://supabase.com) — create a project |
| `CLERK_API_KEY` | [dashboard.clerk.com](https://dashboard.clerk.com) |
| `RESEND_API_KEY` | [resend.com](https://resend.com/api-keys) |
| `STRIPE_SECRET_KEY` | [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys) |
| `BINANCE_API_KEY` | [binance.com/en/my/settings/api-management](https://www.binance.com/en/my/settings/api-management) |
| `ALPACA_API_KEY` | [app.alpaca.markets](https://app.alpaca.markets/paper-trading/overview) |
| `OANDA_API_KEY` | [developer.oanda.com](https://developer.oanda.com) |
| `SENTRY_DSN` | [sentry.io](https://sentry.io) |

> For local development you only **need** `JWT_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, and optionally `ANTHROPIC_API_KEY`. Everything else degrades gracefully.

---

## Database Setup

Tables are created automatically on startup. To create them manually:

```bash
python -c "import asyncio; from database import create_tables; asyncio.run(create_tables())"
```

---

## Running the App

```bash
python -m uvicorn main:app --reload
```

| URL | Description |
|---|---|
| http://localhost:8000 | Root / health |
| http://localhost:8000/docs | Swagger UI (interactive API docs) |
| http://localhost:8000/redoc | ReDoc |
| http://localhost:8000/health | App liveness |
| http://localhost:8000/health/database | DB connectivity |
| http://localhost:8000/health/ai | Anthropic API status |
| http://localhost:8000/health/email | Resend status |
| http://localhost:8000/health/payment | Stripe status |

---

## API Reference

### Authentication

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Create account |
| `POST` | `/api/auth/verify-email` | Confirm email |
| `POST` | `/api/auth/login` | Get JWT tokens |
| `POST` | `/api/auth/logout` | Revoke refresh token |
| `POST` | `/api/auth/refresh-token` | Issue new access token |
| `POST` | `/api/auth/2fa/setup` | Generate TOTP secret + QR |
| `POST` | `/api/auth/2fa/verify` | Activate 2FA |
| `POST` | `/api/auth/password-reset-request` | Send reset email |
| `POST` | `/api/auth/password-reset` | Apply new password |
| `GET` | `/api/auth/me` | Current user profile |

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | App liveness |
| `GET` | `/health/database` | Database connectivity |
| `GET` | `/health/ai` | Anthropic API |
| `GET` | `/health/email` | Resend API |
| `GET` | `/health/payment` | Stripe API |

---

## Project Structure

```
unitrader-bot/
├── main.py           FastAPI app, middleware, error handlers, startup
├── config.py         All settings loaded from .env
├── database.py       Async SQLAlchemy engine + session dependency
├── models.py         ORM models: User, Trade, Conversation, ExchangeAPIKey,
│                                 UserSettings, AuditLog
├── schemas.py        Pydantic request / response schemas
├── security.py       bcrypt, JWT, Fernet encryption, TOTP, input validation
├── requirements.txt
├── .env.example      Template — copy to .env
├── .gitignore
└── routers/
    ├── auth.py       All /api/auth/* endpoints
    └── health.py     All /health/* endpoints
```

---

## Security Notes

- All passwords hashed with **bcrypt** (never stored plain)
- All broker API keys encrypted with **Fernet** (AES-128-CBC)
- JWT tokens are short-lived (1 hour access / 30 day refresh)
- Rate limiting via **slowapi** on all auth endpoints
- Security headers added to every response (CSP, HSTS in production)
- `.env` is in `.gitignore` — never commit secrets
