"""
routers/governance.py — Data governance admin API (Phase 12).

Admin-only endpoints for business snapshots, approval workflow, egress audit,
and allowlist management. All require X-Admin-Secret header.

Endpoints:
    GET    /api/governance/latest                 — most recent business snapshot
    GET    /api/governance/snapshots?days=30      — snapshot history
    GET    /api/governance/approvals?status=...   — approval queue
    POST   /api/governance/approvals/{id}/approve — mark approved (admin)
    POST   /api/governance/approvals/{id}/deny    — mark denied (admin)
    GET    /api/governance/egress?days=7          — outbound call audit
    GET    /api/governance/allowlist              — current allowlist
    GET    /api/governance/dashboard              — one-shot combined payload
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import (
    BusinessApproval,
    BusinessSnapshot,
    EgressAllowlist,
    EgressAuditLog,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/governance", tags=["Governance"])


# ─────────────────────────────────────────────
# Auth guard (same pattern as token_management)
# ─────────────────────────────────────────────

async def require_admin(x_admin_secret: str = Header(...)) -> None:
    if not settings.admin_secret_key:
        raise HTTPException(status_code=503, detail="Admin secret not configured")
    if x_admin_secret != settings.admin_secret_key:
        raise HTTPException(status_code=403, detail="Invalid admin secret")


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class DenyRequest(BaseModel):
    reason: Optional[str] = None


# ─────────────────────────────────────────────
# GET /api/governance/latest
# ─────────────────────────────────────────────

@router.get("/latest", dependencies=[Depends(require_admin)])
async def get_latest_snapshot(db: AsyncSession = Depends(get_db)) -> dict:
    """Most recent business snapshot + quick derived KPIs."""
    result = await db.execute(
        select(BusinessSnapshot)
        .order_by(BusinessSnapshot.snapshot_at.desc())
        .limit(1)
    )
    snap = result.scalar_one_or_none()
    if snap is None:
        return {"snapshot": None}
    return {"snapshot": _snap_to_dict(snap)}


# ─────────────────────────────────────────────
# GET /api/governance/snapshots
# ─────────────────────────────────────────────

@router.get("/snapshots", dependencies=[Depends(require_admin)])
async def get_snapshots(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(BusinessSnapshot)
        .where(BusinessSnapshot.snapshot_at >= since)
        .order_by(BusinessSnapshot.snapshot_at.asc())
    )
    rows = result.scalars().all()
    return {"days": days, "series": [_snap_to_dict(r) for r in rows]}


# ─────────────────────────────────────────────
# GET /api/governance/approvals
# ─────────────────────────────────────────────

@router.get("/approvals", dependencies=[Depends(require_admin)])
async def list_approvals(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(BusinessApproval).order_by(BusinessApproval.created_at.desc())
    if status_filter:
        stmt = stmt.where(BusinessApproval.status == status_filter)
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_approval_to_dict(r) for r in rows]}


# ─────────────────────────────────────────────
# POST /api/governance/approvals/{id}/approve
# ─────────────────────────────────────────────

@router.post("/approvals/{approval_id}/approve", dependencies=[Depends(require_admin)])
async def approve_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    approval = await _get_pending(db, approval_id)
    approval.status = "approved"
    approval.approved_at = datetime.now(timezone.utc)
    approval.approved_via = "eagle_eye"
    await db.commit()
    await db.refresh(approval)
    logger.info("Approval %s APPROVED via eagle_eye", approval_id)
    return {"ok": True, "approval": _approval_to_dict(approval)}


# ─────────────────────────────────────────────
# POST /api/governance/approvals/{id}/deny
# ─────────────────────────────────────────────

@router.post("/approvals/{approval_id}/deny", dependencies=[Depends(require_admin)])
async def deny_approval(
    approval_id: str,
    body: DenyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    approval = await _get_pending(db, approval_id)
    approval.status = "denied"
    approval.approved_at = datetime.now(timezone.utc)
    approval.approved_via = "eagle_eye"
    approval.denial_reason = body.reason or "denied by admin"
    await db.commit()
    await db.refresh(approval)
    logger.info("Approval %s DENIED via eagle_eye: %s", approval_id, approval.denial_reason)
    return {"ok": True, "approval": _approval_to_dict(approval)}


# ─────────────────────────────────────────────
# GET /api/governance/egress
# ─────────────────────────────────────────────

@router.get("/egress", dependencies=[Depends(require_admin)])
async def get_egress_audit(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # Aggregate by domain.
    by_domain = (await db.execute(
        select(
            EgressAuditLog.domain,
            func.count().label("calls"),
            func.sum(EgressAuditLog.bytes_out).label("bytes_out"),
            func.sum(EgressAuditLog.bytes_in).label("bytes_in"),
        )
        .where(EgressAuditLog.ts >= since)
        .group_by(EgressAuditLog.domain)
        .order_by(func.count().desc())
    )).all()
    # Daily totals.
    bucket = func.date_trunc("day", EgressAuditLog.ts).label("day")
    daily = (await db.execute(
        select(bucket, func.count().label("calls"))
        .where(EgressAuditLog.ts >= since)
        .group_by(bucket)
        .order_by(bucket.asc())
    )).all()
    # Recent errors.
    errors = (await db.execute(
        select(EgressAuditLog)
        .where(EgressAuditLog.ts >= since, EgressAuditLog.error_message.isnot(None))
        .order_by(EgressAuditLog.ts.desc())
        .limit(25)
    )).scalars().all()
    return {
        "days": days,
        "by_domain": [
            {"domain": r.domain, "calls": int(r.calls or 0),
             "bytes_out": int(r.bytes_out or 0), "bytes_in": int(r.bytes_in or 0)}
            for r in by_domain
        ],
        "daily": [
            {"day": r.day.isoformat() if r.day else None, "calls": int(r.calls or 0)}
            for r in daily
        ],
        "errors": [_audit_to_dict(r) for r in errors],
    }


# ─────────────────────────────────────────────
# GET /api/governance/allowlist
# ─────────────────────────────────────────────

@router.get("/allowlist", dependencies=[Depends(require_admin)])
async def get_allowlist(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(
        select(EgressAllowlist).order_by(EgressAllowlist.category, EgressAllowlist.domain)
    )).scalars().all()
    return {
        "domains": [
            {"domain": r.domain, "category": r.category, "purpose": r.purpose,
             "added_at": r.added_at.isoformat() if r.added_at else None}
            for r in rows
        ]
    }


# ─────────────────────────────────────────────
# GET /api/governance/dashboard — one-shot UI payload
# ─────────────────────────────────────────────

@router.get("/dashboard", dependencies=[Depends(require_admin)])
async def get_dashboard(db: AsyncSession = Depends(get_db)) -> dict:
    latest = (await db.execute(
        select(BusinessSnapshot).order_by(BusinessSnapshot.snapshot_at.desc()).limit(1)
    )).scalar_one_or_none()

    pending = (await db.execute(
        select(func.count()).select_from(BusinessApproval)
        .where(BusinessApproval.status == "pending")
    )).scalar() or 0

    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    calls_24h = (await db.execute(
        select(func.count()).select_from(EgressAuditLog)
        .where(EgressAuditLog.ts >= since_24h)
    )).scalar() or 0

    return {
        "latest": _snap_to_dict(latest) if latest else None,
        "pending_approvals": int(pending),
        "egress_calls_24h": int(calls_24h),
    }


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

async def _get_pending(db: AsyncSession, approval_id: str) -> BusinessApproval:
    result = await db.execute(
        select(BusinessApproval).where(BusinessApproval.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval already {approval.status}",
        )
    # Expire if past TTL.
    if approval.ttl_expires_at and approval.ttl_expires_at < datetime.now(timezone.utc):
        approval.status = "expired"
        await db.commit()
        raise HTTPException(status_code=410, detail="Approval expired")
    return approval


def _snap_to_dict(s: BusinessSnapshot) -> dict:
    return {
        "id": s.id,
        "snapshot_at": s.snapshot_at.isoformat() if s.snapshot_at else None,
        "mrr_cents": int(s.mrr_cents or 0),
        "active_subs": int(s.active_subs or 0),
        "new_subs_30d": int(s.new_subs_30d or 0),
        "cancelled_subs_30d": int(s.cancelled_subs_30d or 0),
        "churn_rate_pct": float(s.churn_rate_pct or 0),
        "costs_total_cents": int(s.costs_total_cents or 0),
        "costs_breakdown": s.costs_breakdown or {},
        "margin_cents": int(s.margin_cents or 0),
        "forecast_30d_mrr_cents": int(s.forecast_30d_mrr_cents) if s.forecast_30d_mrr_cents else None,
        "forecast_30d_cost_cents": int(s.forecast_30d_cost_cents) if s.forecast_30d_cost_cents else None,
        "anomalies": s.anomalies or [],
    }


def _approval_to_dict(a: BusinessApproval) -> dict:
    return {
        "id": a.id,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "requested_by_agent": a.requested_by_agent,
        "action_category": a.action_category,
        "target_domain": a.target_domain,
        "action_summary": a.action_summary,
        "request_payload": a.request_payload,
        "status": a.status,
        "result_payload": a.result_payload,
        "notified_via": a.notified_via or [],
        "approved_at": a.approved_at.isoformat() if a.approved_at else None,
        "approved_via": a.approved_via,
        "executed_at": a.executed_at.isoformat() if a.executed_at else None,
        "denial_reason": a.denial_reason,
        "ttl_expires_at": a.ttl_expires_at.isoformat() if a.ttl_expires_at else None,
    }


def _audit_to_dict(r: EgressAuditLog) -> dict:
    return {
        "id": r.id,
        "ts": r.ts.isoformat() if r.ts else None,
        "domain": r.domain,
        "method": r.method,
        "path": r.path,
        "status_code": r.status_code,
        "purpose": r.purpose,
        "bytes_out": r.bytes_out,
        "bytes_in": r.bytes_in,
        "duration_ms": r.duration_ms,
        "approval_id": r.approval_id,
        "error_message": r.error_message,
    }
