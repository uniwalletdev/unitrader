"""
src/services/subscription.py — Subscription lifecycle management.

Handles upgrading, downgrading, and syncing subscription state between
Stripe and the local User model.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import User
from src.integrations.stripe_client import (
    PLAN_FREE,
    PLAN_PRO,
    create_checkout_session,
    create_customer,
    create_portal_session,
    get_subscription,
)

logger = logging.getLogger(__name__)

_FRONTEND_URL = getattr(settings, "frontend_url", "http://localhost:3000")


# ─────────────────────────────────────────────
# Checkout
# ─────────────────────────────────────────────

async def start_pro_checkout(user: User, price_id: str) -> str:
    """Ensure the user has a Stripe customer record, then create a checkout session.

    Args:
        user: Authenticated User ORM instance.
        price_id: Stripe Price ID for the Pro plan.

    Returns:
        Stripe Checkout URL to redirect the user to.
    """
    async with AsyncSessionLocal() as db:
        # Create Stripe customer on first checkout
        if not user.stripe_customer_id:
            customer_id = create_customer(email=user.email, user_id=user.id)
            result = await db.execute(select(User).where(User.id == user.id))
            db_user = result.scalar_one()
            db_user.stripe_customer_id = customer_id
            await db.commit()
        else:
            customer_id = user.stripe_customer_id

    success_url = f"{_FRONTEND_URL}/app?upgraded=true"
    cancel_url  = f"{_FRONTEND_URL}/app?modal=trial"

    url = create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url,
        user_id=user.id,
    )
    logger.info("Checkout session started for user %s", user.id)
    return url


# ─────────────────────────────────────────────
# Billing Portal
# ─────────────────────────────────────────────

async def get_billing_portal_url(user: User) -> str:
    """Return the Stripe Customer Portal URL for the given user.

    Raises ValueError if the user has no Stripe customer record.
    """
    if not user.stripe_customer_id:
        raise ValueError("No Stripe customer record — user must subscribe first")

    return_url = f"{_FRONTEND_URL}/app"
    return create_portal_session(
        customer_id=user.stripe_customer_id,
        return_url=return_url,
    )


# ─────────────────────────────────────────────
# Webhook sync
# ─────────────────────────────────────────────

async def sync_subscription_from_webhook(parsed: dict) -> None:
    """Update the User's subscription fields from a parsed Stripe webhook event.

    Args:
        parsed: Output of stripe_client.parse_subscription_event().
    """
    customer_id = parsed.get("customer_id")
    subscription_id = parsed.get("subscription_id")
    stripe_status = parsed.get("status")
    period_end_ts = parsed.get("period_end")

    if not customer_id:
        logger.warning("Webhook missing customer_id — skipping sync")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("No user found for Stripe customer %s", customer_id)
            return

        # Map Stripe status → internal subscription tier
        if stripe_status in {"active", "trialing"}:
            user.subscription_tier = PLAN_PRO
        elif stripe_status in {"canceled", "unpaid", "incomplete_expired"}:
            user.subscription_tier = PLAN_FREE
        # past_due keeps current tier but flags the issue

        user.stripe_subscription_id = subscription_id
        user.stripe_subscription_status = stripe_status

        if period_end_ts:
            user.subscription_current_period_end = datetime.fromtimestamp(
                period_end_ts, tz=timezone.utc
            )

        await db.commit()
        logger.info(
            "Subscription synced: user=%s tier=%s status=%s",
            user.id, user.subscription_tier, stripe_status,
        )


# ─────────────────────────────────────────────
# Subscription status helpers
# ─────────────────────────────────────────────

def is_pro(user: User) -> bool:
    """Return True if the user has an active Pro subscription."""
    return (
        user.subscription_tier == PLAN_PRO
        and user.stripe_subscription_status in {"active", "trialing"}
    )


def get_subscription_summary(user: User) -> dict:
    """Return a clean subscription summary dict for API responses."""
    active = is_pro(user)
    period_end = user.subscription_current_period_end

    return {
        "tier": user.subscription_tier,
        "is_pro": active,
        "status": user.stripe_subscription_status or "none",
        "current_period_end": period_end.isoformat() if period_end else None,
        "features": _get_features(user.subscription_tier),
    }


def _get_features(tier: str) -> list[str]:
    from src.integrations.stripe_client import PLAN_FEATURES
    return PLAN_FEATURES.get(tier, PLAN_FEATURES[PLAN_FREE])


# ─────────────────────────────────────────────
# Feature gating
# ─────────────────────────────────────────────

FREE_ALLOWED_SYMBOLS = {"BTCUSDT", "BTC/USDT", "BTC/USD", "BTCUSD"}
FREE_MAX_EXCHANGES = 1
FREE_TRADES_PER_MONTH = 10


def check_free_tier_symbol(user: User, symbol: str) -> None:
    """Raise HTTPException if a free-tier user tries to trade a non-BTC symbol.

    During the 14-day trial users get unlimited symbols.  Once the trial ends
    and the user has chosen the free tier (trial_status == "downgraded") they
    are limited to BTC only.
    """
    from fastapi import HTTPException, status as http_status

    # Pro users and active trials have no restriction
    if user.subscription_tier == "pro":
        return
    if user.trial_status == "active":
        return

    normalised = symbol.upper().replace("-", "").replace("_", "").replace("/", "")
    if not any(normalised.startswith(btc) for btc in ("BTCUSDT", "BTCUSD", "BTC")):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=(
                f"Free plan is limited to BTC/USD. "
                f"Upgrade to Pro to trade {symbol}."
            ),
        )


async def check_trade_limit(user: User, db: AsyncSession) -> dict:
    """Check whether the user has remaining trades in their free-tier limit.

    Free plan: 10 trades per calendar month.
    Pro plan: unlimited.

    Returns:
        {"allowed": bool, "trades_used": int, "trades_limit": int | None}
    """
    if is_pro(user):
        return {"allowed": True, "trades_used": 0, "trades_limit": None}

    from sqlalchemy import func
    from models import Trade
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(func.count()).where(
            Trade.user_id == user.id,
            Trade.created_at >= month_start,
        )
    )
    used = result.scalar() or 0
    limit = 10

    return {
        "allowed": used < limit,
        "trades_used": used,
        "trades_limit": limit,
    }
