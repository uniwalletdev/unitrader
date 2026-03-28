"""
routers/onboarding.py — Onboarding and user agreement endpoints.

Endpoints:
    POST /api/onboarding/accept-risk-disclosure — Accept risk disclosure
    GET  /api/onboarding/trust-ladder          — Trust ladder status (frontend)
    POST /api/onboarding/complete-wizard       — Mark onboarding complete after Apex wizard
    POST /api/onboarding/skip                  — Skip onboarding using sensible defaults
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import AuditLog, User, UserSettings
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["Onboarding"])


@router.get("/trust-ladder")
async def get_trust_ladder(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return trust ladder status for the current user.

    Minimal shape for frontend:
      { stage, paperEnabled, canAdvance, daysAtStage, paperTradesCount, maxAmountGbp }
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    s = result.scalar_one_or_none()
    stage = 1
    if s and getattr(s, "risk_disclosure_accepted", False):
        stage = 2
    # Frontend can decide the rest; keep conservative defaults.
    max_amount = 25 if stage <= 2 else 500
    return {
        "stage": stage,
        "paperEnabled": True,
        "canAdvance": bool(s and getattr(s, "risk_disclosure_accepted", False)),
        "daysAtStage": 1,
        "paperTradesCount": 0,
        "maxAmountGbp": max_amount,
    }


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class AcceptRiskDisclosureResponse(BaseModel):
    """Response after accepting risk disclosure."""
    success: bool
    accepted_at: str  # ISO timestamp


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.post("/accept-risk-disclosure", response_model=AcceptRiskDisclosureResponse)
async def accept_risk_disclosure(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept risk disclosure agreement.

    Requires authentication. No request body needed — the act of calling
    this endpoint is consent. Records IP address and user agent for audit.

    Returns:
        {
            "success": true,
            "accepted_at": "2026-03-14T10:30:00Z"
        }
    """
    try:
        # Get client IP and user agent
        ip_address = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        timestamp = datetime.now(timezone.utc)

        # Fetch user settings
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        user_settings = result.scalar_one_or_none()

        if not user_settings:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User settings not found",
            )

        # Update user settings
        user_settings.risk_disclosure_accepted = True
        user_settings.risk_disclosure_accepted_at = timestamp
        db.add(user_settings)

        # Write to audit log
        audit_log = AuditLog(
            user_id=current_user.id,
            event_type="risk_disclosure_accepted",
            event_details={
                "ip": ip_address,
                "user_agent": user_agent,
                "timestamp": timestamp.isoformat(),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(audit_log)

        # Commit both changes
        await db.commit()

        logger.info(
            "User %s accepted risk disclosure from IP %s",
            current_user.id,
            ip_address,
        )

        return AcceptRiskDisclosureResponse(
            success=True,
            accepted_at=timestamp.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error accepting risk disclosure: %s", e)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept risk disclosure",
        )


# ─────────────────────────────────────────────
# POST /api/onboarding/complete-wizard
# ─────────────────────────────────────────────

class CompleteWizardRequest(BaseModel):
    """Optional profile data gathered by Apex wizard."""
    goal: str | None = None           # grow_savings / generate_income / learn_trading / crypto_focus
    risk_level: str | None = None     # conservative / balanced / aggressive
    budget: float | None = None       # GBP per trade
    exchange: str | None = None       # alpaca / coinbase / oanda
    trader_class: str | None = None   # detected class if available


@router.post("/complete-wizard")
async def complete_wizard(
    body: CompleteWizardRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark onboarding complete after the Apex wizard finishes.

    Called by the frontend when the guided wizard reaches the last stage.
    Persists any profile data collected and sets onboarding_complete = True,
    which unlocks the full trading chat and trade page.
    """
    try:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        settings = result.scalar_one_or_none()
        if not settings:
            settings = UserSettings(user_id=current_user.id)
            db.add(settings)

        settings.onboarding_complete = True
        if body.goal:
            settings.financial_goal = body.goal
        if body.risk_level:
            settings.risk_level_setting = body.risk_level
        if body.budget is not None:
            settings.max_trade_amount = body.budget
        if body.trader_class:
            settings.trader_class = body.trader_class

        db.add(AuditLog(
            user_id=current_user.id,
            event_type="onboarding_complete",
            event_details={
                "source": "apex_wizard",
                "goal": body.goal,
                "risk_level": body.risk_level,
                "budget": body.budget,
                "exchange": body.exchange,
                "trader_class": body.trader_class,
            },
            ip_address=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", "unknown"),
        ))
        await db.commit()

        from src.agents.shared_memory import SharedMemory
        SharedMemory.invalidate(current_user.id)

        logger.info("Onboarding complete (wizard) for user %s", current_user.id)
        return {"success": True, "onboarding_complete": True}

    except Exception as exc:
        await db.rollback()
        logger.error("complete_wizard error for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=500, detail="Failed to complete onboarding")


# ─────────────────────────────────────────────
# POST /api/onboarding/skip
# ─────────────────────────────────────────────

_SKIP_DEFAULTS = {
    "financial_goal": "grow_savings",
    "risk_level_setting": "balanced",
    "max_trade_amount": 100.0,
    "trader_class": "complete_novice",
}


@router.post("/skip")
async def skip_onboarding(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Skip onboarding and apply sensible defaults so the user can trade immediately.

    Marks onboarding_complete = True with conservative defaults.
    The user can update any setting later from the settings page.
    """
    try:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        settings = result.scalar_one_or_none()
        if not settings:
            settings = UserSettings(user_id=current_user.id)
            db.add(settings)

        # Only apply default if the field has not already been set
        for field, default in _SKIP_DEFAULTS.items():
            if not getattr(settings, field, None):
                setattr(settings, field, default)

        settings.onboarding_complete = True
        db.add(AuditLog(
            user_id=current_user.id,
            event_type="onboarding_skipped",
            event_details={"defaults_applied": _SKIP_DEFAULTS},
            ip_address=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", "unknown"),
        ))
        await db.commit()

        from src.agents.shared_memory import SharedMemory
        SharedMemory.invalidate(current_user.id)

        logger.info("Onboarding skipped (defaults) for user %s", current_user.id)
        return {
            "success": True,
            "onboarding_complete": True,
            "message": "You're all set! Conservative defaults applied. Update them anytime in Settings.",
        }

    except Exception as exc:
        await db.rollback()
        logger.error("skip_onboarding error for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=500, detail="Failed to skip onboarding")
