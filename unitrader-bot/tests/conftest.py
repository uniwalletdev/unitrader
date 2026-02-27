"""
tests/conftest.py — Shared pytest configuration and fixtures for live integration tests.

Env setup:
  Copy .env.example → .env.test and fill in real sandbox credentials.
  All live tests read from .env.test (or current .env as fallback).

Markers:
  @pytest.mark.live      — requires real API keys; skipped in CI unless explicitly enabled
  @pytest.mark.exchange  — requires exchange sandbox keys
  @pytest.mark.email     — requires RESEND_API_KEY
  @pytest.mark.stripe    — requires STRIPE_SECRET_KEY
  @pytest.mark.claude    — requires ANTHROPIC_API_KEY

Run all live tests:
    pytest tests/ -m live -v

Run just exchange tests:
    pytest tests/test_exchanges_live.py -v

Run without live tests (unit only):
    pytest tests/ -m "not live" -v
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# ─── Path setup ──────────────────────────────────────────────────────────────
# Ensure the project root is on sys.path so imports resolve correctly
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load .env.test if present, else fall back to .env
_env_test = ROOT / ".env.test"
_env_main = ROOT / ".env"
_env_file = _env_test if _env_test.exists() else _env_main

from dotenv import load_dotenv
load_dotenv(_env_file, override=True)


# ─── pytest-asyncio: single event loop for all async tests ───────────────────
@pytest.fixture(scope="session")
def event_loop():
    """Provide a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ─── Marker registration ─────────────────────────────────────────────────────
def pytest_configure(config):
    config.addinivalue_line("markers", "live: marks test as a live integration test requiring real API keys")
    config.addinivalue_line("markers", "exchange: requires exchange sandbox/testnet API keys")
    config.addinivalue_line("markers", "email: requires RESEND_API_KEY")
    config.addinivalue_line("markers", "stripe: requires Stripe test-mode keys")
    config.addinivalue_line("markers", "claude: requires ANTHROPIC_API_KEY")


# ─── Skip helpers ────────────────────────────────────────────────────────────
def _skip_if_missing(*env_vars: str, reason_prefix: str = ""):
    """Return a pytest.mark.skip if any env var is empty."""
    missing = [v for v in env_vars if not os.getenv(v)]
    if missing:
        label = reason_prefix or "Live test"
        return pytest.mark.skip(reason=f"{label} skipped — missing env vars: {', '.join(missing)}")
    return None


# ─── Environment-level skip fixtures ─────────────────────────────────────────
@pytest.fixture(autouse=False)
def require_binance(request):
    skip = _skip_if_missing("BINANCE_API_KEY", "BINANCE_API_SECRET", reason_prefix="Binance")
    if skip:
        pytest.skip(skip.kwargs["reason"])


@pytest.fixture(autouse=False)
def require_alpaca(request):
    skip = _skip_if_missing("ALPACA_API_KEY", "ALPACA_API_SECRET", reason_prefix="Alpaca")
    if skip:
        pytest.skip(skip.kwargs["reason"])


@pytest.fixture(autouse=False)
def require_oanda(request):
    skip = _skip_if_missing("OANDA_API_KEY", "OANDA_ACCOUNT_ID", reason_prefix="OANDA")
    if skip:
        pytest.skip(skip.kwargs["reason"])


@pytest.fixture(autouse=False)
def require_resend(request):
    skip = _skip_if_missing("RESEND_API_KEY", reason_prefix="Resend")
    if skip:
        pytest.skip(skip.kwargs["reason"])


@pytest.fixture(autouse=False)
def require_stripe(request):
    skip = _skip_if_missing("STRIPE_SECRET_KEY", "STRIPE_PRO_PRICE_ID", reason_prefix="Stripe")
    if skip:
        pytest.skip(skip.kwargs["reason"])


@pytest.fixture(autouse=False)
def require_claude(request):
    skip = _skip_if_missing("ANTHROPIC_API_KEY", reason_prefix="Claude")
    if skip:
        pytest.skip(skip.kwargs["reason"])


# ─── Exchange client fixtures ─────────────────────────────────────────────────
@pytest.fixture
def binance_client():
    """Live Binance client using env credentials."""
    from src.integrations.exchange_client import BinanceClient
    client = BinanceClient(
        api_key=os.environ["BINANCE_API_KEY"],
        api_secret=os.environ["BINANCE_API_SECRET"],
    )
    yield client
    asyncio.get_event_loop().run_until_complete(client.aclose())


@pytest.fixture
def alpaca_client():
    """Live Alpaca paper-trading client using env credentials."""
    from src.integrations.exchange_client import AlpacaClient
    client = AlpacaClient(
        api_key=os.environ["ALPACA_API_KEY"],
        api_secret=os.environ["ALPACA_API_SECRET"],
        base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
    )
    yield client
    asyncio.get_event_loop().run_until_complete(client.aclose())


@pytest.fixture
def oanda_client():
    """Live OANDA practice client using env credentials."""
    from src.integrations.exchange_client import OandaClient
    client = OandaClient(
        api_key=os.environ["OANDA_API_KEY"],
        api_secret="",  # OANDA uses single token auth
        account_id=os.environ["OANDA_ACCOUNT_ID"],
    )
    yield client
    asyncio.get_event_loop().run_until_complete(client.aclose())


# ─── Test user fixture ────────────────────────────────────────────────────────
@pytest.fixture
def mock_user():
    """A minimal in-memory User-like object for tests that need a user but no DB."""
    from types import SimpleNamespace
    from datetime import datetime, timezone, timedelta
    return SimpleNamespace(
        id="test-user-live-001",
        email="test@unitrader.app",
        ai_name="TestBot",
        subscription_tier="pro",
        trial_status="active",
        trial_end_date=datetime.now(timezone.utc) + timedelta(days=7),
        is_active=True,
        stripe_customer_id=None,
    )


# ─── Settings override for tests ─────────────────────────────────────────────
@pytest.fixture(autouse=True)
def reload_settings():
    """Force settings to reload from env on each test (avoids cached stale values)."""
    from config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
