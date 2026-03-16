"""
src/services/subscription.py — Subscription lifecycle management.

Handles upgrading, downgrading, and syncing subscription state between
Stripe and the local User model.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import Trade, User
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
    """Symbol restriction disabled — all users can trade all symbols.

    Previously limited free-tier users to BTC only, but now all users
    have complete free access to all symbols.
    """
    # No restrictions — all symbols allowed for all users
    return


async def check_trade_limit(user: User, db: AsyncSession) -> dict:
    """Check whether the user has remaining trades for the current calendar month.

    Rules:
    - TESTING_MODE=true: bypass all limits (always allow)
    - Active paid subscription: unlimited
    - Active 14-day free trial: allow up to FREE_TRADES_PER_MONTH
    - Trial expired and no paid plan: block (subscription_required)

    Returns:
        {"allowed": bool, "trades_used": int, "trades_limit": int | None, "reason": str | None}
    """
    user_id = getattr(user, "id", None)

    # ── TESTING_MODE bypass ────────────────────────────────────────────────
    if str(getattr(settings, "testing_mode", "false")).strip().lower() == "true":
        logger.info("TESTING_MODE active — trade limit bypassed for user %s", user_id)
        return {"allowed": True, "trades_used": 0, "trades_limit": None, "reason": None}

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # calendar-month trade count
    trades_used_result = await db.execute(
        select(func.count()).select_from(Trade).where(
            Trade.user_id == user.id,
            Trade.created_at >= month_start,
        )
    )
    trades_used = int(trades_used_result.scalar() or 0)

    subscription_status = getattr(user, "stripe_subscription_status", None) or "none"
    subscription_tier = getattr(user, "subscription_tier", PLAN_FREE) or PLAN_FREE
    trial_status = getattr(user, "trial_status", None) or "unknown"
    trial_end_date = getattr(user, "trial_end_date", None)
    trial_active = (
        trial_status == "active"
        and trial_end_date is not None
        and trial_end_date > now
    )

    # Paid subscription: unlimited trades
    paid_active = (
        subscription_tier == PLAN_PRO
        and subscription_status in {"active", "trialing"}
    )

    # Determine limit and decision
    trades_limit: int | None
    reason: str | None = None
    allowed: bool

    if paid_active:
        trades_limit = None
        allowed = True
    elif trial_active:
        trades_limit = FREE_TRADES_PER_MONTH
        allowed = trades_used < FREE_TRADES_PER_MONTH
        if not allowed:
            reason = "trial_limit_reached"
    else:
        trades_limit = 0
        allowed = False
        reason = "subscription_required"

    logger.debug(
        "Trade limit check user=%s subscription_status=%s tier=%s trial_status=%s trial_end_date=%s "
        "trades_used_month=%s trades_limit=%s allowed=%s reason=%s",
        user_id,
        subscription_status,
        subscription_tier,
        trial_status,
        trial_end_date.isoformat() if trial_end_date else None,
        trades_used,
        trades_limit,
        allowed,
        reason,
    )

    if not allowed:
        logger.warning(
            "Trade blocked user=%s reason=%s trades_used_month=%s trades_limit=%s",
            user_id,
            reason,
            trades_used,
            trades_limit,
        )

    return {
        "allowed": allowed,
        "trades_used": trades_used,
        "trades_limit": trades_limit,
        "reason": reason,
    }
