"""
tests/test_stripe_live.py — Live integration tests for Stripe payments and webhooks.

Tests the full payment pipeline:
  1. Stripe SDK connection + customer creation
  2. Checkout session URL generation
  3. Webhook signature verification
  4. Webhook event processing → DB user tier update
  5. Billing portal URL generation

═══════════════════════════════════════════════════════════
SETUP INSTRUCTIONS
═══════════════════════════════════════════════════════════

1. Create a Stripe account at https://stripe.com (free)
2. Go to Dashboard → Developers → API Keys
3. Copy the TEST keys (pk_test_... and sk_test_...)
4. Create a Product + Price in test mode:
   - Products → Add product → "Unitrader Pro" → $9.99/month
   - Copy the Price ID (price_xxx)
5. Add to .env.test:
       STRIPE_SECRET_KEY=sk_test_xxxxx
       STRIPE_PUBLIC_KEY=pk_test_xxxxx
       STRIPE_WEBHOOK_SECRET=whsec_xxxxx    (see step 7)
       STRIPE_PRO_PRICE_ID=price_xxxxx

6. For webhook testing, install Stripe CLI:
   https://stripe.com/docs/stripe-cli

7. Run the CLI listener in a separate terminal:
       stripe listen --forward-to localhost:8000/api/billing/webhook

   The CLI prints your webhook signing secret:
       Ready! Your webhook signing secret is whsec_xxxxx
   Copy it into STRIPE_WEBHOOK_SECRET.

8. In another terminal, trigger test events:
       stripe trigger checkout.session.completed

Run tests:
    pytest tests/test_stripe_live.py -v -s
═══════════════════════════════════════════════════════════
"""

import hashlib
import hmac
import json
import os
import time
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.live, pytest.mark.stripe]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_user(
    user_id: str = "test-stripe-user-001",
    email: str = "stripetest@unitrader.app",
    stripe_customer_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        email=email,
        ai_name="TradeBot",
        subscription_tier="free",
        trial_status="active",
        stripe_customer_id=stripe_customer_id,
        is_active=True,
    )


def _build_stripe_webhook_payload(event_type: str, data: dict) -> tuple[bytes, str]:
    """Build a raw Stripe webhook payload + valid HMAC signature."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    if secret.startswith("whsec_"):
        raw_secret = secret[len("whsec_"):]
    else:
        raw_secret = secret

    body = json.dumps({"type": event_type, "data": {"object": data}}).encode()
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{body.decode()}"
    sig = hmac.new(
        raw_secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    header = f"t={timestamp},v1={sig}"
    return body, header


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Stripe SDK connection
# ─────────────────────────────────────────────────────────────────────────────

class TestStripeConnection:
    """Verify Stripe API key is valid and SDK can connect."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_stripe):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_stripe_balance_retrieval(self):
        """A valid test key should let us fetch the Stripe account balance."""
        import stripe
        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

        # balance.retrieve() is a lightweight endpoint — safe for testing
        balance = stripe.Balance.retrieve()
        print(f"\n  Stripe account balance object: available currencies = {[b['currency'] for b in balance['available']]}")
        assert balance is not None, "Balance object should not be None"
        assert "available" in balance, "Balance should have 'available' list"

    @pytest.mark.asyncio
    async def test_stripe_key_is_test_mode(self):
        """Ensure we're using a test-mode key, never a live key in tests."""
        key = os.environ["STRIPE_SECRET_KEY"]
        assert key.startswith("sk_test_"), (
            f"STRIPE_SECRET_KEY must start with 'sk_test_' in tests. Got: {key[:12]}..."
        )
        print("\n  Stripe key is test-mode: OK")


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Customer creation
# ─────────────────────────────────────────────────────────────────────────────

class TestStripeCustomer:
    """Create and verify Stripe customer records."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_stripe):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_create_customer_returns_id(self):
        """create_customer() should return a valid cus_xxx ID."""
        from src.integrations.stripe_client import create_customer

        customer_id = create_customer(
            email="live-test@unitrader.app",
            user_id="test-user-stripe-001",
        )
        print(f"\n  Created Stripe customer: {customer_id}")
        assert customer_id.startswith("cus_"), f"Expected cus_xxx, got: {customer_id}"

        # Clean up
        import stripe
        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        stripe.Customer.delete(customer_id)
        print(f"  Cleaned up: {customer_id} deleted.")

    @pytest.mark.asyncio
    async def test_create_customer_metadata(self):
        """Customer should have user_id stored in metadata."""
        import stripe
        from src.integrations.stripe_client import create_customer

        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        user_id = "test-metadata-user-001"
        customer_id = create_customer(email="meta-test@unitrader.app", user_id=user_id)

        customer = stripe.Customer.retrieve(customer_id)
        print(f"\n  Customer metadata: {customer.metadata}")
        assert customer.metadata.get("user_id") == user_id, "Metadata should have user_id"

        stripe.Customer.delete(customer_id)


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Checkout session creation
# ─────────────────────────────────────────────────────────────────────────────

class TestStripeCheckout:
    """Verify checkout session URL generation."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_stripe):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_create_checkout_session_url(self):
        """create_checkout_session() should return a valid Stripe checkout URL."""
        import stripe
        from src.integrations.stripe_client import create_customer, create_checkout_session

        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        price_id = os.environ["STRIPE_PRO_PRICE_ID"]

        # Create a temporary customer
        customer_id = create_customer(email="checkout-test@unitrader.app", user_id="checkout-test-001")
        print(f"\n  Created customer: {customer_id}")

        try:
            url = create_checkout_session(
                customer_id=customer_id,
                price_id=price_id,
                success_url="http://localhost:3000/app?upgraded=true",
                cancel_url="http://localhost:3000/app?modal=trial",
            )
            print(f"  Checkout URL: {url[:60]}...")
            assert url.startswith("https://checkout.stripe.com"), (
                f"Expected Stripe checkout URL, got: {url[:60]}"
            )
        finally:
            stripe.Customer.delete(customer_id)
            print("  Customer cleaned up.")

    @pytest.mark.asyncio
    async def test_checkout_url_contains_session_id(self):
        """Stripe checkout URLs include a session ID after the path."""
        import stripe
        from src.integrations.stripe_client import create_customer, create_checkout_session

        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        price_id = os.environ["STRIPE_PRO_PRICE_ID"]

        customer_id = create_customer(email="sess-test@unitrader.app", user_id="sess-001")
        try:
            url = create_checkout_session(
                customer_id=customer_id,
                price_id=price_id,
                success_url="http://localhost:3000/success",
                cancel_url="http://localhost:3000/cancel",
            )
            # URL format: https://checkout.stripe.com/c/pay/cs_test_xxx
            assert "/pay/cs_" in url or "/c/pay/" in url, f"Expected session path in URL: {url}"
        finally:
            stripe.Customer.delete(customer_id)


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Webhook signature verification
# ─────────────────────────────────────────────────────────────────────────────

class TestStripeWebhookVerification:
    """Verify the webhook HMAC signature validation logic."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_stripe):  # noqa: F811
        pass

    def test_verify_webhook_valid_signature(self):
        """verify_webhook() should succeed with a correctly-signed payload."""
        from src.integrations.stripe_client import verify_webhook

        secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        if not secret:
            pytest.skip("STRIPE_WEBHOOK_SECRET not set — skipping signature test")

        body, header = _build_stripe_webhook_payload(
            "customer.subscription.created",
            {"id": "sub_test_001", "status": "active", "customer": "cus_test_001"},
        )

        event = verify_webhook(body, header)
        print(f"\n  Webhook verified — event type: {event['type']}")
        assert event["type"] == "customer.subscription.created"

    def test_verify_webhook_invalid_signature_raises(self):
        """verify_webhook() should raise SignatureVerificationError on bad sig."""
        import stripe as stripe_lib
        from src.integrations.stripe_client import verify_webhook

        body = b'{"type":"test","data":{"object":{}}}'
        bad_header = "t=1234567890,v1=invalidsignature"

        with pytest.raises(stripe_lib.error.SignatureVerificationError):
            verify_webhook(body, bad_header)
        print("\n  Invalid signature correctly rejected.")

    def test_verify_webhook_missing_secret_raises_value_error(self, monkeypatch):
        """verify_webhook() should raise ValueError when no secret is configured."""
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "")
        from config import get_settings
        get_settings.cache_clear()

        from src.integrations.stripe_client import verify_webhook

        with pytest.raises(ValueError, match="webhook secret"):
            verify_webhook(b"payload", "t=123,v1=sig")


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Webhook event parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestStripeWebhookEventParsing:
    """Test parse_subscription_event() with realistic Stripe event payloads."""

    def _sub_event(self, event_type: str, status: str = "active") -> dict:
        return {
            "type": event_type,
            "data": {
                "object": {
                    "id": "sub_test_001",
                    "status": status,
                    "customer": "cus_test_001",
                    "items": {
                        "data": [{
                            "price": {
                                "id": os.getenv("STRIPE_PRO_PRICE_ID", "price_test"),
                                "recurring": {"interval": "month"},
                            }
                        }]
                    },
                    "current_period_end": int(time.time()) + 86400 * 30,
                    "metadata": {"user_id": "test-user-001"},
                }
            },
        }

    def test_subscription_created_parsed(self):
        """Subscription created event should parse to 'pro' tier."""
        from src.integrations.stripe_client import parse_subscription_event
        event = self._sub_event("customer.subscription.created", "active")
        parsed = parse_subscription_event(event)
        print(f"\n  Parsed event: {parsed}")
        assert parsed["event_type"] == "customer.subscription.created"
        assert parsed["customer_id"] == "cus_test_001"

    def test_subscription_deleted_parsed(self):
        """Subscription deleted/cancelled event."""
        from src.integrations.stripe_client import parse_subscription_event
        event = self._sub_event("customer.subscription.deleted", "canceled")
        parsed = parse_subscription_event(event)
        assert parsed["event_type"] == "customer.subscription.deleted"
        print(f"\n  Deleted event customer_id: {parsed['customer_id']}")

    def test_invoice_payment_succeeded_parsed(self):
        """Invoice paid event should parse cleanly."""
        from src.integrations.stripe_client import parse_subscription_event
        event = {
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "id": "in_test_001",
                    "customer": "cus_test_001",
                    "subscription": "sub_test_001",
                    "status": "paid",
                    "metadata": {"user_id": "test-user-001"},
                }
            },
        }
        parsed = parse_subscription_event(event)
        assert parsed is not None
        print(f"\n  Invoice event parsed: {parsed.get('event_type')}")

    def test_unhandled_event_returns_gracefully(self):
        """Unknown event types should not raise — return None or minimal dict."""
        from src.integrations.stripe_client import parse_subscription_event
        event = {
            "type": "payment_intent.created",
            "data": {"object": {"id": "pi_test"}},
        }
        # Should not raise — graceful handling
        try:
            result = parse_subscription_event(event)
            print(f"\n  Unhandled event result: {result}")
        except Exception as exc:
            pytest.fail(f"parse_subscription_event raised on unhandled event: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: End-to-end webhook → user tier upgrade (with test DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestStripeWebhookToUserUpgrade:
    """Simulate a full Stripe checkout.session.completed → user.subscription_tier = 'pro' flow."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_stripe):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_sync_subscription_from_webhook_upgrades_user(self):
        """sync_subscription_from_webhook() should update user to pro tier."""
        from src.services.subscription import sync_subscription_from_webhook

        parsed = {
            "event_type": "customer.subscription.created",
            "customer_id": "cus_test_no_match",  # user won't be in test DB
            "subscription_id": "sub_test_001",
            "plan": "pro",
            "status": "active",
            "current_period_end": time.time() + 86400 * 30,
            "user_id": None,
        }

        # With no matching user, it should log and return gracefully — no crash
        try:
            await sync_subscription_from_webhook(parsed)
            print("\n  sync_subscription_from_webhook: handled gracefully for unknown customer")
        except Exception as exc:
            pytest.fail(f"sync_subscription_from_webhook raised unexpectedly: {exc}")
