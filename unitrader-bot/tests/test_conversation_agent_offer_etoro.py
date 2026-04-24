"""
tests/test_conversation_agent_offer_etoro.py — unit tests for
``_build_onboarding_system_prompt`` and the eToro offer templates.

Pure prompt-construction tests. No Claude calls, no httpx, no network.
All branches of the gate are covered:

  * feature flag on/off
  * onboarding_complete true/false
  * class_detected_at set/None
  * user has any active ExchangeAPIKey row yes/no
  * every ``trader_class`` value maps to its own template

Uses in-memory SQLite via the shared conftest pattern.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import pytest_asyncio

from database import AsyncSessionLocal, Base
from models import ExchangeAPIKey, User, UserSettings
from src.agents.core.conversation_agent import (
    _ETORO_OFFER_TEMPLATES,
    _ONBOARDING_SYSTEM_PROMPT,
    _build_onboarding_system_prompt,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_tables():
    # Function-scoped to match pytest.ini's asyncio_default_fixture_loop_scope.
    # create_all is idempotent on the shared :memory: engine; cheap per-test.
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
    onboarding_complete: bool = False,
) -> User:
    uid = f"offer-{uuid.uuid4().hex[:8]}"
    user = User(
        id=uid,
        email=f"{uid}@t.local",
        password_hash="x",
        ai_name="Nova",
        subscription_tier="pro",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    us = UserSettings(
        user_id=uid,
        trader_class=trader_class,
        class_detected_at=class_detected_at,
        onboarding_complete=onboarding_complete,
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


# ─── Gate tests ──────────────────────────────────────────────────────────────

class TestOfferGate:
    """Every gate must pass before the offer block is appended. Any single
    failing condition returns the bare prompt with no mention of eToro."""

    @pytest.mark.asyncio
    async def test_feature_flag_off_returns_bare_prompt(self, db):
        user = await _make_user(
            db,
            trader_class="complete_novice",
            class_detected_at=datetime.now(timezone.utc),
        )
        with patch("src.agents.core.conversation_agent.settings") as s:
            s.feature_etoro_enabled = False
            prompt = await _build_onboarding_system_prompt(user.id, db)
        assert prompt == _ONBOARDING_SYSTEM_PROMPT
        assert "eToro" not in prompt

    @pytest.mark.asyncio
    async def test_no_user_settings_row_returns_bare(self, db):
        # User exists, no UserSettings row was created.
        uid = f"nous-{uuid.uuid4().hex[:8]}"
        db.add(User(
            id=uid, email=f"{uid}@t.local", password_hash="x",
            ai_name="N", subscription_tier="pro", is_active=True,
        ))
        await db.commit()
        with patch("src.agents.core.conversation_agent.settings") as s:
            s.feature_etoro_enabled = True
            prompt = await _build_onboarding_system_prompt(uid, db)
        assert prompt == _ONBOARDING_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_onboarding_complete_returns_bare(self, db):
        user = await _make_user(
            db,
            trader_class="experienced",
            class_detected_at=datetime.now(timezone.utc),
            onboarding_complete=True,
        )
        with patch("src.agents.core.conversation_agent.settings") as s:
            s.feature_etoro_enabled = True
            prompt = await _build_onboarding_system_prompt(user.id, db)
        assert prompt == _ONBOARDING_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_class_not_yet_detected_returns_bare(self, db):
        user = await _make_user(
            db,
            trader_class="complete_novice",
            class_detected_at=None,  # not yet classified
        )
        with patch("src.agents.core.conversation_agent.settings") as s:
            s.feature_etoro_enabled = True
            prompt = await _build_onboarding_system_prompt(user.id, db)
        assert prompt == _ONBOARDING_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_active_exchange_already_connected_returns_bare(self, db):
        user = await _make_user(
            db,
            trader_class="experienced",
            class_detected_at=datetime.now(timezone.utc),
        )
        await _attach_active_key(db, user.id, exchange="alpaca")
        with patch("src.agents.core.conversation_agent.settings") as s:
            s.feature_etoro_enabled = True
            prompt = await _build_onboarding_system_prompt(user.id, db)
        assert prompt == _ONBOARDING_SYSTEM_PROMPT


# ─── Template tests ─────────────────────────────────────────────────────────

class TestOfferTemplatePerTraderClass:
    """When all gates pass, the offer block for the correct trader_class
    must be appended. Verifies all 6 classes + the 'Apex' anti-hardcode rule."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", [
        "complete_novice",
        "curious_saver",
        "self_taught",
        "experienced",
        "semi_institutional",
        "crypto_native",
    ])
    async def test_offer_block_appended_for_class(self, db, cls):
        user = await _make_user(
            db,
            trader_class=cls,
            class_detected_at=datetime.now(timezone.utc),
        )
        with patch("src.agents.core.conversation_agent.settings") as s:
            s.feature_etoro_enabled = True
            prompt = await _build_onboarding_system_prompt(user.id, db)
        # Starts with the unchanged base prompt.
        assert prompt.startswith(_ONBOARDING_SYSTEM_PROMPT)
        # Offer block is present.
        assert "eToro offer" in prompt
        # The class-specific template copy appears verbatim.
        assert _ETORO_OFFER_TEMPLATES[cls] in prompt
        # The structured tool contract is signposted.
        assert "offer_etoro_accepted" in prompt
        # Trust Ladder override is mentioned so Claude does not pre-check.
        assert "Stage 3" in prompt

    @pytest.mark.asyncio
    async def test_offer_block_never_hardcodes_apex(self, db):
        user = await _make_user(
            db,
            trader_class="complete_novice",
            class_detected_at=datetime.now(timezone.utc),
        )
        with patch("src.agents.core.conversation_agent.settings") as s:
            s.feature_etoro_enabled = True
            prompt = await _build_onboarding_system_prompt(user.id, db)
        # The injected block should instruct Claude to use the user's chosen
        # ai_name rather than the literal "Apex" or "Unitrader".
        offer_block = prompt[len(_ONBOARDING_SYSTEM_PROMPT):]
        assert "user's chosen AI name" in offer_block
        assert "never 'Apex'" in offer_block
