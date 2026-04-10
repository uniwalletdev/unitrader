"""
main.py — FastAPI application entry point for Unitrader.

Wires together all middleware, routers, error handlers, and startup logic.
Run with:  python -m uvicorn main:app --reload
"""

import asyncio
import logging
import os
import secrets
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytz
import sentry_sdk
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import and_, or_, select, func
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from database import AsyncSessionLocal, create_tables
from models import (
    ApexSelectsApprovalToken,
    AuditLog,
    ExchangeAPIKey,
    SignalScanRun,
    SignalStack,
    TradingAccount,
    Trade,
    TradeUndoToken,
    User,
    UserSettings,
)
from routers import auth, health
from routers import trading as trading_router
from routers import chat as chat_router
from routers import content as content_router
from routers import billing as billing_router
from routers import trial as trial_router
from routers import learning as learning_router
from routers import onboarding as onboarding_router
from routers import notifications as notifications_router
from routers import ws as ws_router
from routers import exchanges as exchanges_router
from routers import goals as goals_router
from routers import signals as signals_router
from routers import admin as admin_router
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
from src.agents.signal_stack_agent import signal_stack_agent
from src.agents.shared_memory import SharedContext, SharedMemory
from src.agents.marketing.content_writer import generate_weekly_posts, generate_monthly_guide
from src.agents.sentiment_agent import SentimentAgent
from backend.agents.content_agent import ContentAgent
from src.integrations.market_data import classify_asset, full_market_analysis
from src.market_context import ExchangeAssetClassError
from src.services.trade_monitoring import is_key_in_backoff, monitor_loop
from src.services.email_sequences import send_trial_emails_for_all_users
from src.services.learning_hub import learning_hub
from src.services.unitrader_notifications import (
    UnitraderNotificationEngine,
    get_unitrader_notification_engine,
    set_unitrader_notification_engine,
)

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────


class _MaxLevelFilter(logging.Filter):
    """Allow records up to and including a maximum level."""

    def __init__(self, max_level: int):
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


_log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.DEBUG if settings.debug else logging.INFO)
_stdout_handler.setFormatter(logging.Formatter(_log_format))
_stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))

_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setLevel(logging.WARNING)
_stderr_handler.setFormatter(logging.Formatter(_log_format))

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    handlers=[_stdout_handler, _stderr_handler],
    force=True,
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

    # 2b. Alpaca (paper + optional live) — same booleans market_data uses for data API headers
    _alpaca_paper_key = bool((settings.alpaca_paper_api_key or "").strip())
    _alpaca_paper_secret = bool((settings.alpaca_paper_api_secret or "").strip())
    logger.info(
        "Alpaca paper: Key configured=%s, Secret configured=%s (set on the Python API service in Railway; redeploy after changing variables)",
        _alpaca_paper_key,
        _alpaca_paper_secret,
    )
    if not _alpaca_paper_key or not _alpaca_paper_secret:
        logger.warning(
            "Alpaca paper credentials missing — stock/crypto market data and server-side Alpaca calls will fail until "
            "ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET (or legacy ALPACA_API_KEY / ALPACA_API_SECRET) are set."
        )
    else:
        # Optional Massive probe (news / legacy); primary quotes use Alpaca + Coinbase + yfinance.
        _massive_key = (settings.massive_api_key or "").strip()
        if _massive_key:
            try:
                import httpx as _httpx
                _probe_url = (
                    (settings.massive_base_url or "https://api.massive.com").rstrip("/")
                    + "/v2/aggs/ticker/AAPL/prev"
                )
                _probe_headers = {"Authorization": f"Bearer {_massive_key}"}
                async with _httpx.AsyncClient(timeout=8.0, headers=_probe_headers) as _probe_client:
                    _probe_resp = await _probe_client.get(_probe_url)
                if _probe_resp.status_code == 200:
                    logger.info("Massive API key OK — optional news/legacy endpoints available")
                elif _probe_resp.status_code == 401:
                    logger.warning(
                        "MASSIVE_API_KEY invalid or expired (401) — "
                        "news via Massive disabled; set DATA_PROVIDER=yfinance and use Alpaca for data."
                    )
                else:
                    logger.debug("Massive startup probe HTTP %s (non-fatal)", _probe_resp.status_code)
            except Exception as _probe_exc:
                logger.debug("Massive startup probe skipped: %s", _probe_exc)
        else:
            logger.info(
                "MASSIVE_API_KEY not set — using Alpaca/Coinbase/yfinance for market data "
                "(set DATA_PROVIDER=yfinance or alpaca in env).",
            )
    _alpaca_live_key = bool((settings.alpaca_live_api_key or "").strip())
    _alpaca_live_secret = bool((settings.alpaca_live_api_secret or "").strip())
    if _alpaca_live_key and _alpaca_live_secret:
        logger.info("Alpaca live: Key configured=True, Secret configured=True")
    elif _alpaca_live_key or _alpaca_live_secret:
        logger.warning("Alpaca live: incomplete — set both ALPACA_LIVE_API_KEY and ALPACA_LIVE_API_SECRET for live trading")

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

    # 4. Launch background loops (skip in tests / CI to prevent hanging workers)
    _disable_loops = bool(settings.disable_background_loops) or ("PYTEST_CURRENT_TEST" in os.environ)
    if _disable_loops:
        trading_task = monitor_task = content_task = email_task = learning_task = goals_task = None
        full_auto_task = apex_selects_task = morning_briefing_task = daily_digest_task = None
        logger.info("Background loops disabled (tests/CI mode)")
    else:
        trading_task  = asyncio.create_task(_trading_loop(),             name="trading_loop")
        monitor_task  = asyncio.create_task(monitor_loop(),              name="monitor_loop")
        content_task  = asyncio.create_task(_content_scheduler(),        name="content_scheduler")
        email_task    = asyncio.create_task(_email_scheduler(),          name="email_scheduler")
        learning_task = asyncio.create_task(_learning_scheduler(),       name="learning_scheduler")
        goals_task    = asyncio.create_task(_goals_scheduler(),          name="goals_scheduler")
        full_auto_task = asyncio.create_task(full_auto_scanner_loop(),   name="full_auto_scanner_loop")
        apex_selects_task = asyncio.create_task(apex_selects_scanner_loop(), name="apex_selects_scanner_loop")
        morning_briefing_task = asyncio.create_task(morning_briefing_loop(), name="morning_briefing_loop")
        daily_digest_task = asyncio.create_task(daily_digest_loop(),     name="daily_digest_loop")
        logger.info(
            "Background loops started "
            "(trading=5min, monitoring=1min, content=daily, emails=daily@9am, learning=hourly, goals=weekly@8am, full_auto=30min, apex_selects=30min, morning_briefing=hourly, daily_digest=8am)"
        )

    # 5. Initialise Telegram bot (optional — disabled if token not set)
    if (not _disable_loops) and settings.telegram_enabled:
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

    # 5b. Initialise Unitrader notifications engine
    _unitrader_notifications = UnitraderNotificationEngine(
        telegram_bot=_tg_bot,
        whatsapp_bot=None,
        claude_client=None,
    )
    set_unitrader_notification_engine(_unitrader_notifications)
    logger.info("Unitrader notifications engine initialised")

    # 6. Initialise WhatsApp bot (optional — disabled if Twilio creds not set)
    if (not _disable_loops) and settings.whatsapp_enabled:
        try:
            from src.integrations.whatsapp_bot import WhatsAppBotService
            _wa_bot = WhatsAppBotService(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token,
                twilio_whatsapp_number=settings.twilio_whatsapp_number,
            )
            set_whatsapp_bot_service(_wa_bot)
            _unitrader_notifications.whatsapp_bot = _wa_bot
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

    # Price store feeds (Alpaca stocks + Coinbase crypto) — background tasks
    if not _disable_loops:
        try:
            from src.services.price_feed import start_price_feeds

            start_price_feeds()
            logger.info("Price feeds initialised as background tasks")
        except Exception as _pf_exc:
            logger.warning("Price feeds failed to start (non-fatal): %s", _pf_exc)

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
    for task in (
        trading_task,
        monitor_task,
        content_task,
        email_task,
        learning_task,
        goals_task,
        full_auto_task,
        apex_selects_task,
        morning_briefing_task,
        daily_digest_task,
    ):
        if task is not None:
            task.cancel()
    try:
        await asyncio.gather(
            *[t for t in (
                trading_task,
                monitor_task,
                content_task,
                email_task,
                learning_task,
                goals_task,
                full_auto_task,
                apex_selects_task,
                morning_briefing_task,
                daily_digest_task,
            ) if t is not None],
            return_exceptions=True,
        )
    except Exception:
        pass
    logger.info("Shutting down %s", settings.app_name)


# ─────────────────────────────────────────────
# Background: Trading Loop (every 5 minutes)
# ─────────────────────────────────────────────


def is_market_open() -> bool:
    """True if US stock market session is open (Mon–Fri 09:30–16:00 America/New_York)."""
    et = pytz.timezone("America/New_York")
    now_et = datetime.now(et)
    if now_et.weekday() >= 5:
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close


def is_market_open_for_asset_class(asset_class: str) -> bool:
    """Check whether the market for a given asset class is currently open.

    - stocks: Mon–Fri 09:30–16:00 ET
    - crypto: 24/7
    - forex: Sun 17:00 ET – Fri 17:00 ET (continuous)
    """
    if asset_class == "crypto":
        return True
    if asset_class == "forex":
        et = pytz.timezone("America/New_York")
        now_et = datetime.now(et)
        wd = now_et.weekday()
        hour = now_et.hour
        # Closed Fri 17:00 through Sun 17:00 ET
        if wd == 5:  # Saturday
            return False
        if wd == 4 and hour >= 17:  # Friday after 5pm
            return False
        if wd == 6 and hour < 17:  # Sunday before 5pm
            return False
        return True
    # stocks (default)
    return is_market_open()


async def _trading_loop() -> None:
    """Execute trading cycles for all active users every 5 minutes.

    For each user with active exchange keys and approved assets,
    runs TradingAgent.run_cycle() per symbol. Users without exchange
    keys are skipped with a debug log rather than an error.
    """
    logger.info("Trading loop started")
    while True:
        try:
            if not is_market_open():
                logger.info("Trading loop: market closed — skipping cycle")
                await asyncio.sleep(300)
                continue

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
                        from src.market_context import Exchange, MarketContext
                        from src.watchlists import score_universe
                        from sqlalchemy import select as _select

                        for exchange in connected_exchanges:
                            try:
                                market_ctx = MarketContext(
                                    exchange=Exchange(exchange),
                                    is_paper=True,
                                    trading_account_id="system_picks",
                                    user_id=user.id,
                                )
                            except Exception:
                                market_ctx = None

                            symbols = (await score_universe(market_context=market_ctx))[:10]
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

        await asyncio.sleep(300)


# ─────────────────────────────────────────────
# Background: Signal loops and notifications
# ─────────────────────────────────────────────

_signal_sentiment_agent = SentimentAgent()


def _is_market_hours(now: datetime) -> bool:
    return now.weekday() < 5 and 9 <= now.hour < 22


def _is_subscription_active(user: User) -> bool:
    return bool(
        user.subscription_tier in {"pro", "elite"}
        or (
            user.trial_status == "active"
            and user.trial_end_date
            and user.trial_end_date > datetime.now(timezone.utc)
        )
    )


def _is_any_active_user(user: User) -> bool:
    """Return True for any registered active user (free, pro, or elite)."""
    return bool(user.is_active)


def _exchange_for_symbol(symbol: str, asset_class: str) -> str:
    if asset_class == "crypto":
        return "coinbase"
    if asset_class == "forex":
        return "oanda"
    return "alpaca"


async def _analyse_symbol_for_mode(symbol: str, db, exchange_override: str | None = None) -> dict:
    asset_type = classify_asset(symbol)
    asset_class = "stocks"
    if asset_type == "crypto":
        asset_class = "crypto"
    elif asset_type == "forex":
        asset_class = "forex"

    exchange = (exchange_override or _exchange_for_symbol(symbol, asset_class)).lower()
    market_data = await full_market_analysis(symbol, exchange)
    indicators = market_data.get("indicators", {}) or {}
    rsi = indicators.get("rsi")
    macd = signal_stack_agent._classify_macd(indicators.get("macd", {}) or {})
    volume_ratio = signal_stack_agent._volume_ratio(market_data.get("volume"))

    ctx = SharedContext.default("signal-loop")
    if asset_class == "crypto":
        ctx.trader_class = "crypto_native"
    sentiment = await _signal_sentiment_agent.get_sentiment(symbol, ctx)
    convergence = await signal_stack_agent.convergence_engine.score_symbol(
        symbol=symbol,
        asset_class=asset_class,
        existing_market_data=market_data,
        existing_sentiment=sentiment,
        db=db,
    )

    return {
        "symbol": symbol,
        "asset_name": signal_stack_agent._get_asset_name(symbol),
        "asset_class": asset_class,
        "exchange": exchange,
        "signal": convergence["signal"],
        "confidence": convergence["confidence"],
        "reasoning_expert": convergence["reasoning_expert"],
        "reasoning_simple": convergence["reasoning_simple"],
        "reasoning_metaphor": convergence["reasoning_metaphor"],
        "rsi": rsi,
        "macd_signal": macd,
        "volume_ratio": volume_ratio,
        "sentiment_score": sentiment.get("sentiment_score", "neutral"),
        "earnings_days": signal_stack_agent._earnings_days(sentiment.get("earnings_date")),
        "fear_greed_index": sentiment.get("fear_greed_index"),
        "current_price": market_data.get("price"),
        "price_change_24h": market_data.get("price_change_pct"),
        "convergence": convergence,
    }


def _signal_row_from_analysis(analysis: dict, run_id: uuid.UUID) -> SignalStack:
    return SignalStack(
        id=uuid.uuid4(),
        symbol=analysis["symbol"],
        asset_name=analysis["asset_name"],
        asset_class=analysis["asset_class"],
        exchange=analysis["exchange"],
        signal=analysis["signal"],
        confidence=analysis["confidence"],
        reasoning_expert=analysis["reasoning_expert"],
        reasoning_simple=analysis["reasoning_simple"],
        reasoning_metaphor=analysis["reasoning_metaphor"],
        rsi=analysis["rsi"],
        macd_signal=analysis["macd_signal"],
        volume_ratio=analysis["volume_ratio"],
        sentiment_score=analysis["sentiment_score"],
        earnings_days=analysis["earnings_days"],
        fear_greed_index=analysis["fear_greed_index"],
        current_price=analysis["current_price"],
        price_change_24h=analysis["price_change_24h"],
        scan_run_id=run_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=35),
    )


async def _build_daily_digest(user_id: str, db, settings_row: UserSettings) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    trades_result = await db.execute(
        select(Trade).where(Trade.user_id == user_id, Trade.created_at >= since)
    )
    trades = trades_result.scalars().all()
    open_positions_result = await db.execute(
        select(Trade).where(Trade.user_id == user_id, Trade.status == "open")
    )
    open_positions = open_positions_result.scalars().all()
    pnl = sum((trade.profit or 0) - (trade.loss or 0) for trade in trades)
    return {
        "trades_today": len(trades),
        "pnl_today": round(pnl, 2),
        "signals_skipped": 0,
        "open_positions": len(open_positions),
        "watchlist": settings_row.watchlist or [],
    }


async def full_auto_scanner_loop() -> None:
    logger.info("Full Auto scanner loop started")
    while True:
        try:
            # Check per-account asset class instead of global market hours
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(TradingAccount, UserSettings, User)
                    .join(User, User.id == TradingAccount.user_id)
                    .join(UserSettings, UserSettings.user_id == User.id)
                    .where(
                        TradingAccount.auto_trade_enabled == True,  # noqa: E712
                        TradingAccount.is_active == True,  # noqa: E712
                        UserSettings.trading_paused == False,  # noqa: E712
                        User.is_active == True,  # noqa: E712
                    )
                )
                for trading_account, settings_row, user in result.all():
                    # Full Auto is Elite-only (or active trial)
                    if not (
                        user.subscription_tier == "elite"
                        or (
                            user.trial_status == "active"
                            and user.trial_end_date
                            and user.trial_end_date > datetime.now(timezone.utc)
                        )
                    ):
                        continue
                    # Per-account asset class market hours check
                    ac = getattr(trading_account, "asset_class", None) or "stocks"
                    if not is_market_open_for_asset_class(ac):
                        continue
                    try:
                        await _run_auto_scan_for_account(trading_account, settings_row, user, db)
                    except Exception as exc:
                        logger.error("Full Auto scan failed for %s: %s", user.id, exc)
                        sentry_sdk.capture_exception(exc)
        except Exception as exc:
            logger.error("Full Auto scanner loop error: %s", exc)
        await asyncio.sleep(30 * 60)


async def _run_auto_scan_for_account(trading_account: TradingAccount, settings_row: UserSettings, user: User, db) -> None:
    # Per-account Full Auto settings (multiple accounts may run concurrently)
    watchlist = trading_account.watchlist or []
    if not watchlist:
        ex = (trading_account.exchange or "").lower()
        if ex in ("coinbase", "binance"):
            watchlist = ["BTC/USD", "ETH/USD"]
        elif ex == "oanda":
            watchlist = ["EUR_USD", "GBP_USD"]
        else:
            watchlist = ["AAPL", "MSFT", "NVDA"]

    threshold = trading_account.auto_trade_threshold or 80
    max_per_scan = trading_account.auto_trade_max_per_scan or 1
    trades_this_scan = 0
    run_id = uuid.uuid4()
    orchestrator = get_orchestrator()
    notification_engine = get_unitrader_notification_engine()

    for symbol in watchlist:
        if trades_this_scan >= max_per_scan:
            break
        if await is_key_in_backoff(str(user.id), db):
            logger.info("Full Auto skipping %s for %s due to exchange backoff", symbol, user.id)
            continue

        try:
            analysis = await _analyse_symbol_for_mode(symbol, db, exchange_override=trading_account.exchange)
        except Exception as exc:
            logger.warning("Full Auto: skipping %s for %s — analysis failed: %s", symbol, user.id, exc)
            continue
        db.add(_signal_row_from_analysis(analysis, run_id))
        convergence = analysis["convergence"]
        confidence = convergence["confidence"]
        signal = convergence["signal"]

        if signal in ("buy", "sell") and confidence >= threshold:
            try:
                from src.services.signal_notification_dispatch import (
                    dispatch_signal_notification,
                )

                reasoning = str(analysis.get("reasoning_simple", "") or "").strip()
                if len(reasoning) > 200:
                    reasoning = reasoning[:197].rstrip() + "..."
                await dispatch_signal_notification(
                    {
                        "symbol": symbol,
                        "direction": str(signal).upper(),
                        "confidence": int(confidence),
                        "exchange": str(analysis.get("exchange", "") or ""),
                        "price": float(analysis.get("current_price", 0) or 0),
                        "reasoning": reasoning,
                    },
                    db,
                )
            except Exception as exc:
                logger.debug("Signal broadcast failed (non-fatal): %s", exc)

            ctx = await SharedMemory.load(str(user.id), db)
            ctx.exchange = analysis["exchange"]
            result = await orchestrator._trade_execute(  # type: ignore[attr-defined]
                str(user.id),
                ctx,
                {
                    "symbol": symbol,
                    "side": signal.upper(),
                    "amount": settings_row.max_trade_amount or 100,
                    "source": "full_auto",
                    "signal_context": convergence,
                    "trading_account_id": trading_account.id,
                    "is_paper": trading_account.is_paper,
                },
                db,
            )
            if result.get("status") == "executed":
                trades_this_scan += 1
                undo_token = secrets.token_urlsafe(16)
                db.add(
                    TradeUndoToken(
                        token=undo_token,
                        user_id=str(user.id),
                        trade_id=str(result.get("trade_id")),
                        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
                    )
                )
                if notification_engine:
                    await notification_engine.send_auto_trade_executed(
                        user_id=str(user.id),
                        trade={
                            **result,
                            "amount": settings_row.max_trade_amount or 100,
                            "asset_name": analysis["asset_name"],
                            "stop_loss_pct": 2,
                            "take_profit_pct": 5,
                        },
                        convergence=convergence,
                        undo_token=undo_token,
                        db=db,
                    )
        else:
            logger.info(
                "[Full Auto] Skipped %s for %s: signal=%s confidence=%s threshold=%s",
                symbol,
                user.id,
                signal,
                confidence,
                threshold,
            )

    db.add(
        SignalScanRun(
            id=run_id,
            assets_scanned=len(watchlist),
            signals_generated=trades_this_scan,
            triggered_by="full_auto",
        )
    )
    await db.commit()


async def apex_selects_scanner_loop() -> None:
    logger.info("Apex Selects scanner loop started")
    while True:
        try:
            # At least one asset class must be open to warrant scanning
            any_open = is_market_open() or is_market_open_for_asset_class("crypto") or is_market_open_for_asset_class("forex")
            if any_open:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(UserSettings, User)
                        .join(User, User.id == UserSettings.user_id)
                        .where(
                            UserSettings.signal_stack_mode == "apex_selects",
                            UserSettings.trading_paused == False,  # noqa: E712
                            User.is_active == True,  # noqa: E712
                        )
                    )
                    for settings_row, user in result.all():
                        if not _is_subscription_active(user):
                            continue
                        try:
                            await _run_apex_selects_for_user(settings_row, user, db)
                        except Exception as exc:
                            logger.error("Apex Selects failed for %s: %s", user.id, exc)
            else:
                logger.debug("Apex Selects scanner: market closed — skipping scan")
        except Exception as exc:
            logger.error("Apex Selects loop error: %s", exc)
        await asyncio.sleep(30 * 60)


async def _run_apex_selects_for_user(settings_row: UserSettings, user: User, db) -> None:
    threshold = settings_row.apex_selects_threshold or 75
    max_trades = settings_row.apex_selects_max_trades or 2
    allowed_classes = settings_row.apex_selects_asset_classes or ["stocks", "crypto"]
    watchlist = settings_row.watchlist or ["AAPL", "BTC/USD", "NVDA", "TSLA", "ETH/USD"]
    qualifying = []
    run_id = uuid.uuid4()

    for symbol in watchlist:
        try:
            analysis = await _analyse_symbol_for_mode(symbol, db)
        except Exception as exc:
            logger.warning("Apex Selects: skipping %s for %s — analysis failed: %s", symbol, user.id, exc)
            continue
        db.add(_signal_row_from_analysis(analysis, run_id))
        if analysis["asset_class"] not in allowed_classes:
            continue
        # Skip symbols whose asset-class market is currently closed
        if not is_market_open_for_asset_class(analysis["asset_class"]):
            continue
        if (
            analysis["signal"] in ("buy", "sell")
            and analysis["confidence"] >= threshold
        ):
            qualifying.append(
                {
                    "symbol": symbol,
                    "asset_name": analysis["asset_name"],
                    "asset_class": analysis["asset_class"],
                    "exchange": analysis["exchange"],
                    "signal": analysis["signal"],
                    "confidence": analysis["confidence"],
                    "reasoning_expert": analysis["reasoning_expert"],
                    "reasoning_simple": analysis["reasoning_simple"],
                    "reasoning_metaphor": analysis["reasoning_metaphor"],
                    "threshold_used": threshold,
                }
            )
        if len(qualifying) >= max_trades:
            break

    if qualifying:
        approve_token = secrets.token_urlsafe(16)
        db.add(
            ApexSelectsApprovalToken(
                token=approve_token,
                user_id=str(user.id),
                signals_payload={"signals": qualifying},
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        notification_engine = get_unitrader_notification_engine()
        if notification_engine:
            await notification_engine.send_apex_selects_ready(
                user_id=str(user.id),
                selected_signals=qualifying,
                total_scanned=len(watchlist),
                approve_token=approve_token,
                db=db,
            )

    db.add(
        SignalScanRun(
            id=run_id,
            assets_scanned=len(watchlist),
            signals_generated=len(qualifying),
            triggered_by="apex_selects",
        )
    )
    await db.commit()


async def morning_briefing_loop() -> None:
    logger.info("Morning briefing loop started")
    while True:
        try:
            now = datetime.now(timezone.utc)
            current_hour = now.strftime("%H:00")
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(UserSettings, User)
                    .join(User, User.id == UserSettings.user_id)
                    .where(
                        UserSettings.signal_stack_mode == "browse",
                        UserSettings.morning_briefing_enabled == True,  # noqa: E712
                        UserSettings.morning_briefing_time == current_hour,
                        User.is_active == True,  # noqa: E712
                    )
                )
                users = result.all()
                if users and _is_market_hours(now):
                    await signal_stack_agent.run_scan(db, triggered_by="morning_briefing")

                signals_result = await db.execute(
                    select(SignalStack)
                    .where(
                        SignalStack.expires_at > now,
                        SignalStack.signal.in_(["buy", "sell"]),
                        SignalStack.confidence >= 65,
                    )
                    .order_by(SignalStack.confidence.desc())
                    .limit(5)
                )
                top_signals = signals_result.scalars().all()
                notification_engine = get_unitrader_notification_engine()
                for settings_row, user in users:
                    if not _is_any_active_user(user) or not top_signals or not notification_engine:
                        continue
                    await notification_engine.send_browse_morning_briefing(
                        user_id=str(user.id),
                        top_signals=[
                            {
                                "symbol": signal.symbol,
                                "asset_name": signal.asset_name,
                                "signal": signal.signal,
                                "confidence": signal.confidence,
                                "reasoning_simple": signal.reasoning_simple,
                            }
                            for signal in top_signals[:3]
                        ],
                        total_scanned=len(top_signals),
                        trader_class=settings_row.trader_class or "complete_novice",
                        db=db,
                    )
                await db.commit()
        except Exception as exc:
            logger.error("Morning briefing loop error: %s", exc)
        await asyncio.sleep(60 * 60)


async def daily_digest_loop() -> None:
    logger.info("Daily digest loop started")
    while True:
        try:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(UserSettings, User)
                    .join(User, User.id == UserSettings.user_id)
                    .where(
                        User.is_active == True,  # noqa: E712
                    )
                )
                notification_engine = get_unitrader_notification_engine()
                for settings_row, user in result.all():
                    if not _is_subscription_active(user) or not notification_engine:
                        continue
                    # Only send digest if the user has any Full Auto-enabled account.
                    enabled_count = await db.execute(
                        select(func.count())
                        .select_from(TradingAccount)
                        .where(
                            TradingAccount.user_id == str(user.id),
                            TradingAccount.auto_trade_enabled == True,  # noqa: E712
                            TradingAccount.is_active == True,  # noqa: E712
                        )
                    )
                    if int(enabled_count.scalar() or 0) <= 0:
                        continue
                    digest = await _build_daily_digest(str(user.id), db, settings_row)
                    await notification_engine.send_daily_digest(
                        user_id=str(user.id),
                        digest=digest,
                        db=db,
                    )
                await db.commit()
        except Exception as exc:
            logger.error("Daily digest loop error: %s", exc)
            await asyncio.sleep(60)


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

                    rows = (
                        await db.execute(
                            sa_select(UserSettings, User).join(
                                User, User.id == UserSettings.user_id
                            )
                        )
                    ).all()

                    count = 0
                    for setting, user in rows:
                        if not _is_subscription_active(user):
                            continue
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
    # Always emit to normal logs so Railway/Sentry captures it even if file write fails.
    try:
        logger.warning(
            "RequestValidationError on %s %s fields=%s",
            request.method,
            request.url.path,
            [e.get("field") for e in errors],
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"status": "error", "error": "Validation failed", "details": errors},
    )


@app.exception_handler(ExchangeAssetClassError)
async def exchange_asset_class_error_handler(request: Request, exc: ExchangeAssetClassError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "code": exc.error_code,
            "exchange": exc.exchange.value,
            "symbol": exc.symbol,
            "asset_class": exc.asset_class.value,
        },
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
app.include_router(notifications_router.router)
app.include_router(ws_router.router)
app.include_router(goals_router.router)
app.include_router(signals_router.router)
app.include_router(admin_router.router)
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
