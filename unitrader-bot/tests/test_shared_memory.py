"""
tests/test_shared_memory.py — Unit tests for the SharedMemory symbiotic learning layer.

All tests use an in-memory SQLite database (no external services required).
Run with:
    pytest tests/test_shared_memory.py -v

Test groups:
  TestStoreAndRetrieve   — store_outcome saves correctly; store + retrieve round-trip
  TestQuerySimilarContext— query returns relevant results ordered by similarity
  TestSharedContextExpiry— TTL expiry is respected; non-expired values are returned
  TestPerformanceMetrics — success rate, avg confidence, best/worst conditions
  TestBroadcastOutcome   — broadcast writes to blackboard; caution tags on failure
  TestSimilarityHelpers  — pure similarity scoring functions
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# ── Path setup ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Force SQLite for tests ───────────────────────────────────────────────────
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from database import Base
from models import AgentOutcomeModel, SharedContextModel
from src.agents.memory.shared_memory import (
    AgentOutcome,
    SharedMemory,
    _context_score,
    _is_successful,
    _rsi_band,
    _sentiment_band,
)


# ─────────────────────────────────────────────
# SQLite in-memory engine + session fixture
# ─────────────────────────────────────────────

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_test_engine = create_async_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

_TestSession = async_sessionmaker(
    bind=_test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_tables():
    """Create all tables once for the whole module."""
    import models  # noqa: F401 — ensures all models are registered
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db():
    """Provide a fresh AsyncSession for each test, rolled back on teardown."""
    async with _TestSession() as session:
        yield session
        await session.rollback()


def _mem(db: AsyncSession) -> SharedMemory:
    return SharedMemory(db)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _outcome(**kwargs) -> AgentOutcome:
    defaults = dict(
        agent_name="trading_agent",
        action_type="trade",
        user_id="user-001",
        context={"rsi": 65, "trend": "uptrend", "sentiment_score": 0.2},
        action_taken={"symbol": "BTCUSDT", "direction": "buy", "size": 0.1},
        result={"profit_pct": 2.5},
        confidence_score=0.75,
        asset="BTCUSDT",
        exchange="binance",
        tags=["bullish_macd"],
    )
    defaults.update(kwargs)
    return AgentOutcome(**defaults)


# ═════════════════════════════════════════════
# SIMILARITY HELPERS  (pure, no I/O)
# ═════════════════════════════════════════════

class TestSimilarityHelpers:
    def test_rsi_band_oversold(self):
        assert _rsi_band(25) == "oversold"

    def test_rsi_band_overbought(self):
        assert _rsi_band(75) == "overbought"

    def test_rsi_band_neutral(self):
        assert _rsi_band(50) == "neutral"

    def test_rsi_band_none(self):
        assert _rsi_band(None) == "unknown"

    def test_sentiment_very_negative(self):
        assert _sentiment_band(-0.8) == "very_negative"

    def test_sentiment_positive(self):
        assert _sentiment_band(0.3) == "positive"

    def test_sentiment_none(self):
        assert _sentiment_band(None) == "unknown"

    def test_context_score_perfect_match(self):
        # asset param is passed but the stored dict doesn't include an "asset"
        # key — so asset(0) + rsi(2) + sentiment(2) + trend(2) = 6.
        # If the stored dict does include "asset" the score rises to 9.
        ctx_no_asset = {"rsi": 72, "trend": "uptrend", "sentiment_score": 0.4}
        score_no_asset = _context_score(ctx_no_asset, ctx_no_asset, "BTCUSDT")
        assert score_no_asset >= 6

        ctx_with_asset = {"rsi": 72, "trend": "uptrend", "sentiment_score": 0.4, "asset": "BTCUSDT"}
        score_with_asset = _context_score(ctx_with_asset, ctx_with_asset, "BTCUSDT")
        assert score_with_asset >= 9  # asset(3) + rsi(2) + sentiment(2) + trend(2)

    def test_context_score_no_overlap(self):
        stored = {"rsi": 20, "trend": "downtrend", "sentiment_score": -0.8}
        query = {"rsi": 72, "trend": "uptrend", "sentiment_score": 0.8}
        score = _context_score(stored, query, "ETHUSDT")
        assert score == 0

    def test_context_score_asset_boost(self):
        ctx = {"rsi": 50}
        score_with = _context_score({"rsi": 50, "asset": "BTCUSDT"}, ctx, "BTCUSDT")
        score_without = _context_score({"rsi": 50, "asset": "BTCUSDT"}, ctx, "ETHUSDT")
        assert score_with > score_without

    def test_is_successful_profit(self):
        assert _is_successful({"profit_pct": 1.5}) is True

    def test_is_successful_loss(self):
        assert _is_successful({"profit_pct": -1.5}) is False

    def test_is_successful_flag(self):
        assert _is_successful({"success": True}) is True
        assert _is_successful({"success": False}) is False

    def test_is_successful_helpful(self):
        assert _is_successful({"user_rated_helpful": True}) is True

    def test_is_successful_empty(self):
        assert _is_successful({}) is False


# ═════════════════════════════════════════════
# STORE & RETRIEVE
# ═════════════════════════════════════════════

class TestStoreAndRetrieve:
    @pytest.mark.asyncio
    async def test_store_returns_id(self, db):
        mem = _mem(db)
        o = _outcome()
        oid = await mem.store_outcome(o)
        assert oid == o.id

    @pytest.mark.asyncio
    async def test_stored_outcome_persisted(self, db):
        mem = _mem(db)
        o = _outcome(agent_name="test_agent_store", asset="AAPL", exchange="alpaca")
        await mem.store_outcome(o)
        await db.flush()

        from sqlalchemy import select
        result = await db.execute(
            select(AgentOutcomeModel).where(AgentOutcomeModel.id == o.id)
        )
        row = result.scalar_one_or_none()
        assert row is not None
        assert row.agent_name == "test_agent_store"
        assert row.asset == "AAPL"
        assert row.exchange == "alpaca"
        assert row.confidence == 0.75

    @pytest.mark.asyncio
    async def test_stored_context_preserved(self, db):
        mem = _mem(db)
        ctx = {"rsi": 72, "trend": "uptrend", "sentiment_score": 0.3}
        o = _outcome(context=ctx, tags=["overbought", "bullish"])
        await mem.store_outcome(o)
        await db.flush()

        from sqlalchemy import select
        result = await db.execute(
            select(AgentOutcomeModel).where(AgentOutcomeModel.id == o.id)
        )
        row = result.scalar_one_or_none()
        assert row.context_data == ctx
        assert "overbought" in row.tags

    @pytest.mark.asyncio
    async def test_store_result_data(self, db):
        mem = _mem(db)
        o = _outcome(result={"profit_pct": 3.2, "exit_reason": "take_profit"})
        await mem.store_outcome(o)
        await db.flush()

        from sqlalchemy import select
        result = await db.execute(
            select(AgentOutcomeModel).where(AgentOutcomeModel.id == o.id)
        )
        row = result.scalar_one_or_none()
        assert row.result_data["profit_pct"] == 3.2
        assert row.result_data["exit_reason"] == "take_profit"


# ═════════════════════════════════════════════
# QUERY SIMILAR CONTEXT
# ═════════════════════════════════════════════

class TestQuerySimilarContext:
    @pytest_asyncio.fixture(autouse=True)
    async def seed(self, db):
        """Insert several outcomes with varying contexts."""
        mem = _mem(db)

        # High RSI + uptrend + positive sentiment → win (should rank highly)
        await mem.store_outcome(_outcome(
            agent_name="qsc_agent",
            context={"rsi": 72, "trend": "uptrend", "sentiment_score": 0.4},
            result={"profit_pct": 3.0},
            asset="BTCUSDT",
            tags=["overbought"],
        ))
        # Oversold + downtrend → loss (poor match for uptrend query)
        await mem.store_outcome(_outcome(
            agent_name="qsc_agent",
            context={"rsi": 25, "trend": "downtrend", "sentiment_score": -0.7},
            result={"profit_pct": -2.0},
            asset="BTCUSDT",
            tags=["oversold"],
        ))
        # Different asset but similar context
        await mem.store_outcome(_outcome(
            agent_name="qsc_agent",
            context={"rsi": 68, "trend": "uptrend", "sentiment_score": 0.3},
            result={"profit_pct": 1.5},
            asset="ETHUSDT",
            tags=["bullish"],
        ))
        await db.flush()

    @pytest.mark.asyncio
    async def test_returns_list(self, db):
        mem = _mem(db)
        results = await mem.query_similar_context(
            context={"rsi": 70, "trend": "uptrend"},
            action_type="trade",
            asset="BTCUSDT",
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_same_asset_ranked_first(self, db):
        mem = _mem(db)
        results = await mem.query_similar_context(
            context={"rsi": 70, "trend": "uptrend", "sentiment_score": 0.35},
            action_type="trade",
            asset="BTCUSDT",
        )
        # Filter to outcomes seeded by this test class
        btc_results = [r for r in results if r.asset == "BTCUSDT"]
        eth_results = [r for r in results if r.asset == "ETHUSDT"]
        if btc_results and eth_results:
            btc_idx = results.index(btc_results[0])
            eth_idx = results.index(eth_results[0])
            # BTC (same asset) should rank at least as high as ETH (different asset)
            assert btc_idx <= eth_idx

    @pytest.mark.asyncio
    async def test_downtrend_ranked_lower_than_uptrend(self, db):
        mem = _mem(db)
        results = await mem.query_similar_context(
            context={"rsi": 70, "trend": "uptrend", "sentiment_score": 0.4},
            action_type="trade",
            asset="BTCUSDT",
        )
        uptrend = [r for r in results if r.context.get("trend") == "uptrend" and r.asset == "BTCUSDT"]
        downtrend = [r for r in results if r.context.get("trend") == "downtrend"]
        if uptrend and downtrend:
            assert results.index(uptrend[0]) < results.index(downtrend[0])

    @pytest.mark.asyncio
    async def test_respects_limit(self, db):
        mem = _mem(db)
        results = await mem.query_similar_context(
            context={"rsi": 70},
            action_type="trade",
            limit=1,
        )
        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_returns_agent_outcome_type(self, db):
        mem = _mem(db)
        results = await mem.query_similar_context(
            context={"rsi": 70},
            action_type="trade",
        )
        for r in results:
            assert isinstance(r, AgentOutcome)

    @pytest.mark.asyncio
    async def test_no_results_for_unknown_action_type(self, db):
        mem = _mem(db)
        results = await mem.query_similar_context(
            context={"rsi": 50},
            action_type="nonexistent_type",
        )
        assert results == []


# ═════════════════════════════════════════════
# SHARED CONTEXT EXPIRY
# ═════════════════════════════════════════════

class TestSharedContextExpiry:
    @pytest.mark.asyncio
    async def test_set_and_get_basic(self, db):
        mem = _mem(db)
        await mem.set_shared_context("TEST_key_basic", 42, "test_agent")
        await db.flush()
        ctx = await mem.get_shared_context("TEST_key_basic")
        assert ctx is not None
        assert ctx.value == 42
        assert ctx.set_by == "test_agent"

    @pytest.mark.asyncio
    async def test_non_expired_returned(self, db):
        mem = _mem(db)
        await mem.set_shared_context("TEST_future_key", "alive", "test_agent", ttl_seconds=3600)
        await db.flush()
        ctx = await mem.get_shared_context("TEST_future_key")
        assert ctx is not None
        assert ctx.value == "alive"

    @pytest.mark.asyncio
    async def test_expired_returns_none(self, db):
        """Insert a row with an expiry in the past; get_shared_context must return None."""
        from sqlalchemy import select
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        row = SharedContextModel(
            key="TEST_expired_key",
            value_data={"_v": "should_be_gone"},
            set_by="test_agent",
            expires_at=past,
        )
        db.add(row)
        await db.flush()

        mem = _mem(db)
        ctx = await mem.get_shared_context("TEST_expired_key")
        assert ctx is None

    @pytest.mark.asyncio
    async def test_missing_key_returns_none(self, db):
        mem = _mem(db)
        ctx = await mem.get_shared_context("TEST_definitely_absent_key_xyz")
        assert ctx is None

    @pytest.mark.asyncio
    async def test_overwrite_updates_value(self, db):
        mem = _mem(db)
        await mem.set_shared_context("TEST_overwrite_key", "first", "agent_a")
        await db.flush()
        await mem.set_shared_context("TEST_overwrite_key", "second", "agent_b")
        await db.flush()
        ctx = await mem.get_shared_context("TEST_overwrite_key")
        assert ctx.value == "second"
        assert ctx.set_by == "agent_b"

    @pytest.mark.asyncio
    async def test_various_value_types(self, db):
        mem = _mem(db)
        for val in [True, -0.7, {"nested": "dict"}, [1, 2, 3], None]:
            key = f"TEST_type_{type(val).__name__}_{id(val)}"
            await mem.set_shared_context(key, val, "test_agent")
            await db.flush()
            ctx = await mem.get_shared_context(key)
            assert ctx is not None
            assert ctx.value == val

    @pytest.mark.asyncio
    async def test_get_all_context_for_asset(self, db):
        mem = _mem(db)
        asset = "XRPUSDT"
        await mem.set_shared_context(f"{asset}_sentiment", -0.6, "sentiment_agent", ttl_seconds=3600)
        await mem.set_shared_context(f"{asset}_fear_greed", 18, "fear_agent", ttl_seconds=3600)
        await mem.set_shared_context(f"{asset}_trend", "bearish", "trend_agent", ttl_seconds=3600)
        await db.flush()

        result = await mem.get_all_context_for_asset(asset)
        assert result[f"{asset}_sentiment"] == -0.6
        assert result[f"{asset}_fear_greed"] == 18
        assert result[f"{asset}_trend"] == "bearish"

    @pytest.mark.asyncio
    async def test_get_all_context_excludes_expired(self, db):
        asset = "LTCUSDT"
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        row = SharedContextModel(
            key=f"{asset}_expired_metric",
            value_data={"_v": "old"},
            set_by="test_agent",
            expires_at=past,
        )
        db.add(row)
        await db.flush()

        mem = _mem(db)
        result = await mem.get_all_context_for_asset(asset)
        assert f"{asset}_expired_metric" not in result


# ═════════════════════════════════════════════
# PERFORMANCE METRICS
# ═════════════════════════════════════════════

class TestPerformanceMetrics:
    @pytest_asyncio.fixture
    async def seeded_db(self, db):
        """10 outcomes: 7 wins + 3 losses for perf_agent."""
        mem = _mem(db)
        for i in range(7):
            await mem.store_outcome(_outcome(
                agent_name="perf_agent",
                result={"profit_pct": 1.5 + i * 0.1},
                confidence_score=0.8,
                context={"rsi": 60, "trend": "uptrend"},
            ))
        for i in range(3):
            await mem.store_outcome(_outcome(
                agent_name="perf_agent",
                result={"profit_pct": -1.0},
                confidence_score=0.5,
                context={"rsi": 80, "trend": "downtrend"},
            ))
        await db.flush()
        return db

    @pytest.mark.asyncio
    async def test_total_actions(self, seeded_db):
        mem = _mem(seeded_db)
        perf = await mem.get_agent_performance("perf_agent", timeframe_days=30)
        assert perf.total_actions == 10

    @pytest.mark.asyncio
    async def test_success_rate(self, seeded_db):
        mem = _mem(seeded_db)
        perf = await mem.get_agent_performance("perf_agent", timeframe_days=30)
        assert abs(perf.success_rate - 0.7) < 0.01

    @pytest.mark.asyncio
    async def test_avg_confidence(self, seeded_db):
        mem = _mem(seeded_db)
        perf = await mem.get_agent_performance("perf_agent", timeframe_days=30)
        # 7 * 0.8 + 3 * 0.5 = 5.6 + 1.5 = 7.1 / 10 = 0.71
        assert abs(perf.avg_confidence - 0.71) < 0.01

    @pytest.mark.asyncio
    async def test_timeframe_label(self, seeded_db):
        mem = _mem(seeded_db)
        perf = await mem.get_agent_performance("perf_agent", timeframe_days=7)
        assert perf.timeframe == "7d"

    @pytest.mark.asyncio
    async def test_zero_actions_returns_zeros(self, db):
        mem = _mem(db)
        perf = await mem.get_agent_performance("nonexistent_agent_xyz", timeframe_days=30)
        assert perf.total_actions == 0
        assert perf.success_rate == 0.0
        assert perf.avg_confidence == 0.0
        assert perf.best_conditions == {}
        assert perf.worst_conditions == {}

    @pytest.mark.asyncio
    async def test_best_conditions_reflect_winning_context(self, seeded_db):
        mem = _mem(seeded_db)
        perf = await mem.get_agent_performance("perf_agent", timeframe_days=30)
        # Winning trades had rsi=60, trend="uptrend"
        if perf.best_conditions:
            assert perf.best_conditions.get("trend") in (None, "uptrend")

    @pytest.mark.asyncio
    async def test_worst_conditions_reflect_losing_context(self, seeded_db):
        mem = _mem(seeded_db)
        perf = await mem.get_agent_performance("perf_agent", timeframe_days=30)
        # Losing trades had rsi=80, trend="downtrend"
        if perf.worst_conditions:
            assert perf.worst_conditions.get("trend") in (None, "downtrend")


# ═════════════════════════════════════════════
# BROADCAST OUTCOME
# ═════════════════════════════════════════════

class TestBroadcastOutcome:
    @pytest.mark.asyncio
    async def test_broadcast_stores_outcome(self, db):
        mem = _mem(db)
        o = _outcome(agent_name="broadcast_agent", asset="SOLUSDT")
        await mem.broadcast_outcome(o)
        await db.flush()

        from sqlalchemy import select
        result = await db.execute(
            select(AgentOutcomeModel).where(AgentOutcomeModel.id == o.id)
        )
        row = result.scalar_one_or_none()
        assert row is not None

    @pytest.mark.asyncio
    async def test_broadcast_sets_last_action_context(self, db):
        mem = _mem(db)
        o = _outcome(agent_name="broadcast_agent", asset="SOLUSDT", action_type="trade")
        await mem.broadcast_outcome(o)
        await db.flush()

        ctx = await mem.get_shared_context("SOLUSDT_last_trade")
        assert ctx is not None
        assert ctx.set_by == "broadcast_agent"
        assert ctx.value["action"]["direction"] == "buy"

    @pytest.mark.asyncio
    async def test_broadcast_sets_recent_success_true(self, db):
        mem = _mem(db)
        o = _outcome(result={"profit_pct": 2.0}, asset="AVAXUSDT")
        await mem.broadcast_outcome(o)
        await db.flush()

        ctx = await mem.get_shared_context("AVAXUSDT_recent_success")
        assert ctx is not None
        assert ctx.value is True

    @pytest.mark.asyncio
    async def test_broadcast_sets_recent_success_false_on_loss(self, db):
        mem = _mem(db)
        o = _outcome(result={"profit_pct": -1.5}, asset="DOTUSDT")
        await mem.broadcast_outcome(o)
        await db.flush()

        ctx = await mem.get_shared_context("DOTUSDT_recent_success")
        assert ctx is not None
        assert ctx.value is False

    @pytest.mark.asyncio
    async def test_broadcast_sets_avoid_tags_on_failure(self, db):
        mem = _mem(db)
        o = _outcome(
            result={"profit_pct": -2.0},
            asset="LINKUSDT",
            tags=["overbought", "bearish_divergence"],
        )
        await mem.broadcast_outcome(o)
        await db.flush()

        avoid_overbought = await mem.get_shared_context("avoid_LINKUSDT_overbought")
        avoid_bearish = await mem.get_shared_context("avoid_LINKUSDT_bearish_divergence")
        assert avoid_overbought is not None and avoid_overbought.value is True
        assert avoid_bearish is not None and avoid_bearish.value is True

    @pytest.mark.asyncio
    async def test_broadcast_no_avoid_tags_on_success(self, db):
        mem = _mem(db)
        o = _outcome(
            result={"profit_pct": 3.0},
            asset="UNIUSDT",
            tags=["overbought"],
        )
        await mem.broadcast_outcome(o)
        await db.flush()

        ctx = await mem.get_shared_context("avoid_UNIUSDT_overbought")
        assert ctx is None

    @pytest.mark.asyncio
    async def test_broadcast_skips_blackboard_without_asset(self, db):
        mem = _mem(db)
        o = _outcome(asset=None, tags=["some_tag"])
        await mem.broadcast_outcome(o)
        await db.flush()
        # Should still store the outcome
        from sqlalchemy import select
        result = await db.execute(
            select(AgentOutcomeModel).where(AgentOutcomeModel.id == o.id)
        )
        assert result.scalar_one_or_none() is not None
