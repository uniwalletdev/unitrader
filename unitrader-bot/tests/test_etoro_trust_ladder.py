"""
tests/test_etoro_trust_ladder.py — unit tests for the eToro safety helpers.

Covers both layers of the Trust Ladder safety gate:
  * Layer 1: ``check_etoro_connect_allowed`` — connect-time block
  * Layer 2: ``resolve_effective_etoro_environment`` — runtime override

Uses in-memory SQLite. No network. No Clerk. No Sentry. No real Anthropic
calls. Mirrors the fixture pattern in tests/test_orchestrator.py.
"""

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from database import AsyncSessionLocal, Base
from models import AuditLog, User
from src.services.etoro_trust_ladder import (
    EVENT_CONNECT_BLOCKED,
    EVENT_TRUST_LADDER_OVERRIDE,
    REASON_FEATURE_DISABLED,
    REASON_REAL_REQUIRES_STAGE_3,
    REASON_TRUST_LADDER_BELOW_3,
    check_etoro_connect_allowed,
    resolve_effective_etoro_environment,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_tables():
    import models  # noqa: F401 — register the models on Base
    from database import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_user(db):
    uid = str(uuid.uuid4())[:8]
    user = User(
        id=f"etl-{uid}",
        email=f"etl-{uid}@test.unitrader.app",
        password_hash="x",
        ai_name="TestAI",
        subscription_tier="pro",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _audit_rows(db, user_id: str, event_type: str) -> list[AuditLog]:
    result = await db.execute(
        select(AuditLog).where(
            AuditLog.user_id == user_id,
            AuditLog.event_type == event_type,
        )
    )
    return list(result.scalars().all())


# ─── Layer 1 — check_etoro_connect_allowed ───────────────────────────────────

class TestConnectGuard:
    """Connect-time guard. Trust Ladder stage < 3 must never store Real keys,
    and the feature flag kills everything when off."""

    @pytest.mark.asyncio
    async def test_stage_1_real_is_blocked(self, db, test_user):
        with pytest.raises(HTTPException) as exc:
            await check_etoro_connect_allowed(
                user_id=test_user.id,
                environment="real",
                trust_ladder_stage=1,
                db=db,
                feature_enabled=True,
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == REASON_REAL_REQUIRES_STAGE_3
        await db.commit()
        rows = await _audit_rows(db, test_user.id, EVENT_CONNECT_BLOCKED)
        assert len(rows) == 1
        assert rows[0].event_details["reason"] == REASON_REAL_REQUIRES_STAGE_3
        assert rows[0].event_details["attempted_environment"] == "real"

    @pytest.mark.asyncio
    async def test_stage_2_real_is_blocked(self, db, test_user):
        with pytest.raises(HTTPException) as exc:
            await check_etoro_connect_allowed(
                user_id=test_user.id,
                environment="real",
                trust_ladder_stage=2,
                db=db,
                feature_enabled=True,
            )
        assert exc.value.status_code == 403
        await db.commit()
        rows = await _audit_rows(db, test_user.id, EVENT_CONNECT_BLOCKED)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_stage_3_real_is_allowed(self, db, test_user):
        # Does not raise.
        await check_etoro_connect_allowed(
            user_id=test_user.id,
            environment="real",
            trust_ladder_stage=3,
            db=db,
            feature_enabled=True,
        )
        await db.commit()
        # No audit row for successful connects — those are covered by
        # the generic api_key_added / api_key_test flows.
        rows = await _audit_rows(db, test_user.id, EVENT_CONNECT_BLOCKED)
        assert rows == []

    @pytest.mark.asyncio
    async def test_stage_1_demo_is_allowed(self, db, test_user):
        await check_etoro_connect_allowed(
            user_id=test_user.id,
            environment="demo",
            trust_ladder_stage=1,
            db=db,
            feature_enabled=True,
        )
        await db.commit()
        rows = await _audit_rows(db, test_user.id, EVENT_CONNECT_BLOCKED)
        assert rows == []

    @pytest.mark.asyncio
    async def test_feature_disabled_blocks_everything(self, db, test_user):
        # Even stage 3 + real gets refused when the kill switch is off.
        with pytest.raises(HTTPException) as exc:
            await check_etoro_connect_allowed(
                user_id=test_user.id,
                environment="real",
                trust_ladder_stage=3,
                db=db,
                feature_enabled=False,
            )
        assert exc.value.status_code == 503
        await db.commit()
        rows = await _audit_rows(db, test_user.id, EVENT_CONNECT_BLOCKED)
        assert len(rows) == 1
        assert rows[0].event_details["reason"] == REASON_FEATURE_DISABLED


# ─── Layer 2 — resolve_effective_etoro_environment ───────────────────────────

class TestRuntimeOverride:
    """Runtime override. Even if a Real row somehow exists for a stage<3 user,
    we must force demo at execution time."""

    @pytest.mark.asyncio
    async def test_stage_1_real_is_forced_demo(self, db, test_user):
        env, overridden = await resolve_effective_etoro_environment(
            user_id=test_user.id,
            stored_environment="real",
            trust_ladder_stage=1,
            db=db,
            symbol="AAPL",
        )
        assert env == "demo"
        assert overridden is True
        await db.commit()
        rows = await _audit_rows(db, test_user.id, EVENT_TRUST_LADDER_OVERRIDE)
        assert len(rows) == 1
        d = rows[0].event_details
        assert d["stored_environment"] == "real"
        assert d["effective_environment"] == "demo"
        assert d["trust_ladder_stage"] == 1
        assert d["reason"] == REASON_TRUST_LADDER_BELOW_3
        assert d["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_stage_3_real_passes_through(self, db, test_user):
        env, overridden = await resolve_effective_etoro_environment(
            user_id=test_user.id,
            stored_environment="real",
            trust_ladder_stage=3,
            db=db,
        )
        assert env == "real"
        assert overridden is False
        await db.commit()
        rows = await _audit_rows(db, test_user.id, EVENT_TRUST_LADDER_OVERRIDE)
        assert rows == []

    @pytest.mark.asyncio
    async def test_stage_1_demo_passes_through_no_audit(self, db, test_user):
        env, overridden = await resolve_effective_etoro_environment(
            user_id=test_user.id,
            stored_environment="demo",
            trust_ladder_stage=1,
            db=db,
        )
        assert env == "demo"
        assert overridden is False
        await db.commit()
        rows = await _audit_rows(db, test_user.id, EVENT_TRUST_LADDER_OVERRIDE)
        assert rows == []

    @pytest.mark.asyncio
    async def test_unknown_stored_value_normalises_to_demo(self, db, test_user):
        env, overridden = await resolve_effective_etoro_environment(
            user_id=test_user.id,
            stored_environment="something_weird",
            trust_ladder_stage=3,
            db=db,
        )
        assert env == "demo"
        assert overridden is False
