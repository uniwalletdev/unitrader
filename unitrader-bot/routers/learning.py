"""
routers/learning.py — Learning Hub API endpoints.

Exposes read-only visibility into the pattern discovery system and
a manual trigger for operator/admin use.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import AgentInstruction, AgentOutput, Pattern, User
from routers.auth import get_current_user
from src.services.learning_hub import (
    get_content_insights,
    get_support_insights,
    get_trading_insights,
    learning_hub,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/learning", tags=["learning"])


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/learning/patterns
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/patterns")
async def get_patterns(
    limit: int = 20,
    category: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active learning patterns discovered by the hub.

    Ordered by confidence score descending.
    """
    query = select(Pattern).where(Pattern.is_active == True)  # noqa: E712
    if category:
        query = query.where(Pattern.category == category)
    query = query.order_by(Pattern.confidence_score.desc()).limit(limit)

    result = await db.execute(query)
    patterns = result.scalars().all()

    return {
        "patterns": [
            {
                "id": p.id,
                "pattern_name": p.pattern_name,
                "description": p.description,
                "confidence_score": p.confidence_score,
                "category": p.category,
                "supporting_agents": p.supporting_agents,
                "recommendation": p.recommendation,
                "timestamp": p.timestamp.isoformat() if p.timestamp else None,
                "expires_at": p.expires_at.isoformat() if p.expires_at else None,
            }
            for p in patterns
        ],
        "count": len(patterns),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/learning/instructions/{agent_name}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/instructions/{agent_name}")
async def get_instructions(
    agent_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active instructions for a specific agent."""
    result = await db.execute(
        select(AgentInstruction).where(
            AgentInstruction.agent_name == agent_name,
            AgentInstruction.status == "active",
        ).order_by(AgentInstruction.priority.desc()).limit(5)
    )
    instructions = result.scalars().all()

    return {
        "agent": agent_name,
        "instructions": [
            {
                "id": i.id,
                "instruction": i.instruction,
                "priority": i.priority,
                "source_pattern_id": i.source_pattern_id,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in instructions
        ],
        "count": len(instructions),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/learning/outputs
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/outputs")
async def get_outputs(
    agent_name: str | None = None,
    output_type: str | None = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return recent agent outputs logged to the learning hub."""
    query = select(AgentOutput)
    if agent_name:
        query = query.where(AgentOutput.agent_name == agent_name)
    if output_type:
        query = query.where(AgentOutput.output_type == output_type)
    query = query.order_by(AgentOutput.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    outputs = result.scalars().all()

    return {
        "outputs": [
            {
                "id": o.id,
                "agent_name": o.agent_name,
                "output_type": o.output_type,
                "outcome": o.outcome,
                "metrics": o.metrics,
                "timestamp": o.timestamp.isoformat() if o.timestamp else None,
            }
            for o in outputs
        ],
        "count": len(outputs),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/learning/insights/{agent_type}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/insights/{agent_type}")
async def get_insights(
    agent_type: str,
    current_user: User = Depends(get_current_user),
):
    """Return current learning insights for a specific agent type.

    agent_type: trading | content | support
    """
    if agent_type == "trading":
        return await get_trading_insights()
    elif agent_type == "content":
        return await get_content_insights()
    elif agent_type == "support":
        return await get_support_insights()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown agent_type '{agent_type}'. Use: trading | content | support",
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/learning/dashboard
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_learning_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Single call that returns everything needed for the learning hub UI panel."""
    # Top patterns
    patterns_result = await db.execute(
        select(Pattern).where(Pattern.is_active == True)  # noqa: E712
        .order_by(Pattern.confidence_score.desc()).limit(5)
    )
    top_patterns = patterns_result.scalars().all()

    # Active instruction count per agent
    instr_result = await db.execute(
        select(AgentInstruction).where(AgentInstruction.status == "active")
    )
    active_instructions = instr_result.scalars().all()
    instr_by_agent: dict[str, int] = {}
    for i in active_instructions:
        instr_by_agent[i.agent_name] = instr_by_agent.get(i.agent_name, 0) + 1

    # Output outcomes (last 100)
    outputs_result = await db.execute(
        select(AgentOutput).order_by(AgentOutput.timestamp.desc()).limit(100)
    )
    recent_outputs = outputs_result.scalars().all()
    outcome_counts = {"success": 0, "failure": 0, "skipped": 0, "pending": 0}
    for o in recent_outputs:
        key = o.outcome or "pending"
        outcome_counts[key] = outcome_counts.get(key, 0) + 1

    return {
        "top_patterns": [
            {
                "name": p.pattern_name,
                "confidence": p.confidence_score,
                "category": p.category,
                "recommendation": p.recommendation,
            }
            for p in top_patterns
        ],
        "active_instructions_by_agent": instr_by_agent,
        "recent_output_outcomes": outcome_counts,
        "total_active_patterns": len(top_patterns),
        "total_active_instructions": len(active_instructions),
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/learning/trigger — manual analysis run (admin only)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/trigger")
async def trigger_learning_cycle(
    current_user: User = Depends(get_current_user),
):
    """Manually trigger one learning hub analysis cycle.

    Useful for testing and for admin users who want to refresh patterns immediately.
    """
    if current_user.subscription_tier != "pro" and not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only pro users or admins can manually trigger a learning cycle",
        )

    logger.info("Manual learning cycle triggered by user %s", current_user.id)
    try:
        summary = await learning_hub.analyze_all_data()
        return {
            "status": "completed",
            "patterns_found": summary.get("patterns_found", 0),
            "instructions_sent": summary.get("instructions_sent", 0),
            "duration_s": summary.get("duration_s", 0),
        }
    except Exception as exc:
        logger.error("Manual learning cycle failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Learning cycle failed: {exc}",
        )
