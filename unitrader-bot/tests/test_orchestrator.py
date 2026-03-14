"""
tests/test_orchestrator.py — Unit tests for the MasterOrchestrator.

Uses in-memory SQLite. Forces DATABASE_URL before any app imports.
Run with:  pytest tests/test_orchestrator.py -v

NOTE: Tests for old orchestrator (TaskType enum) need to be rewritten
for the new orchestrator API that uses action strings and SharedContext.

Test groups (TODO):
  TestTradeAnalyze      — Trade analyze routes correctly, uses SharedContext
  TestTradeExecute      — Trade execute checks subscription and trading_paused
  TestOnboardingChat    — Chat mode works with context loaded
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, Base
from models import User
from src.agents.orchestrator import MasterOrchestrator, get_orchestrator
from src.agents.shared_memory import SharedContext, SharedMemory


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
        """Trade workflow is invoked for TRADE_SIGNAL and returns a result."""
        orch = MasterOrchestrator(db=db, user_id=test_user.id)
        result = await orch.route(
            TaskType.TRADE_SIGNAL,
            {"symbol": "BTCUSDT", "exchange": "binance"},
        )
        assert result.agents_used == ["trading_agent"]
        assert "result" in result.model_dump()
        assert result.result.get("status") in ("wait", "skipped", "executed", "rejected", "error")

    @pytest.mark.asyncio
    async def test_trade_workflow_injects_shared_context(self, db, test_user):
        """When shared context exists for asset, it is passed to the workflow."""
        from src.agents.memory import SharedMemory
        mem = SharedMemory(db)
        await mem.set_shared_context("BTCUSDT_sentiment", -0.5, "sentiment_agent", ttl_seconds=3600)
        await db.flush()

        orch = MasterOrchestrator(db=db, user_id=test_user.id)
        result = await orch.route(
            TaskType.TRADE_SIGNAL,
            {"symbol": "BTCUSDT", "exchange": "binance"},
        )
        assert result.learning_applied or result.result.get("status") in ("wait", "skipped", "error", "rejected")

    @pytest.mark.asyncio
    async def test_trade_workflow_missing_symbol_returns_error(self, db, test_user):
        orch = MasterOrchestrator(db=db, user_id=test_user.id)
        result = await orch.route(TaskType.TRADE_SIGNAL, {"exchange": "binance"})
        assert "error" in result.result.get("status", "") or "reason" in result.result


# ═════════════════════════════════════════════
# CONVERSATION WORKFLOW
# ═════════════════════════════════════════════

class TestConversationWorkflow:
    @pytest.mark.asyncio
    async def test_conversation_workflow_routes(self, db, test_user):
        orch = MasterOrchestrator(db=db, user_id=test_user.id)
        result = await orch.route(
            TaskType.USER_QUESTION,
            {"message": "What is RSI?"},
        )
        assert "conversation_agent" in result.agents_used
        assert "result" in result.model_dump()

    @pytest.mark.asyncio
    async def test_conversation_enriches_with_asset_context(self, db, test_user):
        from src.agents.memory import SharedMemory
        mem = SharedMemory(db)
        await mem.set_shared_context("BTCUSDT_trend", "bearish", "trend_agent", ttl_seconds=3600)
        await db.flush()

        orch = MasterOrchestrator(db=db, user_id=test_user.id)
        result = await orch.route(
            TaskType.USER_QUESTION,
            {"message": "Should I buy Bitcoin now?"},
        )
        assert result.result is not None
        assert "response" in result.result or "error" in str(result.result).lower() or "status" in result.result


# ═════════════════════════════════════════════
# LEARNING STORED
# ═════════════════════════════════════════════

class TestLearningStored:
    @pytest.mark.asyncio
    async def test_trade_outcome_stored(self, db, test_user):
        from sqlalchemy import select
        orch = MasterOrchestrator(db=db, user_id=test_user.id)
        await orch.route(TaskType.TRADE_SIGNAL, {"symbol": "BTCUSDT", "exchange": "binance"})
        await db.flush()

        result = await db.execute(
            select(AgentOutcomeModel).where(
                AgentOutcomeModel.agent_name == "trading_agent",
                AgentOutcomeModel.user_id == test_user.id,
            )
        )
        rows = result.scalars().all()
        assert len(rows) >= 1

    @pytest.mark.asyncio
    async def test_conversation_outcome_stored(self, db, test_user):
        from sqlalchemy import select
        orch = MasterOrchestrator(db=db, user_id=test_user.id)
        await orch.route(TaskType.USER_QUESTION, {"message": "Hello"})
        await db.flush()

        result = await db.execute(
            select(AgentOutcomeModel).where(
                AgentOutcomeModel.agent_name == "conversation_agent",
                AgentOutcomeModel.user_id == test_user.id,
            )
        )
        rows = result.scalars().all()
        assert len(rows) >= 1

    @pytest.mark.asyncio
    async def test_content_outcome_stored(self, db, test_user):
        from sqlalchemy import select
        orch = MasterOrchestrator(db=db, user_id=test_user.id)
        await orch.route(
            TaskType.CONTENT_CREATE,
            {"topic": "Risk management", "content_type": "blog"},
        )
        await db.flush()

        result = await db.execute(
            select(AgentOutcomeModel).where(
                AgentOutcomeModel.agent_name == "content_writer",
                AgentOutcomeModel.user_id == test_user.id,
            )
        )
        rows = result.scalars().all()
        assert len(rows) >= 1


# ═════════════════════════════════════════════
# SYSTEM HEALTH
# ═════════════════════════════════════════════

class TestSystemHealth:
    @pytest.mark.asyncio
    async def test_system_health_returns_metrics(self, db):
        orch = MasterOrchestrator(db=db, user_id="system")
        health = await orch.get_system_health()
        assert "agent_performance" in health
        assert "shared_context_summary" in health
        assert "recent_outcomes" in health
        assert "timestamp" in health

    @pytest.mark.asyncio
    async def test_system_health_agent_performance_structure(self, db):
        orch = MasterOrchestrator(db=db, user_id="system")
        health = await orch.get_system_health()
        perf = health["agent_performance"]
        for name in ("trading_agent", "conversation_agent", "content_writer"):
            assert name in perf
            agent_data = perf[name]
            if "error" not in agent_data:
                assert "total_actions" in agent_data or "agent_name" in agent_data

    @pytest.mark.asyncio
    async def test_system_health_recent_outcomes_list(self, db):
        orch = MasterOrchestrator(db=db, user_id="system")
        health = await orch.get_system_health()
        assert isinstance(health["recent_outcomes"], list)
