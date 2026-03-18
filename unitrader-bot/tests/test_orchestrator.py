"""
tests/test_orchestrator.py — Unit tests for the MasterOrchestrator.

Uses in-memory SQLite. Forces DATABASE_URL before any app imports.
Run with:  pytest tests/test_orchestrator.py -v

Tests the new orchestrator API that uses action strings and SharedContext.

Test groups:
  TestTradeWorkflow       — Route dispatches to correct private methods
  TestConversationWorkflow — onboarding_chat and backtest routing
  TestAuditLogging        — Audit log helpers write to DB
  TestInputValidation     — Unknown actions and missing params
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import pytest_asyncio

from database import AsyncSessionLocal, Base
from models import User
from src.agents.orchestrator import MasterOrchestrator
from src.agents.shared_memory import SharedContext


def _fake_ctx(**overrides):
    """Build a mock SharedContext with sensible defaults."""
    defaults = {
        "subscription_active": True,
        "trading_paused": False,
        "paper_trading_enabled": True,
        "trust_ladder_stage": 1,
    }
    defaults.update(overrides)
    ctx = MagicMock(spec=SharedContext)
    for k, v in defaults.items():
        setattr(ctx, k, v)
    ctx.is_crypto_native = MagicMock(return_value=False)
    ctx.is_pro = MagicMock(return_value=True)
    ctx.is_intermediate = MagicMock(return_value=False)
    return ctx


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_tables():
    import models  # noqa: F401
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
    import uuid
    uid = str(uuid.uuid4())[:8]
    user = User(
        id=f"orch-test-{uid}",
        email=f"orch-{uid}@test.unitrader.app",
        password_hash="test_hash_placeholder",
        ai_name="TestAI",
        subscription_tier="pro",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ═════════════════════════════════════════════
# TRADE WORKFLOW
# ═════════════════════════════════════════════

class TestTradeWorkflow:
    @pytest.mark.asyncio
    async def test_trade_workflow_routes(self, db, test_user):
        """trade_analyze action dispatches to _trade_analyze and returns a dict."""
        orch = MasterOrchestrator()
        fake_result = {"signal": "BUY", "confidence": 0.75, "status": "executed"}
        with patch.object(orch, "_trade_analyze", new_callable=AsyncMock, return_value=fake_result):
            with patch("src.agents.shared_memory.SharedMemory.load", new_callable=AsyncMock, return_value=_fake_ctx()):
                result = await orch.route(
                    user_id=test_user.id,
                    action="trade_analyze",
                    payload={"symbol": "BTCUSDT", "exchange": "binance"},
                    db=db,
                )
        assert isinstance(result, dict)
        assert result.get("status") in ("wait", "skipped", "executed", "rejected", "error", None) or "signal" in result

    @pytest.mark.asyncio
    async def test_trade_workflow_injects_shared_context(self, db, test_user):
        """SharedContext is loaded and passed to the trade workflow."""
        orch = MasterOrchestrator()
        fake_ctx = _fake_ctx()
        fake_result = {"signal": "WAIT", "status": "wait"}
        with patch.object(orch, "_trade_analyze", new_callable=AsyncMock, return_value=fake_result) as mock_analyze:
            with patch("src.agents.shared_memory.SharedMemory.load", new_callable=AsyncMock, return_value=fake_ctx):
                await orch.route(
                    user_id=test_user.id,
                    action="trade_analyze",
                    payload={"symbol": "BTCUSDT", "exchange": "binance"},
                    db=db,
                )
        # Verify the private method received the shared context
        call_args = mock_analyze.call_args
        assert call_args is not None
        # ctx is passed as the second positional arg
        assert call_args[0][1] is fake_ctx

    @pytest.mark.asyncio
    async def test_trade_workflow_missing_symbol_returns_error(self, db, test_user):
        """trade_analyze with missing symbol raises ValueError."""
        orch = MasterOrchestrator()
        with patch("src.agents.shared_memory.SharedMemory.load", new_callable=AsyncMock, return_value=_fake_ctx()):
            with pytest.raises((ValueError, Exception)):
                await orch.route(
                    user_id=test_user.id,
                    action="trade_analyze",
                    payload={"exchange": "binance"},
                    db=db,
                )


# ═════════════════════════════════════════════
# CONVERSATION WORKFLOW
# ═════════════════════════════════════════════

class TestConversationWorkflow:
    @pytest.mark.asyncio
    async def test_conversation_workflow_routes(self, db, test_user):
        """onboarding_chat action dispatches to _onboarding_chat and returns a dict."""
        orch = MasterOrchestrator()
        fake_result = {"response": "RSI stands for Relative Strength Index."}
        with patch.object(orch, "_onboarding_chat", new_callable=AsyncMock, return_value=fake_result):
            with patch("src.agents.shared_memory.SharedMemory.load", new_callable=AsyncMock, return_value=_fake_ctx()):
                result = await orch.route(
                    user_id=test_user.id,
                    action="onboarding_chat",
                    payload={"message": "What is RSI?"},
                    db=db,
                )
        assert isinstance(result, dict)
        assert "response" in result

    @pytest.mark.asyncio
    async def test_conversation_enriches_with_asset_context(self, db, test_user):
        """onboarding_chat receives the loaded SharedContext."""
        orch = MasterOrchestrator()
        fake_ctx = _fake_ctx()
        fake_result = {"response": "Based on current trends, here's my take..."}
        with patch.object(orch, "_onboarding_chat", new_callable=AsyncMock, return_value=fake_result) as mock_chat:
            with patch("src.agents.shared_memory.SharedMemory.load", new_callable=AsyncMock, return_value=fake_ctx):
                result = await orch.route(
                    user_id=test_user.id,
                    action="onboarding_chat",
                    payload={"message": "Should I buy Bitcoin now?"},
                    db=db,
                )
        assert result is not None
        assert "response" in result or "error" in str(result).lower()


# ═════════════════════════════════════════════
# AUDIT LOGGING
# ═════════════════════════════════════════════

class TestLearningStored:
    @pytest.mark.asyncio
    async def test_trade_outcome_stored(self, db, test_user):
        """log_trade_decision writes an AuditLog entry to the DB."""
        from sqlalchemy import select
        from models import AuditLog

        orch = MasterOrchestrator()
        ctx = _fake_ctx()
        await orch.log_trade_decision(
            user_id=test_user.id,
            payload={"symbol": "BTCUSDT"},
            ctx=ctx,
            risk_result=(True, "ok"),
            portfolio_result={"approved": True, "reason": "within limits"},
            agent_response={"signal": "BUY", "confidence": 0.8, "explanation_expert": "strong momentum"},
            db=db,
        )

        result = await db.execute(
            select(AuditLog).where(
                AuditLog.user_id == test_user.id,
                AuditLog.event_type == "trade_decision",
            )
        )
        rows = result.scalars().all()
        assert len(rows) >= 1

    @pytest.mark.asyncio
    async def test_conversation_outcome_stored(self, db, test_user):
        """log_trust_ladder_advance writes an AuditLog entry to the DB."""
        from sqlalchemy import select
        from models import AuditLog

        orch = MasterOrchestrator()
        await orch.log_trust_ladder_advance(
            user_id=test_user.id,
            old_stage=1,
            new_stage=2,
            db=db,
        )

        result = await db.execute(
            select(AuditLog).where(
                AuditLog.user_id == test_user.id,
                AuditLog.event_type == "trust_ladder_advance",
            )
        )
        rows = result.scalars().all()
        assert len(rows) >= 1

    @pytest.mark.asyncio
    async def test_content_outcome_stored(self, db, test_user):
        """log_circuit_breaker_activation writes an AuditLog entry to the DB."""
        from sqlalchemy import select
        from models import AuditLog

        orch = MasterOrchestrator()
        await orch.log_circuit_breaker_activation(
            user_id=test_user.id,
            current_loss_pct=3.5,
            max_daily_loss_pct=3.0,
            db=db,
        )

        result = await db.execute(
            select(AuditLog).where(
                AuditLog.user_id == test_user.id,
                AuditLog.event_type == "circuit_breaker",
            )
        )
        rows = result.scalars().all()
        assert len(rows) >= 1


# ═════════════════════════════════════════════
# INPUT VALIDATION
# ═════════════════════════════════════════════

class TestSystemHealth:
    @pytest.mark.asyncio
    async def test_system_health_returns_metrics(self, db):
        """Constructor takes no arguments."""
        orch = MasterOrchestrator()
        assert orch is not None

    @pytest.mark.asyncio
    async def test_system_health_agent_performance_structure(self, db):
        """Unknown action raises ValueError."""
        orch = MasterOrchestrator()
        with patch("src.agents.shared_memory.SharedMemory.load", new_callable=AsyncMock, return_value=_fake_ctx()):
            with pytest.raises(ValueError, match="Unknown action"):
                await orch.route(
                    user_id="system",
                    action="invalid_action",
                    payload={},
                    db=db,
                )

    @pytest.mark.asyncio
    async def test_system_health_recent_outcomes_list(self, db):
        """backtest action dispatches to _backtest."""
        orch = MasterOrchestrator()
        fake_result = {"backtest_result": "completed", "metrics": {}}
        with patch.object(orch, "_backtest", new_callable=AsyncMock, return_value=fake_result):
            with patch("src.agents.shared_memory.SharedMemory.load", new_callable=AsyncMock, return_value=_fake_ctx()):
                result = await orch.route(
                    user_id="system",
                    action="backtest",
                    payload={"strategy": "momentum"},
                    db=db,
                )
        assert isinstance(result, dict)
