"""
main.py — FastAPI application entry point for Unitrader.

Wires together all middleware, routers, error handlers, and startup logic.
Run with:  python -m uvicorn main:app --reload
"""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import sentry_sdk
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from database import AsyncSessionLocal, create_tables
from models import ExchangeAPIKey, User, UserSettings
from routers import auth, health
from routers import trading as trading_router
from routers import chat as chat_router
from routers import content as content_router
from routers import billing as billing_router
from routers import trial as trial_router
from routers import learning as learning_router
from routers import onboarding as onboarding_router
from routers import ws as ws_router
from routers import exchanges as exchanges_router
from routers import goals as goals_router
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
from src.error_handling import configure_third_party_loggers, http_exception_handler
from src.agents.orchestrator import get_orchestrator
from src.agents.marketing.content_writer import generate_weekly_posts, generate_monthly_guide
from backend.agents.content_agent import ContentAgent
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
configure_third_party_loggers()
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


class EnforceHTTPSMiddleware(BaseHTTPMiddleware):
    """Redirect external HTTP traffic to HTTPS in production.

    Railway health checks hit localhost over plain HTTP inside the container,
    so those requests must bypass redirects.
    """

    async def dispatch(self, request: Request, call_next):
        if settings.is_production:
            forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
            host = request.headers.get("host", "").lower()
            is_local = host.startswith("localhost") or host.startswith("127.0.0.1")

            if forwarded_proto == "http" and not is_local:
                target = str(request.url).replace("http://", "https://", 1)
                return RedirectResponse(url=target, status_code=status.HTTP_308_PERMANENT_REDIRECT)

        return await call_next(request)


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
    try:
        await create_tables()
    except Exception as _db_exc:
        logger.error("Database init failed (app will still start): %s", _db_exc)

    # 2. Verify Anthropic API key is present
    if settings.anthropic_api_key:
        logger.info("Anthropic API key: configured")
    else:
        logger.warning("Anthropic API key: NOT configured — AI features disabled")

    # 3. Verify database configuration
    _db_url_display = settings.database_url[:40] + "..." if len(settings.database_url) > 40 else settings.database_url
    if "sqlite" in settings.database_url:
        logger.warning(
            "DATABASE WARNING: Using SQLite (%s). "
            "Set DATABASE_URL to a PostgreSQL/Supabase connection string for production. "
            "Data will NOT persist across deploys with SQLite.",
            _db_url_display,
        )
    else:
        logger.info("Database: PostgreSQL configured (%s)", _db_url_display)

    if settings.supabase_url:
        logger.info("Supabase: configured at %s", settings.supabase_url)
    else:
        logger.warning(
            "Supabase: SUPABASE_URL not set. "
            "If using Supabase, also set SUPABASE_SERVICE_ROLE_KEY."
        )

    # 4. Launch background loops
    trading_task  = asyncio.create_task(_trading_loop(),       name="trading_loop")
    monitor_task  = asyncio.create_task(monitor_loop(),        name="monitor_loop")
    content_task  = asyncio.create_task(_content_scheduler(),  name="content_scheduler")
    email_task    = asyncio.create_task(_email_scheduler(),    name="email_scheduler")
    learning_task = asyncio.create_task(_learning_scheduler(), name="learning_scheduler")
    goals_task    = asyncio.create_task(_goals_scheduler(),    name="goals_scheduler")
    logger.info(
        "Background loops started "
        "(trading=5min, monitoring=1min, content=daily, emails=daily@9am, learning=hourly, goals=weekly@8am)"
    )

    # 5. Initialise Telegram bot (optional — disabled if token not set)
    if settings.telegram_enabled:
        try:
            from src.integrations.telegram_bot import TelegramBotService
            _tg_bot = TelegramBotService(token=settings.telegram_bot_token)
            await _tg_bot.initialize()
            set_telegram_bot_service(_tg_bot)
            webhook_url = f"{settings.api_base_url}/webhooks/telegram"
            logger.info("Setting Telegram webhook → %s", webhook_url)
            try:
                await _tg_bot.set_webhook(webhook_url)
            except Exception as _wh_exc:
                logger.error(
                    "Telegram webhook registration failed (bot still usable via polling): %s  "
                    "Ensure API_BASE_URL env var is a publicly reachable HTTPS URL (current: %s)",
                    _wh_exc, settings.api_base_url,
                )
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
    for task in (trading_task, monitor_task, content_task, email_task, learning_task, goals_task):
        task.cancel()
    try:
        await asyncio.gather(
            trading_task, monitor_task, content_task, email_task, learning_task, goals_task,
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
    runs TradingAgent.run_cycle() per symbol. Users without exchange
    keys are skipped with a debug log rather than an error.
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
                    async with AsyncSessionLocal() as db:
                        settings_result = await db.execute(
                            select(UserSettings).where(UserSettings.user_id == user.id)
                        )
                        user_settings = settings_result.scalar_one_or_none()

                        keys_result = await db.execute(
                            select(ExchangeAPIKey.exchange).where(
                                ExchangeAPIKey.user_id == user.id,
                                ExchangeAPIKey.is_active == True,  # noqa: E712
                            )
                        )
                        connected_exchanges = {row[0] for row in keys_result.all()}

                    if not connected_exchanges:
                        logger.debug("User %s has no exchange keys — skipping trading loop", user.id)
                        continue

                    approved = (
                        user_settings.approved_assets
                        if user_settings and user_settings.approved_assets
                        else []
                    )

                    if not approved:
                        continue

                    trade_mode = (user_settings.trade_mode or "auto") if user_settings else "auto"
                    trading_paused = (user_settings.trading_paused or False) if user_settings else False

                    if trading_paused:
                        logger.debug("Trading loop: user=%s trading paused — skipping", user.id)
                        continue

                    from src.agents.core.trading_agent import TradingAgent
                    from src.agents.shared_memory import SharedContext, SharedMemory

                    agent = TradingAgent(user_id=user.id)

                    if trade_mode in ("auto", "guided"):
                        # Full autopilot: analyse + execute for each approved symbol
                        for exchange in connected_exchanges:
                            exchange_symbols = [s for s in approved if s]
                            if not exchange_symbols:
                                continue
                            # Only run one symbol per exchange per cycle (avoid over-trading)
                            symbol = exchange_symbols[0]
                            try:
                                result = await agent.run_cycle(
                                    symbol=symbol,
                                    exchange_name=exchange,
                                )
                                logger.info(
                                    "Trading loop: user=%s exchange=%s symbol=%s status=%s",
                                    user.id, exchange, symbol, result.get("status"),
                                )
                            except Exception as exc:
                                logger.error(
                                    "Trading loop: run_cycle failed user=%s symbol=%s: %s",
                                    user.id, symbol, exc,
                                )

                    elif trade_mode == "picks":
                        # AI Picks mode: use dynamic universe pre-scoring, notify user of top opportunities
                        from routers.telegram_webhooks import get_telegram_bot_service
                        from routers.whatsapp_webhooks import get_whatsapp_bot_service
                        from src.agents.shared_memory import SharedMemory
                        from src.watchlists import score_universe
                        from sqlalchemy import select as _select

                        for exchange in connected_exchanges:
                            symbols = await score_universe(exchange, top_n=10)
                            if not symbols:
                                continue

                            async with AsyncSessionLocal() as _db:
                                ctx = await SharedMemory.load(user.id, _db)
                            if ctx is None:
                                ctx = SharedContext.default(user.id)
                            ctx.exchange = exchange

                            picks = []
                            for sym in symbols:
                                try:
                                    result = await agent.analyze(symbol=sym, exchange=exchange, context=ctx)
                                    if result and result.signal in ("buy", "sell"):
                                        picks.append({
                                            "symbol": sym,
                                            "signal": result.signal.upper(),
                                            "confidence": result.confidence,
                                            "reasoning": (result.explanation_expert or "")[:200],
                                        })
                                except Exception:
                                    pass

                            picks.sort(key=lambda p: p["confidence"], reverse=True)
                            top = picks[:3]

                            if not top:
                                continue

                            # Build notification message
                            lines = [f"🔍 Your AI found {len(top)} opportunity{'s' if len(top) > 1 else ''}:"]
                            for i, p in enumerate(top, 1):
                                em = "📈" if p["signal"] == "BUY" else "📉"
                                lines.append(f"{i}) {em} {p['signal']} {p['symbol']} — {p['confidence']:.0f}% confidence")
                            lines.append("\nOpen the app to review and trade.")
                            msg = "\n".join(lines)

                            # Send to connected platforms
                            async with AsyncSessionLocal() as _db:
                                from models import UserExternalAccount
                                ext_rows = (await _db.execute(
                                    _select(UserExternalAccount).where(
                                        UserExternalAccount.user_id == user.id,
                                        UserExternalAccount.is_linked == True,  # noqa: E712
                                    )
                                )).scalars().all()

                            tg_bot = get_telegram_bot_service()
                            wa_bot = get_whatsapp_bot_service()

                            for ext in ext_rows:
                                try:
                                    if ext.platform == "telegram" and tg_bot and tg_bot.app:
                                        await tg_bot.app.bot.send_message(
                                            chat_id=ext.external_id, text=msg
                                        )
                                    elif ext.platform == "whatsapp" and wa_bot:
                                        await wa_bot.send_message(ext.external_id, msg)
                                except Exception as _exc:
                                    logger.debug("picks notify failed for %s: %s", ext.platform, _exc)

                            logger.info(
                                "Trading loop (picks): user=%s exchange=%s found %d picks",
                                user.id, exchange, len(top),
                            )
                    else:
                        logger.debug("Trading loop: user=%s trade_mode=%s — no action", user.id, trade_mode)

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
    last_learning_weekly: datetime | None = None

    while True:
        try:
            now = datetime.now(timezone.utc)

            # ── Daily social posts ────────────────────────────────────────
            if last_daily is None or (now - last_daily).total_seconds() >= 86_400:
                try:
                    async with AsyncSessionLocal() as db:
                        # TODO: Update background content loop to use new orchestrator.route()
                        # with action="content_create"
                        # orchestrator = get_orchestrator()
                        # orch = await orchestrator.route(
                        #     user_id="system",
                        #     action="content_create",
                        #     payload={"content_type": "social", "topic": "Daily market trends", "count": 5},
                        #     db=db,
                        # )
                        # posts = orch.get("posts", []) if isinstance(orch, dict) else []
                        posts = []
                        await db.commit()
                    logger.info("Content scheduler: daily social posts (disabled pending orchestrator migration)")
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

            # ── Weekly learning articles (Phase 14): Monday 06:00 UTC ─────
            is_monday_6 = now.weekday() == 0 and now.hour == 6
            if last_learning_weekly is None or (is_monday_6 and (now - last_learning_weekly).total_seconds() >= 86_400):
                try:
                    async with AsyncSessionLocal() as db:
                        agent = ContentAgent()
                        # 1) Weekly recap
                        await agent.generate_learning_article("weekly_recap", [])

                        # 2) Most-used indicator from last week's audit logs (best-effort)
                        since = now - timedelta(days=7)
                        res = await db.execute(
                            select(AuditLog.event_details)
                            .where(AuditLog.event_type == "trade_decision", AuditLog.timestamp >= since)
                        )
                        indicator_counts: dict[str, int] = {}
                        for (d,) in res.all():
                            if not isinstance(d, dict):
                                continue
                            ind = d.get("indicator") or d.get("primary_indicator")
                            if not ind:
                                continue
                            k = str(ind).strip()
                            indicator_counts[k] = indicator_counts.get(k, 0) + 1
                        most_used = max(indicator_counts.items(), key=lambda kv: kv[1])[0] if indicator_counts else "RSI"
                        await agent.generate_learning_article("concept_explanation", [most_used])

                    logger.info("Content scheduler: generated weekly learning articles")
                    last_learning_weekly = now
                except Exception as exc:
                    logger.error("Weekly learning article generation failed: %s", exc)

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
# Background: Goals Scheduler (every Monday 8am UTC)
# ─────────────────────────────────────────────

async def _goals_scheduler() -> None:
    """Send weekly goal progress reports every Monday at 8am UTC.

    The scheduler wakes every minute to check if it's Monday 8am UTC.
    Reports are generated for all users with subscription_active=True.
    """
    from datetime import datetime as dt, timezone as tz

    logger.info("Goals scheduler started — will run every Monday at 08:00 UTC")
    await asyncio.sleep(300)  # wait 5 min before first run so startup is clean

    last_run: datetime | None = None

    while True:
        try:
            now = dt.now(tz.utc)

            # Check if it's Monday (0 = Monday, 6 = Sunday) at 8am UTC
            is_monday = now.weekday() == 0
            is_8am = 8 <= now.hour < 9
            should_run = is_monday and is_8am and (
                last_run is None or (now - last_run).total_seconds() >= 3_600
            )

            if should_run:
                from src.agents.goal_tracking_agent import GoalTrackingAgent

                agent = GoalTrackingAgent()

                # Get all active users
                async with AsyncSessionLocal() as db:
                    from sqlalchemy import select as sa_select

                    settings_rows = (
                        await db.execute(
                            sa_select(UserSettings).where(
                                UserSettings.subscription_active == True  # noqa: E712
                            )
                        )
                    ).scalars().all()

                    count = 0
                    for setting in settings_rows:
                        try:
                            await agent.generate_progress_report(setting.user_id, db)
                            count += 1
                        except Exception as exc:
                            logger.error(
                                "Goals report error for user %s: %s", setting.user_id, exc
                            )

                    logger.info("Goals scheduler: sent %d reports", count)
                    last_run = now

        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Goals scheduler error: %s", exc)

        try:
            await asyncio.sleep(60)  # check every minute
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

# HTTPS enforcement for external traffic only (safe for Railway internal health
# checks, which originate from localhost over plain HTTP).
app.add_middleware(EnforceHTTPSMiddleware)

# TrustedHostMiddleware intentionally omitted — Railway's reverse proxy handles
# host validation externally. Adding it here would block Railway's internal
# health checks which use the container IP as the Host header.

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


@app.exception_handler(HTTPException)
async def unitrader_http_exception_handler(request: Request, exc: HTTPException):
    return http_exception_handler(request, exc)


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
    error_id = str(uuid.uuid4()) if settings.is_production else None
    logger.exception(
        "Unhandled exception on %s %s error_id=%s",
        request.method,
        request.url.path,
        error_id or "n/a",
    )
    content: dict = {"status": "error", "error": "An internal server error occurred"}
    if error_id:
        content["error_id"] = error_id
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=content,
    )


# ─────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(trading_router.router)
app.include_router(trading_router.performance_router)
app.include_router(trading_router.trades_router)
app.include_router(exchanges_router.router)
app.include_router(chat_router.router)
app.include_router(content_router.router)
app.include_router(billing_router.router)
app.include_router(trial_router.router)
app.include_router(learning_router.router)
app.include_router(onboarding_router.router)
app.include_router(ws_router.router)
app.include_router(goals_router.router)
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
