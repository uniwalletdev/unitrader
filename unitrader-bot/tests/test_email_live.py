"""
tests/test_email_live.py — Live integration tests for Resend email delivery.

Tests the full email pipeline:
  1. Direct Resend API send (raw SDK call)
  2. The _send() helper in email_sequences.py
  3. All four trial email templates render valid HTML
  4. Full drip sequence simulation for a mock user

═══════════════════════════════════════════════════════════
SETUP INSTRUCTIONS
═══════════════════════════════════════════════════════════

1. Sign up: https://resend.com (free tier: 100 emails/day)
2. API Keys → Create API Key → copy
3. Add a verified domain OR use the Resend sandbox domain
4. Add to .env.test:
       RESEND_API_KEY=re_xxxxxxxxxxxx
       EMAIL_FROM=noreply@unitrader.app        (must match your verified domain)
       TEST_EMAIL_TO=your-personal@email.com   (where to receive test emails)

5. Run:
       pytest tests/test_email_live.py -v -s

You should receive the test email in your inbox within ~30 seconds.
═══════════════════════════════════════════════════════════
"""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.live, pytest.mark.email]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_user(days_left: int = 7) -> SimpleNamespace:
    """Return a mock User for testing email templates."""
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id="test-user-email-001",
        email=os.getenv("TEST_EMAIL_TO", "test@unitrader.app"),
        ai_name="TradingBotAlpha",
        subscription_tier="free",
        trial_status="active",
        trial_started_at=now - timedelta(days=14 - days_left),
        trial_end_date=now + timedelta(days=days_left),
        is_active=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Direct Resend SDK
# ─────────────────────────────────────────────────────────────────────────────

class TestResendDirectAPI:
    """Call the Resend SDK directly — validates the key and domain work."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_resend):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_send_plain_text_email(self):
        """Send the simplest possible email — confirm API accepts it."""
        import resend
        resend.api_key = os.environ["RESEND_API_KEY"]

        to_addr  = os.getenv("TEST_EMAIL_TO", "delivered@resend.dev")  # Resend sandbox address
        from_addr = os.getenv("EMAIL_FROM", "onboarding@resend.dev")   # Resend test sender

        response = resend.Emails.send({
            "from": from_addr,
            "to": to_addr,
            "subject": "[Unitrader Test] API Integration Check",
            "html": "<h2>Test email from Unitrader</h2><p>If you see this, Resend is working.</p>",
        })

        print(f"\n  Resend response: {response}")
        assert response is not None, "Resend returned None"
        # The SDK returns an object with an 'id' key on success
        email_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        assert email_id, f"Expected email ID in response, got: {response}"
        print(f"  Email ID: {email_id} — delivery queued.")

    @pytest.mark.asyncio
    async def test_send_html_email_with_styling(self):
        """Send a styled HTML email to verify it renders correctly."""
        import resend
        resend.api_key = os.environ["RESEND_API_KEY"]

        html = """
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto;
                    background:#0d1117;color:#e6edf3;padding:32px;border-radius:12px;">
          <h1 style="color:#7c3aed;">Unitrader</h1>
          <p>Your AI trading companion is <strong style="color:#10b981;">live</strong>.</p>
          <hr style="border-color:#30363d;" />
          <p style="font-size:12px;color:#8b949e;">
            This is a test email from the Unitrader integration test suite.
          </p>
        </div>
        """

        response = resend.Emails.send({
            "from": os.getenv("EMAIL_FROM", "onboarding@resend.dev"),
            "to": os.getenv("TEST_EMAIL_TO", "delivered@resend.dev"),
            "subject": "[Unitrader Test] Styled HTML Email",
            "html": html,
        })
        email_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        assert email_id, "HTML email should return an ID"
        print(f"\n  Styled email ID: {email_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: The _send() helper in email_sequences.py
# ─────────────────────────────────────────────────────────────────────────────

class TestEmailSendHelper:
    """Test the internal _send() wrapper used by the trial drip sequence."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_resend):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_send_helper_returns_true_on_success(self):
        """_send() should return True when Resend accepts the email."""
        from src.services.email_sequences import _send

        result = await _send(
            to=os.getenv("TEST_EMAIL_TO", "delivered@resend.dev"),
            subject="[Unitrader Test] _send() helper check",
            html="<p>Testing the internal _send() helper.</p>",
        )
        print(f"\n  _send() returned: {result}")
        assert result is True, "_send() should return True on success"

    @pytest.mark.asyncio
    async def test_send_helper_returns_false_without_api_key(self, monkeypatch):
        """_send() should gracefully return False when no API key is set."""
        monkeypatch.setenv("RESEND_API_KEY", "")
        # Force settings to re-read the env
        from config import get_settings
        get_settings.cache_clear()

        from src.services.email_sequences import _send
        result = await _send(
            to="test@example.com",
            subject="Should not send",
            html="<p>No key configured</p>",
        )
        assert result is False, "Should return False gracefully when key is missing"

        # Restore key
        monkeypatch.setenv("RESEND_API_KEY", os.environ.get("RESEND_API_KEY", ""))
        get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Trial email templates render valid HTML
# ─────────────────────────────────────────────────────────────────────────────

class TestTrialEmailTemplates:
    """Verify all four trial drip templates produce valid, non-empty HTML."""

    def _import_templates(self):
        """Import private template functions from email_sequences."""
        import importlib
        import src.services.email_sequences as mod
        return mod

    def test_day7_template_renders(self):
        mod = self._import_templates()
        user = _make_mock_user(days_left=7)
        html = mod._day7_html(
            ai_name=user.ai_name,
            profit=567.89,
            total_trades=42,
            win_rate=81.0,
        )
        assert "<html" in html.lower() or "<div" in html.lower(), "Should produce HTML"
        assert user.ai_name in html, "Should mention AI name"
        assert "567" in html or "profit" in html.lower(), "Should mention profit"
        print(f"\n  Day 7 template: {len(html)} chars, mentions AI name: OK")

    def test_day11_template_renders(self):
        mod = self._import_templates()
        user = _make_mock_user(days_left=3)
        html = mod._day11_html(ai_name=user.ai_name, days_left=3)
        assert len(html) > 100, "Template should not be empty"
        assert user.ai_name in html
        print(f"\n  Day 11 template: {len(html)} chars")

    def test_day13_template_renders(self):
        mod = self._import_templates()
        user = _make_mock_user(days_left=1)
        html = mod._day13_html(ai_name=user.ai_name)
        assert len(html) > 100
        assert user.ai_name in html
        print(f"\n  Day 13 template: {len(html)} chars")

    def test_expired_template_renders(self):
        mod = self._import_templates()
        user = _make_mock_user(days_left=0)
        html = mod._expired_html(ai_name=user.ai_name)
        assert len(html) > 100
        print(f"\n  Expired template: {len(html)} chars")

    def test_html_base_wraps_content(self):
        mod = self._import_templates()
        html = mod._html_base("<p>Test content</p>")
        assert "Test content" in html
        assert "Unitrader" in html
        assert "background" in html  # Has inline styles


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Live drip sequence simulation (send all 4 trial emails)
# ─────────────────────────────────────────────────────────────────────────────

class TestTrialEmailDrip:
    """
    Send all four trial emails in sequence to TEST_EMAIL_TO.
    This verifies the full pipeline end-to-end: template → _send() → Resend → inbox.
    """

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_resend):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_day7_email_live(self):
        """Send the Day 7 'halfway through' email."""
        from src.services.email_sequences import _send, _day7_html

        user = _make_mock_user(days_left=7)
        html = _day7_html(
            ai_name=user.ai_name,
            profit=412.50,
            total_trades=28,
            win_rate=78.6,
        )
        result = await _send(
            to=user.email,
            subject=f"[TEST] 🚀 {user.ai_name} is halfway through your trial!",
            html=html,
        )
        print(f"\n  Day 7 email → {user.email}: sent={result}")
        assert result is True

    @pytest.mark.asyncio
    async def test_day3_email_live(self):
        """Send the Day 3 'last 3 days' email."""
        from src.services.email_sequences import _send, _day11_html

        user = _make_mock_user(days_left=3)
        html = _day11_html(ai_name=user.ai_name, days_left=3)
        result = await _send(
            to=user.email,
            subject=f"[TEST] ⏰ 3 days left with {user.ai_name}!",
            html=html,
        )
        print(f"\n  Day 3 email → {user.email}: sent={result}")
        assert result is True

    @pytest.mark.asyncio
    async def test_day1_email_live(self):
        """Send the 'tomorrow: trial expires' email."""
        from src.services.email_sequences import _send, _day13_html

        user = _make_mock_user(days_left=1)
        html = _day13_html(ai_name=user.ai_name)
        result = await _send(
            to=user.email,
            subject=f"[TEST] 🔴 Tomorrow: {user.ai_name}'s trial expires!",
            html=html,
        )
        print(f"\n  Day 1 email → {user.email}: sent={result}")
        assert result is True

    @pytest.mark.asyncio
    async def test_expired_email_live(self):
        """Send the 'trial expired' email."""
        from src.services.email_sequences import _send, _expired_html

        user = _make_mock_user(days_left=0)
        html = _expired_html(ai_name=user.ai_name)
        result = await _send(
            to=user.email,
            subject=f"[TEST] Your Unitrader trial has ended",
            html=html,
        )
        print(f"\n  Expired email → {user.email}: sent={result}")
        assert result is True
