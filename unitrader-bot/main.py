"""
main.py — FastAPI application entry point for Unitrader.

Wires together all middleware, routers, error handlers, and startup logic.
Run with:  python -m uvicorn main:app --reload
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from database import AsyncSessionLocal, create_tables
from models import User, UserSettings
from routers import auth, health
from routers import trading as trading_router
from routers import chat as chat_router
from routers import content as content_router
from routers import billing as billing_router
from routers import trial as trial_router
from routers import learning as learning_router
from routers.telegram_webhooks import (
    linking_router as telegram_linking_router,
    set_telegram_bot_service,
    webhook_router as telegram_webhook_router,
)
from routers.whatsapp_webhooks import (
    linking_router as whatsapp_linking_router,
    set_whatsapp_bot_service,
    webhook_router as whatsapp_webhook_router,
)
from src.agents.core.trading_agent import TradingAgent
from src.agents.marketing.content_writer import generate_weekly_posts, generate_monthly_guide
from src.agents.marketing.social_media import generate_daily_posts
from src.services.trade_monitoring import monitor_loop
from src.services.email_sequences import send_trial_emails_for_all_users
from src.services.learning_hub import learning_hub

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Sentry (production error tracking)
# ─────────────────────────────────────────────

_sentry_configured = (
    settings.sentry_dsn
    and not settings.sentry_dsn.startswith("https://your-sentry")
    and "project-id" not in settings.sentry_dsn
)
if _sentry_configured:
    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.2,
        )
        logger.info("Sentry initialised")
    except Exception as _e:
        logger.warning("Sentry init failed (skipping): %s", _e)
else:
    logger.info("Sentry not configured — skipping")

# ─────────────────────────────────────────────
# Rate Limiter
# ─────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_general])


# ─────────────────────────────────────────────
# Security Headers Middleware
# ─────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security-related HTTP response headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return response


# ─────────────────────────────────────────────
# Request Logging Middleware
# ─────────────────────────────────────────────

_SENSITIVE_PATHS = {"/api/auth/login", "/api/auth/register", "/api/auth/password-reset"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log method, path, status code, and response time for every request.

    Sensitive endpoints are logged without body content.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "%s %s → %d  (%.2fms)  ip=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request.client.host if request.client else "unknown",
        )
        response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
        return response


# ─────────────────────────────────────────────
# Lifespan (startup / shutdown)
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks before serving, cleanup after shutdown."""
    logger.info("Starting %s v%s (%s)", settings.app_name, settings.app_version, settings.environment)

    # 1. Initialise database tables
    await create_tables()

    # 2. Verify Anthropic API key is present
    if settings.anthropic_api_key:
        logger.info("Anthropic API key: configured")
    else:
        logger.warning("Anthropic API key: NOT configured — AI features disabled")

    # 3. Verify Supabase configuration
    if settings.supabase_url:
        logger.info("Supabase: configured at %s", settings.supabase_url)
    else:
        logger.warning("Supabase: NOT configured")

    # 4. Launch background loops
    trading_task  = asyncio.create_task(_trading_loop(),       name="trading_loop")
    monitor_task  = asyncio.create_task(monitor_loop(),        name="monitor_loop")
    content_task  = asyncio.create_task(_content_scheduler(),  name="content_scheduler")
    email_task    = asyncio.create_task(_email_scheduler(),    name="email_scheduler")
    learning_task = asyncio.create_task(_learning_scheduler(), name="learning_scheduler")
    logger.info(
        "Background loops started "
        "(trading=5min, monitoring=1min, content=daily, emails=daily@9am, learning=hourly)"
    )

    # 5. Initialise Telegram bot (optional — disabled if token not set)
    if settings.telegram_enabled:
        try:
            from src.integrations.telegram_bot import TelegramBotService
            _tg_bot = TelegramBotService(token=settings.telegram_bot_token)
            await _tg_bot.initialize()
            set_telegram_bot_service(_tg_bot)
            webhook_url = f"{settings.api_base_url}/webhooks/telegram"
            await _tg_bot.set_webhook(webhook_url)
        except Exception as _tg_exc:
            logger.error("Telegram bot failed to start: %s", _tg_exc)
            _tg_bot = None
    else:
        _tg_bot = None
        logger.info("Telegram bot disabled (TELEGRAM_BOT_TOKEN not set)")

    # 6. Initialise WhatsApp bot (optional — disabled if Twilio creds not set)
    if settings.whatsapp_enabled:
        try:
            from src.integrations.whatsapp_bot import WhatsAppBotService
            _wa_bot = WhatsAppBotService(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token,
                twilio_whatsapp_number=settings.twilio_whatsapp_number,
            )
            set_whatsapp_bot_service(_wa_bot)
            logger.info(
                "WhatsApp bot initialised — webhook: %s/webhooks/whatsapp",
                settings.api_base_url,
            )
        except Exception as _wa_exc:
            logger.error("WhatsApp bot failed to start: %s", _wa_exc)
            _wa_bot = None
    else:
        _wa_bot = None
        logger.info("WhatsApp bot disabled (TWILIO_* credentials not set)")

    yield

    # WhatsApp: no persistent webhook to deregister (Twilio is config-based)

    # ── Cleanup ──────────────────────────────────────────────────────────────

    # Telegram bot
    if _tg_bot:
        try:
            await _tg_bot.delete_webhook()
        except Exception:
            pass

    # Background tasks
    for task in (trading_task, monitor_task, content_task, email_task, learning_task):
        task.cancel()
    try:
        await asyncio.gather(
            trading_task, monitor_task, content_task, email_task, learning_task,
            return_exceptions=True,
        )
    except Exception:
        pass
    logger.info("Shutting down %s", settings.app_name)


# ─────────────────────────────────────────────
# Background: Trading Loop (every 5 minutes)
# ─────────────────────────────────────────────

async def _trading_loop() -> None:
    """Execute trading cycles for all active users every 5 minutes.

    For each user with active exchange keys and approved assets,
    runs TradingAgent.run_cycle() per symbol.
    """
    logger.info("Trading loop started")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(User).where(User.is_active == True)  # noqa: E712
                )
                active_users = result.scalars().all()

            for user in active_users:
                try:
                    # Determine which assets + exchanges to trade
                    async with AsyncSessionLocal() as db:
                        settings_result = await db.execute(
                            select(UserSettings).where(UserSettings.user_id == user.id)
                        )
                        user_settings = settings_result.scalar_one_or_none()

                    approved = (
                        user_settings.approved_assets
                        if user_settings and user_settings.approved_assets
                        else []
                    )

                    if not approved:
                        continue

                    agent = TradingAgent(user.id)

                    for asset_config in approved:
                        # approved_assets format: [{"symbol": "BTCUSDT", "exchange": "binance"}, ...]
                        if isinstance(asset_config, dict):
                            symbol = asset_config.get("symbol")
                            exchange = asset_config.get("exchange", "binance")
                        else:
                            symbol = str(asset_config)
                            exchange = "binance"

                        if not symbol:
                            continue

                        try:
                            result = await agent.run_cycle(symbol, exchange)
                            logger.info(
                                "Trading cycle: user=%s symbol=%s status=%s",
                                user.id, symbol, result.get("status"),
                            )
                        except Exception as exc:
                            logger.error(
                                "Trading cycle error: user=%s symbol=%s: %s",
                                user.id, symbol, exc,
                            )

                except Exception as exc:
                    logger.error("Trading loop error for user %s: %s", user.id, exc)

        except Exception as exc:
            logger.error("Trading loop outer error: %s", exc)

        await asyncio.sleep(300)  # 5 minutes


# ─────────────────────────────────────────────
# Background: Content Scheduler
# ─────────────────────────────────────────────

async def _content_scheduler() -> None:
    """Generate marketing content on a daily / weekly / monthly cadence.

    Cadence:
        Daily   — 5 social media posts
        Weekly  — 2 blog posts  (runs on Monday)
        Monthly — 1 major guide (runs on the 1st of the month)

    The scheduler wakes every hour and checks whether tasks are due.
    Last-run timestamps are tracked in memory; on restart all overdue
    tasks run once immediately.
    """
    logger.info("Content scheduler started — first run in 5 minutes")
    await asyncio.sleep(300)  # wait 5 min before first run so startup is clean

    last_daily: datetime | None = None
    last_weekly: datetime | None = None
    last_monthly: datetime | None = None

    while True:
        try:
            now = datetime.now(timezone.utc)

            # ── Daily social posts ────────────────────────────────────────
            if last_daily is None or (now - last_daily).total_seconds() >= 86_400:
                try:
                    posts = await generate_daily_posts(count=5)
                    logger.info("Content scheduler: generated %d daily social posts", len(posts))
                    last_daily = now
                except Exception as exc:
                    logger.error("Daily social post generation failed: %s", exc)

            # ── Weekly blog posts (run on Monday or first boot) ───────────
            is_monday = now.weekday() == 0
            if last_weekly is None or (is_monday and (now - last_weekly).total_seconds() >= 86_400):
                try:
                    posts = await generate_weekly_posts(count=2)
                    logger.info("Content scheduler: generated %d weekly blog posts", len(posts))
                    last_weekly = now
                except Exception as exc:
                    logger.error("Weekly blog generation failed: %s", exc)

            # ── Monthly guide (run on 1st of month or first boot) ─────────
            is_first = now.day == 1
            if last_monthly is None or (is_first and (now - last_monthly).total_seconds() >= 86_400):
                try:
                    guide = await generate_monthly_guide()
                    logger.info("Content scheduler: monthly guide generated — '%s'", guide.get("title"))
                    last_monthly = now
                except Exception as exc:
                    logger.error("Monthly guide generation failed: %s", exc)

        except Exception as exc:
            logger.error("Content scheduler outer error: %s", exc)

        await asyncio.sleep(3_600)  # check every hour


# ─────────────────────────────────────────────
# Background: Trial Email Scheduler (daily at 9am UTC)
# ─────────────────────────────────────────────

async def _email_scheduler() -> None:
    """Send trial drip emails daily at 09:00 UTC.

    On startup, calculates seconds until next 9am UTC and sleeps until then,
    then runs every 24 hours.
    """
    logger.info("Trial email scheduler started")

    while True:
        try:
            now = datetime.now(timezone.utc)
            # Next 9am UTC
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= target:
                from datetime import timedelta as _td
                target = target + _td(days=1)
            sleep_secs = (target - now).total_seconds()
            logger.info("Trial email scheduler: sleeping %.0fs until %s UTC", sleep_secs, target)
            await asyncio.sleep(sleep_secs)
        except asyncio.CancelledError:
            return

        try:
            await send_trial_emails_for_all_users()
        except Exception as exc:
            logger.error("Trial email scheduler error: %s", exc)

        await asyncio.sleep(1)  # small buffer before recalculating next target


# ─────────────────────────────────────────────
# Background: Learning Hub (every hour)
# ─────────────────────────────────────────────

async def _learning_scheduler() -> None:
    """Run LearningHub.analyze_all_data() every hour.

    On startup, waits 10 minutes to allow the server to fully initialise
    and accumulate initial trade/content data, then runs every 60 minutes.
    """
    logger.info("Learning hub scheduler started — first run in 10 minutes")
    # Startup delay: let server and other agents warm up
    await asyncio.sleep(600)

    while True:
        try:
            summary = await learning_hub.analyze_all_data()
            logger.info(
                "Learning hub cycle: %d patterns, %d instructions, %.1fs",
                summary.get("patterns_found", 0),
                summary.get("instructions_sent", 0),
                summary.get("duration_s", 0),
            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Learning hub scheduler error: %s", exc)

        try:
            await asyncio.sleep(3_600)  # run every hour
        except asyncio.CancelledError:
            return


# ─────────────────────────────────────────────
# App Initialisation
# ─────────────────────────────────────────────

app = FastAPI(
    title="Unitrader API",
    description="Personal AI Trading Companion Platform",
    version=settings.app_version,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

# Attach rate limiter to app state
app.state.limiter = limiter

# ─────────────────────────────────────────────
# Middleware (order matters — outermost first)
# ─────────────────────────────────────────────

# HTTPS redirect — NOT added here because Railway terminates SSL at the proxy
# level and forwards plain HTTP internally. Adding HTTPSRedirectMiddleware would
# cause Railway's health checks (http://localhost:8000/health) to get 301s and fail.

# Trusted hosts — allow our domain, Railway's internal hostnames, and localhost
if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "unitrader.ai",
            "*.unitrader.ai",
            "*.up.railway.app",
            "localhost",
            "127.0.0.1",
        ],
    )

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# Request logging
app.add_middleware(RequestLoggingMiddleware)

# Rate limiting
app.add_middleware(SlowAPIMiddleware)

# ─────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"status": "error", "error": "Too many requests. Please slow down."},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(loc) for loc in e["loc"]), "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"status": "error", "error": "Validation failed", "details": errors},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    # Never leak internal details to the client
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "error", "error": "An internal server error occurred"},
    )


# ─────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(trading_router.router)
app.include_router(chat_router.router)
app.include_router(content_router.router)
app.include_router(billing_router.router)
app.include_router(trial_router.router)
app.include_router(learning_router.router)
app.include_router(telegram_webhook_router)
app.include_router(telegram_linking_router)
app.include_router(whatsapp_webhook_router)
app.include_router(whatsapp_linking_router)


# ─────────────────────────────────────────────
# Root
# ─────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    """Health check / welcome endpoint."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "docs": "/docs",
    }
