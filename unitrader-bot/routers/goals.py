"""
routers/goals.py — Goal tracking and progress reporting endpoints.

Endpoints:
    GET /api/goals/progress  — Generate and return weekly progress report
"""

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from routers.auth import get_current_user
from schemas import SuccessResponse
from src.agents.goal_tracking_agent import GoalTrackingAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/goals", tags=["Goals"])

# Singleton agent instance
_goal_agent = GoalTrackingAgent()


@router.get(
    "/progress",
    response_model=dict,
    summary="Get weekly progress report",
    status_code=status.HTTP_200_OK,
)
async def get_progress_report(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and return the user's weekly progress report.

    Includes:
    - Personalized message (based on trader class)
    - Portfolio change percentage
    - Win rate
    - On-track status (positive P&L)
    - Trader class used for prompt

    Also sends report via Telegram (if linked) and stores as in-app notification.
    """
    try:
        report = await _goal_agent.generate_progress_report(current_user.id, db)
        return {
            "success": True,
            "data": report,
        }
    except Exception as e:
        logger.error("Error generating progress report for user %s: %s", current_user.id, e)
        return {
            "success": False,
            "error": "Failed to generate progress report",
        }
