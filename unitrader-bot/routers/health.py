"""
routers/health.py — Health check endpoints for Unitrader.

Endpoints:
    GET /health                  — Basic application liveness
    GET /health/database         — Database connectivity
    GET /health/database-ready   — Background DB table initialisation status
    GET /health/ai               — Anthropic Claude API connectivity
    GET /health/email            — Resend email API connectivity
    GET /health/payment          — Stripe API connectivity
    GET /health/orchestrator     — Agent performance metrics and shared memory summary
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app_state
from config import settings
from database import get_db
from schemas import HealthResponse, ServiceStatus
from src.integrations.alpaca_circuit_breaker import alpaca_breaker
from src.integrations.alpaca_rate_limiter import alpaca_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])


# ─────────────────────────────────────────────
# GET /health/bot-info  (public, no auth)
# ─────────────────────────────────────────────

@router.get("/bot-info", summary="Public bot contact info for deep-link generation")
async def bot_info():
    """Return WhatsApp number and Telegram bot username so the frontend can
    build one-tap deep links (wa.me / t.me) without hardcoding values."""
    return {
        "whatsapp_number": settings.twilio_whatsapp_number or None,
        "telegram_bot_username": settings.telegram_bot_username or None,
        "whatsapp_enabled": settings.whatsapp_enabled,
        "telegram_enabled": settings.telegram_enabled,
    }


# ─────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────

@router.get("", response_model=HealthResponse, summary="Application liveness")
async def health_check():
    """Return basic application status. Always 200 if the server is running."""
    alpaca_key_set = bool((settings.alpaca_paper_api_key or "").strip())
    alpaca_secret_set = bool((settings.alpaca_paper_api_secret or "").strip())
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
        alpaca_rate_limiter={
            "waiting": alpaca_limiter.waiting,
            "tokens": round(alpaca_limiter.tokens, 2),
        },
        alpaca_credentials={
            "paper_key_configured": alpaca_key_set,
            "paper_secret_configured": alpaca_secret_set,
            "status": "ok" if (alpaca_key_set and alpaca_secret_set) else "missing",
        },
        alpaca_circuit_breaker=alpaca_breaker.status_dict(),
    )


# ─────────────────────────────────────────────
# GET /health/database
# ─────────────────────────────────────────────

@router.get("/database", response_model=HealthResponse, summary="Database connectivity")
async def database_health(db: AsyncSession = Depends(get_db)):
    """Verify that the database can accept connections and execute queries."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = ServiceStatus(status="healthy")
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        db_status = ServiceStatus(status="error", detail="database_unreachable")

    overall = "healthy" if db_status.status == "healthy" else "degraded"
    return HealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc),
        services={"database": db_status},
    )



# ─────────────────────────────────────────────
# GET /health/database-ready
# ─────────────────────────────────────────────

@router.get("/database-ready", response_model=HealthResponse, summary="Database table initialisation status")
async def database_ready_health():
    """Report whether the background database table initialisation task has completed.

    Returns 200 with status 'ready' once tables are initialised, 'initialising'
    while the background task is still running, or 'failed' if all retry attempts
    were exhausted.  This endpoint never blocks — it reads in-memory state only.
    """
    if app_state.db_init_complete:
        db_status = ServiceStatus(status="healthy", detail="tables_initialised")
        overall = "healthy"
    elif app_state.db_init_failed:
        db_status = ServiceStatus(status="error", detail="init_failed_all_retries_exhausted")
        overall = "degraded"
    else:
        db_status = ServiceStatus(status="initialising", detail="background_task_running")
        overall = "initialising"

    return HealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc),
        services={"database_init": db_status},
    )


# ─────────────────────────────────────────────
# GET /health/ai
# ─────────────────────────────────────────────

@router.get("/ai", response_model=HealthResponse, summary="Anthropic Claude API connectivity")
async def ai_health():
    """Verify that the Anthropic API key is configured and the API is reachable."""
    if not settings.anthropic_api_key:
        ai_status = ServiceStatus(status="error", detail="ANTHROPIC_API_KEY not configured")
        return HealthResponse(
            status="degraded",
            timestamp=datetime.now(timezone.utc),
            services={"ai": ai_status},
        )

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        # Minimal call to verify key validity
        await client.messages.create(
            model=settings.anthropic_model_fast,
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}],
        )
        ai_status = ServiceStatus(status="healthy")
    except Exception as exc:
        logger.error("Anthropic health check failed: %s", exc)
        ai_status = ServiceStatus(status="error", detail="anthropic_unreachable")

    overall = "healthy" if ai_status.status == "healthy" else "degraded"
    return HealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc),
        services={"ai": ai_status},
    )


# ─────────────────────────────────────────────
# GET /health/email
# ─────────────────────────────────────────────

@router.get("/email", response_model=HealthResponse, summary="Resend email API connectivity")
async def email_health():
    """Verify that the Resend API key is configured."""
    if not settings.resend_api_key:
        email_status = ServiceStatus(status="error", detail="RESEND_API_KEY not configured")
        return HealthResponse(
            status="degraded",
            timestamp=datetime.now(timezone.utc),
            services={"email": email_status},
        )

    try:
        import resend
        resend.api_key = settings.resend_api_key
        # Resend has no free ping endpoint; we just verify the SDK loads and key is set
        email_status = ServiceStatus(status="healthy", detail="Resend API key configured")
    except Exception as exc:
        logger.error("Resend health check failed: %s", exc)
        email_status = ServiceStatus(status="error", detail="Resend SDK error")

    overall = "healthy" if email_status.status == "healthy" else "degraded"
    return HealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc),
        services={"email": email_status},
    )


# ─────────────────────────────────────────────
# GET /health/payment
# ─────────────────────────────────────────────

@router.get("/payment", response_model=HealthResponse, summary="Stripe API connectivity")
async def payment_health():
    """Verify that the Stripe API key is configured and the API is reachable."""
    if not settings.stripe_secret_key:
        stripe_status = ServiceStatus(status="error", detail="STRIPE_SECRET_KEY not configured")
        return HealthResponse(
            status="degraded",
            timestamp=datetime.now(timezone.utc),
            services={"payment": stripe_status},
        )

    try:
        import stripe
        stripe.api_key = settings.stripe_secret_key
        stripe.Balance.retrieve()
        stripe_status = ServiceStatus(status="healthy")
    except Exception as exc:
        logger.error("Stripe health check failed: %s", exc)
        stripe_status = ServiceStatus(status="error", detail="Stripe API unreachable")

    overall = "healthy" if stripe_status.status == "healthy" else "degraded"
    return HealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc),
        services={"payment": stripe_status},
    )


# ─────────────────────────────────────────────
# GET /health/orchestrator
# ─────────────────────────────────────────────

@router.get("/orchestrator", summary="Orchestrator and agent performance")
async def orchestrator_health(db: AsyncSession = Depends(get_db)):
    """Return agent performance metrics, shared context summary, and recent outcomes.

    Used for monitoring the symbiotic learning system.
    """
    # TODO: Implement health metrics for new orchestrator
    # get_system_health() not available in new orchestrator API
    try:
        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "agents": ["trading_agent", "conversation_agent", "risk_agent", "portfolio_agent"],
                "note": "Health metrics pending orchestrator v2 implementation",
            },
        }
    except Exception as exc:
        logger.error("Orchestrator health check failed: %s", exc)
        return {
            "status": "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "orchestrator_check_failed",
        }
