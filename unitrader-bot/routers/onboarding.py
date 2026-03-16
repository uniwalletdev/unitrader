"""
routers/onboarding.py — Onboarding and user agreement endpoints.

Endpoints:
    POST /api/onboarding/accept-risk-disclosure — Accept risk disclosure
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
