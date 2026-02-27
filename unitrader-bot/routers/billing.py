"""
routers/billing.py — Stripe payment and subscription endpoints.

Endpoints:
    GET  /api/billing/plans              — Available subscription plans + pricing
    GET  /api/billing/status             — Current subscription status
    POST /api/billing/checkout           — Start Stripe Checkout (upgrade to Pro)
    POST /api/billing/portal             — Open Stripe Customer Portal
    POST /api/billing/webhook            — Receive Stripe webhook events
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
import stripe as stripe_lib

from config import settings
from database import get_db
from routers.auth import get_current_user
from src.integrations.stripe_client import (
    PLAN_FEATURES,
    PLAN_PRICES,
    parse_subscription_event,
    verify_webhook,
)
from src.services.subscription import (
    get_billing_portal_url,
    get_subscription_summary,
    start_pro_checkout,
    sync_subscription_from_webhook,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["Billing"])


# ─────────────────────────────────────────────
# GET /api/billing/plans
# ─────────────────────────────────────────────

@router.get("/plans")
async def list_plans():
    """Return available subscription plans with pricing and features.

    No authentication required — used on the public pricing page.
    """
    return {
        "status": "success",
        "data": {
            "plans": [
                {
                    "id": "free",
                    "name": "Free",
                    "price_usd": 0,
                    "price_monthly_cents": 0,
                    "trial_days": 0,
                    "features": PLAN_FEATURES["free"],
                    "cta": "Get Started",
                },
                {
                    "id": "pro",
                    "name": "Pro",
                    "price_usd": 9.99,
                    "price_monthly_cents": PLAN_PRICES["pro"],
                    "trial_days": 7,
                    "features": PLAN_FEATURES["pro"],
                    "cta": "Start Free Trial",
                    "highlighted": True,
                },
            ]
        },
    }


# ─────────────────────────────────────────────
# GET /api/billing/status
# ─────────────────────────────────────────────

@router.get("/status")
async def get_billing_status(current_user=Depends(get_current_user)):
    """Return the authenticated user's current subscription state."""
    return {
        "status": "success",
        "data": get_subscription_summary(current_user),
    }


# ─────────────────────────────────────────────
# POST /api/billing/checkout
# ─────────────────────────────────────────────

async def _run_checkout(current_user) -> dict:
    """Shared logic used by both /checkout and /checkout-session."""
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment system not configured",
        )
    price_id = settings.stripe_pro_price_id
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe Pro price not configured (STRIPE_PRO_PRICE_ID)",
        )
    try:
        url = await start_pro_checkout(current_user, price_id)
    except Exception as exc:
        logger.error("Checkout session creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create checkout session",
        )
    return {"status": "success", "data": {"checkout_url": url}}


@router.post("/checkout")
async def create_checkout(current_user=Depends(get_current_user)):
    """Create a Stripe Checkout session and return the redirect URL.

    Includes a 7-day free trial. The user is redirected to Stripe's
    hosted checkout page to enter their card details.
    """
    return await _run_checkout(current_user)


# ─────────────────────────────────────────────
# POST /api/billing/checkout-session  (alias used by trial modal)
# ─────────────────────────────────────────────

@router.post("/checkout-session")
async def create_checkout_session_alias(current_user=Depends(get_current_user)):
    """Alias for /checkout — used by the trial choice modal.

    Returns the same Stripe Checkout URL. Having a dedicated endpoint lets
    the trial flow remain decoupled from the general billing UI.
    """
    return await _run_checkout(current_user)


# ─────────────────────────────────────────────
# POST /api/billing/portal
# ─────────────────────────────────────────────

@router.post("/portal")
async def open_portal(current_user=Depends(get_current_user)):
    """Create a Stripe Customer Portal session.

    Lets the user manage their subscription, update payment method,
    view invoices, and cancel.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment system not configured",
        )

    try:
        url = await get_billing_portal_url(current_user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error("Portal session creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create billing portal session",
        )

    return {"status": "success", "data": {"portal_url": url}}


# ─────────────────────────────────────────────
# POST /api/billing/webhook
# ─────────────────────────────────────────────

_HANDLED_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
}


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
):
    """Receive and process Stripe webhook events.

    This endpoint must NOT be protected by authentication — Stripe calls it
    directly. Signature verification ensures the request is from Stripe.
    """
    payload = await request.body()

    try:
        event = verify_webhook(payload, stripe_signature or "")
    except stripe_lib.error.SignatureVerificationError:
        logger.warning("Stripe webhook signature verification failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    event_type = event["type"]
    logger.info("Stripe webhook received: %s", event_type)

    if event_type in _HANDLED_EVENTS:
        try:
            parsed = parse_subscription_event(event)
            await sync_subscription_from_webhook(parsed)
        except Exception as exc:
            logger.error("Webhook processing error for %s: %s", event_type, exc)
            # Return 200 to prevent Stripe from retrying on our processing errors
    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)

    return {"received": True}
