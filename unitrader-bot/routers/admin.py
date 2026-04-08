"""
routers/admin.py — Admin panel API endpoints.

All endpoints require the X-Admin-Secret header matching ADMIN_SECRET_KEY.

Endpoints:
    GET   /api/admin/users              — Paginated user list with search
    GET   /api/admin/users/{user_id}    — Full user detail
    PATCH /api/admin/users/{user_id}    — Update tier, trial dates, trading_paused
    GET   /api/admin/metrics            — Dashboard metrics
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import Trade, TradingAccount, User, UserExternalAccount, UserSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ─────────────────────────────────────────────
# Auth guard
# ─────────────────────────────────────────────

async def require_admin(x_admin_secret: str = Header(...)):
    """Dependency: verify the admin secret header."""
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


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class UserListItem(BaseModel):
    id: str
    email: str
    ai_name: str
    subscription_tier: str
    trial_status: str
    trial_end_date: Optional[datetime] = None
    is_active: bool
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    trade_count: int = 0
    exchange_count: int = 0

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: list[UserListItem]
    total: int
    page: int
    page_size: int


class ExchangeInfo(BaseModel):
    id: str
    exchange: str
    is_paper: bool
    account_label: str
    is_active: bool
    auto_trade_enabled: bool
    last_known_balance_usd: Optional[float] = None


class ChannelInfo(BaseModel):
    platform: str
    external_username: Optional[str] = None
    is_linked: bool


class UserDetailResponse(BaseModel):
    id: str
    email: str
    ai_name: str
    subscription_tier: str
    stripe_customer_id: Optional[str] = None
    stripe_subscription_status: Optional[str] = None
    trial_status: str
    trial_end_date: Optional[datetime] = None
    trial_started_at: Optional[datetime] = None
    is_active: bool
    email_verified: bool
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    trading_paused: bool = False
    trade_count: int = 0
    exchanges: list[ExchangeInfo] = []
    channels: list[ChannelInfo] = []

    model_config = {"from_attributes": True}


class UpdateUserRequest(BaseModel):
    subscription_tier: Optional[str] = None
    trial_status: Optional[str] = None
    trial_end_date: Optional[datetime] = None
    trading_paused: Optional[bool] = None
    is_active: Optional[bool] = None


class MetricsResponse(BaseModel):
    total_users: int
    active_users: int
    free_users: int
    pro_users: int
    elite_users: int
    active_trials: int
    expired_trials: int
    converted_trials: int
    conversion_rate: float
    total_trades: int
    trades_this_month: int
    mrr_cents: int


# ─────────────────────────────────────────────
# GET /api/admin/users
# ─────────────────────────────────────────────

@router.get("/users", response_model=UserListResponse)
async def list_users(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query("", max_length=200),
    tier: str = Query("", max_length=20),
):
    """List all users with trade count and exchange count."""

    # Base filter
    filters = []
    if search:
        term = f"%{search}%"
        filters.append(User.email.ilike(term) | User.ai_name.ilike(term))
    if tier:
        filters.append(User.subscription_tier == tier)

    # Total count
    count_q = select(func.count(User.id))
    for f in filters:
        count_q = count_q.where(f)
    total = (await db.execute(count_q)).scalar() or 0

    # Subqueries for aggregations
    trade_count_sq = (
        select(Trade.user_id, func.count(Trade.id).label("trade_count"))
        .group_by(Trade.user_id)
        .subquery()
    )
    exchange_count_sq = (
        select(
            TradingAccount.user_id,
            func.count(TradingAccount.id).label("exchange_count"),
        )
        .where(TradingAccount.is_active == True)  # noqa: E712
        .group_by(TradingAccount.user_id)
        .subquery()
    )

    q = (
        select(
            User,
            func.coalesce(trade_count_sq.c.trade_count, 0).label("trade_count"),
            func.coalesce(exchange_count_sq.c.exchange_count, 0).label("exchange_count"),
        )
        .outerjoin(trade_count_sq, User.id == trade_count_sq.c.user_id)
        .outerjoin(exchange_count_sq, User.id == exchange_count_sq.c.user_id)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    for f in filters:
        q = q.where(f)

    rows = (await db.execute(q)).all()

    users = [
        UserListItem(
            id=user.id,
            email=user.email,
            ai_name=user.ai_name,
            subscription_tier=user.subscription_tier,
            trial_status=user.trial_status,
            trial_end_date=user.trial_end_date,
            is_active=user.is_active,
            created_at=user.created_at if hasattr(user, "created_at") else None,
            last_login=user.last_login,
            trade_count=trade_count,
            exchange_count=exchange_count,
        )
        for user, trade_count, exchange_count in rows
    ]

    return UserListResponse(users=users, total=total, page=page, page_size=page_size)


# ─────────────────────────────────────────────
# GET /api/admin/users/{user_id}
# ─────────────────────────────────────────────

@router.get("/users/{user_id}", response_model=UserDetailResponse)
async def get_user_detail(
    user_id: str,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Full user detail with exchanges, channels, and settings."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Trade count
    tc = await db.execute(
        select(func.count(Trade.id)).where(Trade.user_id == user_id)
    )
    trade_count = tc.scalar() or 0

    # Exchanges
    ex_result = await db.execute(
        select(TradingAccount).where(TradingAccount.user_id == user_id)
    )
    exchanges = [
        ExchangeInfo(
            id=a.id,
            exchange=a.exchange,
            is_paper=a.is_paper,
            account_label=a.account_label,
            is_active=a.is_active,
            auto_trade_enabled=a.auto_trade_enabled,
            last_known_balance_usd=a.last_known_balance_usd,
        )
        for a in ex_result.scalars().all()
    ]

    # Channels
    ch_result = await db.execute(
        select(UserExternalAccount).where(UserExternalAccount.user_id == user_id)
    )
    channels = [
        ChannelInfo(
            platform=c.platform,
            external_username=c.external_username,
            is_linked=c.is_linked,
        )
        for c in ch_result.scalars().all()
    ]

    # Settings
    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = settings_result.scalar_one_or_none()

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        ai_name=user.ai_name,
        subscription_tier=user.subscription_tier,
        stripe_customer_id=user.stripe_customer_id,
        stripe_subscription_status=user.stripe_subscription_status,
        trial_status=user.trial_status,
        trial_end_date=user.trial_end_date,
        trial_started_at=user.trial_started_at,
        is_active=user.is_active,
        email_verified=user.email_verified,
        created_at=user.created_at if hasattr(user, "created_at") else None,
        last_login=user.last_login,
        trading_paused=user_settings.trading_paused if user_settings else False,
        trade_count=trade_count,
        exchanges=exchanges,
        channels=channels,
    )


# ─────────────────────────────────────────────
# PATCH /api/admin/users/{user_id}
# ─────────────────────────────────────────────

@router.patch("/users/{user_id}", response_model=UserDetailResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update user tier, trial, or trading_paused."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate tier
    if body.subscription_tier is not None:
        if body.subscription_tier not in ("free", "pro", "elite"):
            raise HTTPException(status_code=400, detail="Invalid tier. Must be free, pro, or elite.")
        user.subscription_tier = body.subscription_tier
        logger.info("Admin set user %s tier to %s", user_id, body.subscription_tier)

    if body.trial_status is not None:
        if body.trial_status not in ("active", "expired", "converted"):
            raise HTTPException(status_code=400, detail="Invalid trial_status.")
        user.trial_status = body.trial_status

    if body.trial_end_date is not None:
        user.trial_end_date = body.trial_end_date

    if body.is_active is not None:
        user.is_active = body.is_active

    # trading_paused lives on UserSettings
    if body.trading_paused is not None:
        settings_result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        user_settings = settings_result.scalar_one_or_none()
        if user_settings:
            user_settings.trading_paused = body.trading_paused

    await db.commit()

    # Return updated detail
    return await get_user_detail(user_id, _, db)


# ─────────────────────────────────────────────
# GET /api/admin/metrics
# ─────────────────────────────────────────────

@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    _: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard metrics: user counts, trial conversion, MRR."""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # User counts by tier
    tier_counts = await db.execute(
        select(
            User.subscription_tier,
            func.count(User.id),
        )
        .where(User.is_active == True)  # noqa: E712
        .group_by(User.subscription_tier)
    )
    tier_map = {row[0]: row[1] for row in tier_counts.all()}
    free_users = tier_map.get("free", 0)
    pro_users = tier_map.get("pro", 0)
    elite_users = tier_map.get("elite", 0)
    active_users = free_users + pro_users + elite_users

    total_result = await db.execute(select(func.count(User.id)))
    total_users = total_result.scalar() or 0

    # Trial stats
    trial_counts = await db.execute(
        select(User.trial_status, func.count(User.id)).group_by(User.trial_status)
    )
    trial_map = {row[0]: row[1] for row in trial_counts.all()}
    active_trials = trial_map.get("active", 0)
    expired_trials = trial_map.get("expired", 0)
    converted_trials = trial_map.get("converted", 0)

    total_finished = expired_trials + converted_trials
    conversion_rate = (converted_trials / total_finished * 100) if total_finished > 0 else 0.0

    # Trade counts
    total_trades_result = await db.execute(select(func.count(Trade.id)))
    total_trades = total_trades_result.scalar() or 0

    trades_month_result = await db.execute(
        select(func.count(Trade.id)).where(Trade.created_at >= month_start)
    )
    trades_this_month = trades_month_result.scalar() or 0

    # MRR (pro * 999 + elite * 2999 cents)
    mrr_cents = (pro_users * 999) + (elite_users * 2999)

    return MetricsResponse(
        total_users=total_users,
        active_users=active_users,
        free_users=free_users,
        pro_users=pro_users,
        elite_users=elite_users,
        active_trials=active_trials,
        expired_trials=expired_trials,
        converted_trials=converted_trials,
        conversion_rate=round(conversion_rate, 1),
        total_trades=total_trades,
        trades_this_month=trades_this_month,
        mrr_cents=mrr_cents,
    )
