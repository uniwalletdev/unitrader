"""
routers/token_management.py — Token management & cost analytics API.

Admin-only endpoints for observing Anthropic API consumption, budget status,
per-agent rate limits, and optional manual log insertion.

All endpoints require the X-Admin-Secret header matching ADMIN_SECRET_KEY.

Endpoints:
    GET   /api/token/budget          — Current month budget status
    GET   /api/token/consumption     — Per-agent time-series consumption
    GET   /api/token/rates           — Per-agent rate-limit state
    GET   /api/token/dashboard       — Aggregated dashboard payload
    POST  /api/token/log             — Manual log insert (internal use)
    POST  /api/token/check-budget    — Programmatic budget check
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import AgentRateLimit, TokenAuditLog, TokenBudget
from src.agents.token_manager import get_token_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/token", tags=["TokenManagement"])


# ─────────────────────────────────────────────────────────────────────────────
# Auth guard
# ─────────────────────────────────────────────────────────────────────────────

async def require_admin(x_admin_secret: str = Header(...)) -> None:
    if not settings.admin_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin secret not configured on server",
        )
    if x_admin_secret != settings.admin_secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin secret",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class TokenLogRequest(BaseModel):
    agent_name: str
    model: str
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    task_type: Optional[str] = None
    user_id: Optional[str] = None
    trade_id: Optional[str] = None
    status: str = "success"
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None


class CheckBudgetRequest(BaseModel):
    agent_name: str


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/token/budget
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/budget", dependencies=[Depends(require_admin)])
async def get_budget() -> dict:
    """Current month's budget totals + alert state."""
    return await get_token_manager().get_current_budget()


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/token/consumption
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/consumption", dependencies=[Depends(require_admin)])
async def get_consumption(
    agent: Optional[str] = Query(None, description="Agent name; omit for all"),
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-day consumption breakdown over the last `days` days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    bucket = func.date_trunc("day", TokenAuditLog.timestamp).label("day")
    stmt = (
        select(
            bucket,
            TokenAuditLog.agent_name,
            func.sum(TokenAuditLog.tokens_in).label("tokens_in"),
            func.sum(TokenAuditLog.tokens_out).label("tokens_out"),
            func.sum(TokenAuditLog.cost_usd).label("cost_usd"),
            func.count().label("calls"),
        )
        .where(TokenAuditLog.timestamp >= since)
        .group_by(bucket, TokenAuditLog.agent_name)
        .order_by(bucket.desc())
    )
    if agent:
        stmt = stmt.where(TokenAuditLog.agent_name == agent)

    result = await db.execute(stmt)
    rows = result.all()

    return {
        "since": since.isoformat(),
        "days": days,
        "agent_filter": agent,
        "series": [
            {
                "day": r.day.isoformat() if r.day else None,
                "agent_name": r.agent_name,
                "tokens_in": int(r.tokens_in or 0),
                "tokens_out": int(r.tokens_out or 0),
                "cost_usd": float(r.cost_usd or 0),
                "calls": int(r.calls or 0),
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/token/rates
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/rates", dependencies=[Depends(require_admin)])
async def get_rates(db: AsyncSession = Depends(get_db)) -> dict:
    """Every agent's rate-limit config + last known usage."""
    result = await db.execute(
        select(AgentRateLimit).order_by(AgentRateLimit.agent_name)
    )
    rows = result.scalars().all()
    return {
        "agents": [
            {
                "agent_name": r.agent_name,
                "priority": r.priority,
                "tokens_per_minute": r.tokens_per_minute,
                "tokens_used_this_minute": r.tokens_used_this_minute,
                "last_reset": r.last_reset.isoformat() if r.last_reset else None,
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/token/dashboard
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", dependencies=[Depends(require_admin)])
async def get_dashboard(db: AsyncSession = Depends(get_db)) -> dict:
    """One-shot payload for the admin UI dashboard."""
    tm = get_token_manager()
    budget = await tm.get_current_budget()

    # Top agents by cost this month
    since = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    agent_stmt = (
        select(
            TokenAuditLog.agent_name,
            func.sum(TokenAuditLog.tokens_in + TokenAuditLog.tokens_out).label("tokens"),
            func.sum(TokenAuditLog.cost_usd).label("cost"),
            func.count().label("calls"),
        )
        .where(TokenAuditLog.timestamp >= since)
        .group_by(TokenAuditLog.agent_name)
        .order_by(func.sum(TokenAuditLog.cost_usd).desc())
    )
    agent_rows = (await db.execute(agent_stmt)).all()

    # Last 24h calls
    last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    count_stmt = select(func.count()).where(TokenAuditLog.timestamp >= last_24h)
    calls_24h = (await db.execute(count_stmt)).scalar() or 0

    return {
        "budget": budget,
        "calls_last_24h": int(calls_24h),
        "agents_by_cost": [
            {
                "agent_name": r.agent_name,
                "tokens": int(r.tokens or 0),
                "cost_usd": float(r.cost or 0),
                "calls": int(r.calls or 0),
            }
            for r in agent_rows
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/token/log — manual insert for migrated / legacy agents
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/log", dependencies=[Depends(require_admin)])
async def post_log(payload: TokenLogRequest) -> dict:
    """Manually log a single LLM call (used by non-migrated agents)."""
    await get_token_manager().log_call(
        agent_name=payload.agent_name,
        task_type=payload.task_type,
        model=payload.model,
        tokens_in=payload.tokens_in,
        tokens_out=payload.tokens_out,
        latency_ms=payload.latency_ms,
        user_id=payload.user_id,
        trade_id=payload.trade_id,
        status=payload.status,
        error_message=payload.error_message,
    )
    return {"status": "logged"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/token/check-budget
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/check-budget", dependencies=[Depends(require_admin)])
async def post_check_budget(payload: CheckBudgetRequest) -> dict:
    """Programmatic budget check for external callers."""
    return await get_token_manager().check_budget(payload.agent_name)
