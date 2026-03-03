"""
routers/health.py — Health check endpoints for Unitrader.

Endpoints:
    GET /health           — Basic application liveness
    GET /health/database  — Database connectivity
    GET /health/ai        — Anthropic Claude API connectivity
    GET /health/email     — Resend email API connectivity
    GET /health/payment   — Stripe API connectivity
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from schemas import HealthResponse, ServiceStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])


# ─────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────

@router.get("", response_model=HealthResponse, summary="Application liveness")
async def health_check():
    """Return basic application status. Always 200 if the server is running."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
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
        db_status = ServiceStatus(status="error", detail=str(exc)[:200])

    overall = "healthy" if db_status.status == "healthy" else "degraded"
    return HealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc),
        services={"database": db_status},
    )


@router.get("/database/debug", summary="Database debug — shows exact error and URL shape")
async def database_debug():
    """Temporary debug endpoint — shows DB URL shape and exact connection error."""
    import re
    from database import _db_url, _engine_kwargs
    from config import settings

    # Mask password in URL for safe display
    masked = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", _db_url)
    connect_args = _engine_kwargs.get("connect_args", {})

    # Try connecting directly
    error_detail = None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text as sql_text
        engine = create_async_engine(_db_url, connect_args=connect_args, pool_pre_ping=True)
        async with engine.connect() as conn:
            result = await conn.execute(sql_text("SELECT version()"))
            version = result.fetchone()[0]
        await engine.dispose()
        return {
            "status": "connected",
            "db_url_shape": masked,
            "connect_args": str(connect_args),
            "pg_version": str(version)[:80],
        }
    except Exception as exc:
        error_detail = str(exc)

    return {
        "status": "error",
        "db_url_shape": masked,
        "connect_args": str(connect_args),
        "error": error_detail[:300] if error_detail else None,
    }


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
            model="claude-3-haiku-20240307",
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}],
        )
        ai_status = ServiceStatus(status="healthy")
    except Exception as exc:
        logger.error("Anthropic health check failed: %s", exc)
        ai_status = ServiceStatus(status="error", detail=f"Anthropic error: {str(exc)[:80]}")

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
