"""
src/integrations/stripe_client.py — Stripe API wrapper for Unitrader.

Handles checkout sessions, customer portal, webhook verification,
and subscription status parsing.
"""

import logging
from typing import Any

import stripe
from stripe import Webhook

from config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Plans
# ─────────────────────────────────────────────

PLAN_FREE = "free"
PLAN_PRO = "pro"

# Set these in your Stripe dashboard and put the price IDs in .env
PRO_MONTHLY_PRICE_ID = settings.stripe_pro_price_id if hasattr(settings, "stripe_pro_price_id") else ""

PLAN_FEATURES = {
    PLAN_FREE: [
        "1 exchange connection",
        "10 AI trades per month",
        "Basic chat support",
        "Performance dashboard",
    ],
    PLAN_PRO: [
        "Unlimited exchange connections",
        "Unlimited AI trades",
        "Priority Claude AI (Opus)",
        "Advanced analytics",
        "Email alerts",
        "API access",
        "Premium support",
    ],
}

PLAN_PRICES = {
    PLAN_FREE: 0,
    PLAN_PRO: 999,  # cents → $9.99/month
}


def _get_stripe() -> stripe:
    """Return the stripe module configured with the secret key."""
    if not settings.stripe_secret_key:
        raise ValueError("STRIPE_SECRET_KEY is not configured")
    stripe.api_key = settings.stripe_secret_key
    return stripe


# ─────────────────────────────────────────────
# Customer management
# ─────────────────────────────────────────────

def create_customer(email: str, user_id: str) -> str:
    """Create a Stripe customer and return the customer ID.

    Args:
        email: User's email address.
        user_id: Internal user UUID (stored as metadata).

    Returns:
        Stripe customer ID (cus_...).
    """
    _stripe = _get_stripe()
    customer = _stripe.Customer.create(
        email=email,
        metadata={"user_id": user_id},
    )
    logger.info("Stripe customer created: %s for user %s", customer.id, user_id)
    return customer.id


def get_customer(customer_id: str) -> dict:
    """Retrieve a Stripe customer object."""
    _stripe = _get_stripe()
    return _stripe.Customer.retrieve(customer_id)


# ─────────────────────────────────────────────
# Checkout Session
# ─────────────────────────────────────────────

def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    user_id: str,
) -> str:
    """Create a Stripe Checkout session for a subscription.

    Args:
        customer_id: Stripe customer ID.
        price_id: Stripe Price ID for the subscription plan.
        success_url: Redirect URL on successful payment.
        cancel_url: Redirect URL if user cancels.
        user_id: Internal user ID stored in metadata.

    Returns:
        Checkout session URL to redirect the user to.
    """
    _stripe = _get_stripe()
    session = _stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": user_id},
        subscription_data={
            "metadata": {"user_id": user_id},
            "trial_period_days": 7,  # 7-day free trial
        },
        allow_promotion_codes=True,
    )
    logger.info("Checkout session created: %s for customer %s", session.id, customer_id)
    return session.url


# ─────────────────────────────────────────────
# Customer Portal (manage billing)
# ─────────────────────────────────────────────

def create_portal_session(customer_id: str, return_url: str) -> str:
    """Create a Stripe Customer Portal session.

    Allows the user to manage their subscription, update payment methods,
    download invoices, and cancel.

    Returns:
        Portal session URL.
    """
    _stripe = _get_stripe()
    session = _stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url


# ─────────────────────────────────────────────
# Subscription queries
# ─────────────────────────────────────────────

def get_subscription(subscription_id: str) -> dict:
    """Retrieve a subscription object from Stripe."""
    _stripe = _get_stripe()
    return _stripe.Subscription.retrieve(subscription_id)


def cancel_subscription(subscription_id: str, at_period_end: bool = True) -> dict:
    """Cancel a subscription.

    Args:
        subscription_id: Stripe subscription ID.
        at_period_end: If True, cancel at period end (user keeps access until then).
                       If False, cancel immediately.

    Returns:
        Updated subscription object.
    """
    _stripe = _get_stripe()
    if at_period_end:
        sub = _stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True,
        )
    else:
        sub = _stripe.Subscription.cancel(subscription_id)
    logger.info("Subscription %s cancelled (at_period_end=%s)", subscription_id, at_period_end)
    return sub


# ─────────────────────────────────────────────
# Webhook Verification
# ─────────────────────────────────────────────

def verify_webhook(payload: bytes, sig_header: str) -> dict:
    """Verify a Stripe webhook signature and return the parsed event.

    Args:
        payload: Raw request body bytes.
        sig_header: Value of the Stripe-Signature header.

    Returns:
        Stripe Event dict.

    Raises:
        stripe.error.SignatureVerificationError: If verification fails.
        ValueError: If webhook secret is not configured.
    """
    if not settings.stripe_webhook_secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET is not configured")

    event = Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )
    return event


# ─────────────────────────────────────────────
# Event parsing helpers
# ─────────────────────────────────────────────

def parse_subscription_event(event: dict) -> dict:
    """Extract the fields we care about from subscription webhook events.

    Handles:
        customer.subscription.created
        customer.subscription.updated
        customer.subscription.deleted
        invoice.payment_succeeded
        invoice.payment_failed

    Returns:
        {
            "event_type": str,
            "customer_id": str,
            "subscription_id": str | None,
            "status": str | None,       # active | trialing | past_due | canceled
            "period_end": int | None,   # Unix timestamp
            "user_id": str | None,      # from metadata
        }
    """
    event_type = event["type"]
    obj = event["data"]["object"]

    customer_id = obj.get("customer")
    subscription_id = None
    status = None
    period_end = None
    user_id = None

    if event_type.startswith("customer.subscription"):
        subscription_id = obj.get("id")
        status = obj.get("status")
        period_end = obj.get("current_period_end")
        user_id = obj.get("metadata", {}).get("user_id")

    elif event_type.startswith("invoice"):
        subscription_id = obj.get("subscription")
        user_id = obj.get("metadata", {}).get("user_id")
        status = "active" if event_type == "invoice.payment_succeeded" else "past_due"

    return {
        "event_type": event_type,
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "status": status,
        "period_end": period_end,
        "user_id": user_id,
    }
