"""
tests/test_etoro_offer_card.py — unit tests for routers/etoro_offer.py.

Directly invokes the FastAPI endpoint handlers with a hand-built mock
``current_user`` to bypass auth. Each test constructs user state in an
in-memory SQLite session then asserts the JSON payload the router would
return.

Covers:
  * Every gate: feature flag, onboarding_complete, class_detected_at,
    active key, already-dismissed, no UserSettings row.
  * Per-class copy: 6 trader_class values → correct environment + template.
  * Anti-Apex hardcoding: body substitutes ``ai_name`` dynamically.
  * Dismiss endpoint: sets timestamp, is idempotent, gate blocks after.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import pytest_asyncio

from database import AsyncSessionLocal, Base
from models import ExchangeAPIKey, User, UserSettings
from src.agents.core.conversation_agent import _ETORO_OFFER_CARD_COPY


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_tables():
    # Function-scoped to match pytest.ini's asyncio_default_fixture_loop_scope.
    import models  # noqa: F401 — register models on Base
    from database import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


async def _make_user(
    db,
    *,
    trader_class: str = "complete_novice",
    class_detected_at: datetime | None = None,
    onboarding_complete: bool = True,
    etoro_offer_dismissed_at: datetime | None = None,
    ai_name: str = "Nova",
) -> User:
    uid = f"card-{uuid.uuid4().hex[:8]}"
    user = User(
        id=uid,
        email=f"{uid}@t.local",
        password_hash="x",
        ai_name=ai_name,
        subscription_tier="pro",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    us = UserSettings(
        user_id=uid,
        ai_name=ai_name,
        trader_class=trader_class,
        class_detected_at=class_detected_at,
        onboarding_complete=onboarding_complete,
        etoro_offer_dismissed_at=etoro_offer_dismissed_at,
    )
    db.add(us)
    await db.commit()
    return user


async def _attach_active_key(db, user_id: str, exchange: str = "alpaca") -> None:
    db.add(ExchangeAPIKey(
        user_id=user_id,
        exchange=exchange,
        encrypted_api_key="x" * 32,
        encrypted_api_secret="y" * 32,
        key_hash="h" * 16,
        is_active=True,
        is_paper=True,
    ))
    await db.commit()


def _mock_user(user: User) -> SimpleNamespace:
    return SimpleNamespace(id=user.id, email=user.email)


# ─── Gate tests (GET /api/etoro/offer-card) ─────────────────────────────────

class TestOfferCardGate:
    """Every gate must pass before ``show: True`` is returned. Each failing
    condition alone returns ``{show: False}`` with no extra data leaked."""

    @pytest.mark.asyncio
    async def test_feature_flag_off_returns_hidden(self, db):
        from routers.etoro_offer import get_offer_card
        user = await _make_user(
            db,
            trader_class="experienced",
            class_detected_at=datetime.now(timezone.utc),
        )
        with patch("routers.etoro_offer.app_settings") as s:
            s.feature_etoro_enabled = False
            payload = await get_offer_card(current_user=_mock_user(user), db=db)
        assert payload == {"show": False}

    @pytest.mark.asyncio
    async def test_no_user_settings_row_returns_hidden(self, db):
        from routers.etoro_offer import get_offer_card
        uid = f"nous-{uuid.uuid4().hex[:8]}"
        db.add(User(
            id=uid, email=f"{uid}@t.local", password_hash="x",
            ai_name="N", subscription_tier="pro", is_active=True,
        ))
        await db.commit()
        with patch("routers.etoro_offer.app_settings") as s:
            s.feature_etoro_enabled = True
            payload = await get_offer_card(
                current_user=SimpleNamespace(id=uid, email="x"), db=db,
            )
        assert payload == {"show": False}

    @pytest.mark.asyncio
    async def test_onboarding_incomplete_returns_hidden(self, db):
        from routers.etoro_offer import get_offer_card
        user = await _make_user(
            db,
            trader_class="experienced",
            class_detected_at=datetime.now(timezone.utc),
            onboarding_complete=False,
        )
        with patch("routers.etoro_offer.app_settings") as s:
            s.feature_etoro_enabled = True
            payload = await get_offer_card(current_user=_mock_user(user), db=db)
        assert payload == {"show": False}

    @pytest.mark.asyncio
    async def test_class_not_detected_returns_hidden(self, db):
        from routers.etoro_offer import get_offer_card
        user = await _make_user(
            db,
            trader_class="complete_novice",
            class_detected_at=None,
        )
        with patch("routers.etoro_offer.app_settings") as s:
            s.feature_etoro_enabled = True
            payload = await get_offer_card(current_user=_mock_user(user), db=db)
        assert payload == {"show": False}

    @pytest.mark.asyncio
    async def test_already_dismissed_returns_hidden(self, db):
        from routers.etoro_offer import get_offer_card
        user = await _make_user(
            db,
            trader_class="experienced",
            class_detected_at=datetime.now(timezone.utc),
            etoro_offer_dismissed_at=datetime.now(timezone.utc),
        )
        with patch("routers.etoro_offer.app_settings") as s:
            s.feature_etoro_enabled = True
            payload = await get_offer_card(current_user=_mock_user(user), db=db)
        assert payload == {"show": False}

    @pytest.mark.asyncio
    async def test_active_exchange_already_connected_returns_hidden(self, db):
        from routers.etoro_offer import get_offer_card
        user = await _make_user(
            db,
            trader_class="experienced",
            class_detected_at=datetime.now(timezone.utc),
        )
        await _attach_active_key(db, user.id, exchange="alpaca")
        with patch("routers.etoro_offer.app_settings") as s:
            s.feature_etoro_enabled = True
            payload = await get_offer_card(current_user=_mock_user(user), db=db)
        assert payload == {"show": False}


# ─── Per-class template ──────────────────────────────────────────────────────

class TestOfferCardPerClass:
    """When all gates pass, return the class-tailored copy. Verifies all 6
    trader classes + correct environment mapping + ai_name substitution."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls,expected_env", [
        ("complete_novice", "demo"),
        ("curious_saver", "demo"),
        ("self_taught", "demo"),
        ("experienced", "real"),
        ("semi_institutional", "real"),
        ("crypto_native", "real"),
    ])
    async def test_per_class_payload(self, db, cls, expected_env):
        from routers.etoro_offer import get_offer_card
        user = await _make_user(
            db,
            trader_class=cls,
            class_detected_at=datetime.now(timezone.utc),
            ai_name="Nova",
        )
        with patch("routers.etoro_offer.app_settings") as s:
            s.feature_etoro_enabled = True
            payload = await get_offer_card(current_user=_mock_user(user), db=db)

        assert payload["show"] is True
        assert payload["trader_class"] == cls
        assert payload["environment"] == expected_env
        assert payload["headline"] == _ETORO_OFFER_CARD_COPY[cls]["headline"]
        # ai_name is substituted into body
        assert "Nova" in payload["body"]
        assert "{ai_name}" not in payload["body"]
        # Never leak the default "Apex" literal when ai_name is customised
        assert "Apex" not in payload["body"]
        assert payload["cta"] == _ETORO_OFFER_CARD_COPY[cls]["cta"]


# ─── Dismiss endpoint ────────────────────────────────────────────────────────

class TestDismissEndpoint:

    @pytest.mark.asyncio
    async def test_dismiss_sets_timestamp_and_is_idempotent(self, db):
        from routers.etoro_offer import dismiss_offer_card, get_offer_card
        user = await _make_user(
            db,
            trader_class="experienced",
            class_detected_at=datetime.now(timezone.utc),
        )

        with patch("routers.etoro_offer.app_settings") as s:
            s.feature_etoro_enabled = True
            before = await get_offer_card(current_user=_mock_user(user), db=db)
        assert before["show"] is True

        # First dismiss writes timestamp (rowcount == 1)
        first = await dismiss_offer_card(current_user=_mock_user(user), db=db)
        assert first == {"ok": True, "updated": 1}

        # After dismiss, card is hidden
        with patch("routers.etoro_offer.app_settings") as s:
            s.feature_etoro_enabled = True
            after = await get_offer_card(current_user=_mock_user(user), db=db)
        assert after == {"show": False}

        # Second dismiss is a no-op (WHERE clause filters out already-set row)
        second = await dismiss_offer_card(current_user=_mock_user(user), db=db)
        assert second == {"ok": True, "updated": 0}
