"""
routers/onboarding.py — Onboarding and user agreement endpoints.

Endpoints:
    POST /api/onboarding/accept-risk-disclosure  — Accept risk disclosure
    GET  /api/onboarding/trust-ladder            — Trust ladder status (frontend)
    GET  /api/onboarding/trust-ladder/status     — Alias
    POST /api/onboarding/trust-ladder/advance    — Advance to next trust ladder stage
    POST /api/onboarding/complete-wizard         — Mark onboarding complete after wizard
    POST /api/onboarding/skip                    — Skip onboarding using sensible defaults
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


async def _trust_ladder_data(current_user: User, db: AsyncSession) -> dict:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    s = result.scalar_one_or_none()
    stage = 1
    if s and getattr(s, "risk_disclosure_accepted", False):
        stage = 2
    if s and getattr(s, "onboarding_complete", False):
        stage = 3
    max_amount = 25 if stage <= 2 else 500
    return {
        "stage": stage,
        # Paper trading active until stage 3 (full trading unlocked)
        "paperEnabled": stage < 3,
        # Can advance from stage 2 once risk disclosure is accepted
        "canAdvance": stage == 2,
        "daysAtStage": 1,
        "paperTradesCount": 0,
        "maxAmountGbp": max_amount,
    }


@router.get("/trust-ladder")
async def get_trust_ladder(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return trust ladder status for the current user."""
    return await _trust_ladder_data(current_user, db)


@router.get("/trust-ladder/status")
async def get_trust_ladder_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Alias of /trust-ladder — some frontend versions call this path."""
    return await _trust_ladder_data(current_user, db)


@router.post("/trust-ladder/advance")
async def advance_trust_ladder(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Advance the user to the next trust ladder stage.

    Stage 1 → 2: Accepts risk disclosure and switches from Watch to Micro Mode.
    Stage 2 → 3: Marks onboarding complete and unlocks full trading.

    Idempotent — calling when already at max stage returns success without error.
    """
    try:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        settings = result.scalar_one_or_none()
        if not settings:
            settings = UserSettings(user_id=current_user.id)
            db.add(settings)

        stage = 1
        if getattr(settings, "risk_disclosure_accepted", False):
            stage = 2
        if getattr(settings, "onboarding_complete", False):
            stage = 3

        if stage >= 3:
            return {"success": True, "stage": stage, "message": "Already at full trading stage"}

        ip_address = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        if stage == 1:
            settings.risk_disclosure_accepted = True
            settings.risk_disclosure_accepted_at = datetime.now(timezone.utc)
            new_stage = 2
            event_type = "trust_ladder_stage_1_to_2"
        else:
            # stage == 2: unlock full trading
            settings.onboarding_complete = True
            new_stage = 3
            event_type = "trust_ladder_stage_2_to_3"

        db.add(AuditLog(
            user_id=current_user.id,
            event_type=event_type,
            event_details={"from_stage": stage, "to_stage": new_stage},
            ip_address=ip_address,
            user_agent=user_agent,
        ))
        await db.commit()

        try:
            from src.agents.shared_memory import SharedMemory
            SharedMemory.invalidate(current_user.id)
        except Exception:
            pass

        logger.info(
            "Trust ladder advance for user %s: stage %d → %d",
            current_user.id, stage, new_stage,
        )
        return {"success": True, "stage": new_stage}

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("advance_trust_ladder error for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=500, detail="Failed to advance trust ladder")


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
