"""
tests/test_token_management_agent.py — Unit tests for TokenManagementAgent.

Covers:
  • Cost calculator (Sonnet vs Haiku pricing)
  • Rate limiter (acquire / reset / quotas)
  • log_call persistence and budget update
  • check_budget (P0 never throttled, P1/P2 throttled at threshold)
  • Alert firing (70/85/95 thresholds)
  • Gateway model routing (complexity + fallback at budget pressure)

Run:
    pytest tests/test_token_management_agent.py -v
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from database import AsyncSessionLocal, create_tables
from models import (
    AgentRateLimit,
    TokenAuditLog,
    TokenBudget,
    TokenOptimizerConfig,
)
from src.agents.token_manager.agent import (
    TokenManagementAgent,
    BudgetExceededError,
    _MODEL_COMPLEX,
    _MODEL_FALLBACK,
    _MODEL_SIMPLE,
)
from src.agents.token_manager.pricing import MODEL_PRICING, calculate_cost
from src.agents.token_manager.rate_limiter import TokenRateLimiter


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="function")
async def db_clean():
    """Fresh DB state: create tables + wipe token_* tables between tests."""
    await create_tables()
    async with AsyncSessionLocal() as db:
        await db.execute(delete(TokenAuditLog))
        await db.execute(delete(TokenBudget))
        await db.execute(delete(AgentRateLimit))
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(delete(TokenAuditLog))
        await db.execute(delete(TokenBudget))
        await db.execute(delete(AgentRateLimit))
        await db.commit()


@pytest_asyncio.fixture
async def seed_agents(db_clean):
    """Seed a realistic set of agent rate limits (mirrors migration SQL)."""
    async with AsyncSessionLocal() as db:
        db.add_all([
            AgentRateLimit(agent_name="trading", tokens_per_minute=3000, priority="p0"),
            AgentRateLimit(agent_name="conversation", tokens_per_minute=2000, priority="p1"),
            AgentRateLimit(agent_name="content_writer", tokens_per_minute=1500, priority="p2"),
        ])
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Cost calculator
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateCost:
    def test_sonnet_pricing(self):
        """Claude Sonnet 4: $3/$15 per 1M tokens."""
        cost = calculate_cost(1_000_000, 1_000_000, "claude-sonnet-4-20250514")
        assert cost == pytest.approx(3.00 + 15.00, rel=1e-6)

    def test_haiku_pricing(self):
        """Claude Haiku 3: $0.25/$1.25 per 1M tokens."""
        cost = calculate_cost(1_000_000, 1_000_000, "claude-3-haiku-20240307")
        assert cost == pytest.approx(0.25 + 1.25, rel=1e-6)

    def test_cached_discount(self):
        """Cached input tokens billed at 10% of uncached rate."""
        # 1M input total, 500k cached, 0 output, Sonnet
        cost = calculate_cost(
            tokens_in=1_000_000,
            tokens_out=0,
            model="claude-sonnet-4-20250514",
            cached_tokens=500_000,
        )
        # 500k uncached @ $3/MT = $1.50; 500k cached @ $0.30/MT = $0.15
        assert cost == pytest.approx(1.50 + 0.15, rel=1e-6)

    def test_zero_tokens(self):
        assert calculate_cost(0, 0, "claude-sonnet-4-20250514") == 0.0

    def test_unknown_model_falls_back_to_sonnet_pricing(self):
        """Unknown model should not crash — use conservative Sonnet pricing."""
        cost = calculate_cost(1_000_000, 0, "made-up-model")
        assert cost == pytest.approx(3.00, rel=1e-6)

    def test_sonnet_is_roughly_12x_haiku_for_typical_call(self):
        """Sanity: ~500 input / ~200 output trade call."""
        sonnet = calculate_cost(500, 200, "claude-sonnet-4-20250514")
        haiku = calculate_cost(500, 200, "claude-3-haiku-20240307")
        ratio = sonnet / haiku
        assert 10 < ratio < 14  # ~12x


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiter
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRateLimiter:
    async def test_acquire_within_limit(self, seed_agents):
        limiter = TokenRateLimiter()
        async with AsyncSessionLocal() as db:
            allowed, reason = await limiter.acquire(db, "conversation", 500)
        assert allowed is True
        assert reason == ""

    async def test_acquire_exceeds_limit(self, seed_agents):
        limiter = TokenRateLimiter()
        async with AsyncSessionLocal() as db:
            # conversation = 2000 tokens/min; asking for 2500 in one shot
            allowed, reason = await limiter.acquire(db, "conversation", 2500)
        assert allowed is False
        assert "rate_limit" in reason

    async def test_acquire_accumulates(self, seed_agents):
        limiter = TokenRateLimiter()
        async with AsyncSessionLocal() as db:
            a1, _ = await limiter.acquire(db, "conversation", 1500)
            a2, _ = await limiter.acquire(db, "conversation", 400)
            a3, reason = await limiter.acquire(db, "conversation", 500)  # over 2000
        assert a1 is True
        assert a2 is True
        assert a3 is False

    async def test_unknown_agent_uses_defaults(self, db_clean):
        limiter = TokenRateLimiter()
        async with AsyncSessionLocal() as db:
            allowed, _ = await limiter.acquire(db, "nonexistent_agent", 100)
        assert allowed is True  # default 2000/min


# ─────────────────────────────────────────────────────────────────────────────
# log_call + budget accounting
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLogCall:
    async def test_log_call_persists_row(self, db_clean):
        tm = TokenManagementAgent()
        await tm.log_call(
            agent_name="trading",
            task_type="trade_decision",
            model="claude-sonnet-4-20250514",
            tokens_in=500,
            tokens_out=200,
            user_id=None,
            status="success",
        )
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(TokenAuditLog))
            rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].agent_name == "trading"
        assert rows[0].tokens_in == 500
        assert rows[0].tokens_out == 200
        assert float(rows[0].cost_usd) > 0

    async def test_log_call_updates_budget(self, db_clean):
        tm = TokenManagementAgent()
        await tm.log_call(
            agent_name="trading",
            task_type="trade_decision",
            model="claude-3-haiku-20240307",
            tokens_in=1000,
            tokens_out=500,
        )
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(TokenBudget))
            budget = result.scalar_one_or_none()
        assert budget is not None
        assert budget.budget_used == 1500

    async def test_failed_call_does_not_consume_budget(self, db_clean):
        tm = TokenManagementAgent()
        await tm.log_call(
            agent_name="trading",
            task_type="trade_decision",
            model="claude-3-haiku-20240307",
            tokens_in=0,
            tokens_out=0,
            status="error",
            error_message="API timeout",
        )
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(TokenBudget))
            budget = result.scalar_one_or_none()
        # Budget row is still created by the log_call, but budget_used stays 0.
        assert budget is None or budget.budget_used == 0


# ─────────────────────────────────────────────────────────────────────────────
# check_budget priority semantics
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCheckBudget:
    async def _set_budget_pct(self, pct: float) -> None:
        """Helper — directly manipulate budget_used to hit a given pct."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(TokenBudget))
            budget = result.scalar_one_or_none()
            if budget is None:
                now = datetime.now(timezone.utc)
                budget = TokenBudget(
                    month_start=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                    month_end=now.replace(day=28, hour=0, minute=0, second=0, microsecond=0),
                    budget_total=10_000_000,
                    status="active",
                )
                db.add(budget)
                await db.flush()
            budget.budget_used = int(budget.budget_total * pct)
            await db.commit()

    async def test_p0_never_throttled(self, db_clean):
        await self._set_budget_pct(0.99)
        tm = TokenManagementAgent()
        status = await tm.check_budget("trading")
        assert status["allowed"] is True
        assert "p0_never_throttled" in status["reason"]

    async def test_p1_allowed_under_threshold(self, db_clean):
        await self._set_budget_pct(0.50)
        tm = TokenManagementAgent()
        status = await tm.check_budget("conversation")
        assert status["allowed"] is True

    async def test_p1_fallback_at_85(self, db_clean):
        await self._set_budget_pct(0.86)
        tm = TokenManagementAgent()
        status = await tm.check_budget("conversation")
        assert status["allowed"] is True  # still allowed, but with fallback
        assert status["fallback_model"] == _MODEL_FALLBACK
        assert "p1_fallback" in status["reason"]

    async def test_p1_hard_capped_at_98(self, db_clean):
        await self._set_budget_pct(0.99)
        tm = TokenManagementAgent()
        status = await tm.check_budget("conversation")
        assert status["allowed"] is False

    async def test_p2_paused_at_85(self, db_clean):
        await self._set_budget_pct(0.86)
        tm = TokenManagementAgent()
        status = await tm.check_budget("content_writer")
        assert status["allowed"] is False
        assert "p2_paused" in status["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# Model router
# ─────────────────────────────────────────────────────────────────────────────


class TestModelRouter:
    def test_simple_complexity_picks_haiku(self):
        tm = TokenManagementAgent()
        model, fallback = tm._select_model("simple", "conversation", 0.1, None)
        assert model == _MODEL_SIMPLE
        assert fallback is False

    def test_complex_complexity_picks_sonnet(self):
        tm = TokenManagementAgent()
        model, fallback = tm._select_model("complex", "conversation", 0.1, None)
        assert model == _MODEL_COMPLEX
        assert fallback is False

    def test_budget_pressure_downgrades_non_p0(self):
        """At 85%+ budget, non-P0 agents should drop to the fallback model."""
        tm = TokenManagementAgent()
        model, fallback = tm._select_model("complex", "conversation", 0.90, None)
        assert model == _MODEL_FALLBACK
        assert fallback is True

    def test_budget_pressure_does_not_affect_p0(self):
        """P0 agents keep their Sonnet even under pressure."""
        tm = TokenManagementAgent()
        model, fallback = tm._select_model("complex", "trading", 0.95, None)
        assert model == _MODEL_COMPLEX
        assert fallback is False

    def test_override_model_wins(self):
        tm = TokenManagementAgent()
        model, fallback = tm._select_model("simple", "conversation", 0.1, "claude-3-opus-20240229")
        assert model == "claude-3-opus-20240229"


# ─────────────────────────────────────────────────────────────────────────────
# Alert firing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAlerts:
    async def _seed_budget(self, used_pct: float) -> None:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            budget = TokenBudget(
                month_start=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                month_end=now.replace(day=28, hour=0, minute=0, second=0, microsecond=0),
                budget_total=10_000_000,
                budget_used=int(10_000_000 * used_pct),
                status="active",
            )
            db.add(budget)
            await db.commit()

    async def test_no_alert_under_70(self, db_clean):
        await self._seed_budget(0.5)
        tm = TokenManagementAgent()
        with patch("src.agents.token_manager.agent._fire_alert") as mock_alert:
            await tm.check_and_fire_alerts()
            mock_alert.assert_not_called()

    async def test_alert_fires_at_70(self, db_clean):
        await self._seed_budget(0.72)
        tm = TokenManagementAgent()
        with patch("src.agents.token_manager.agent._fire_alert") as mock_alert:
            await tm.check_and_fire_alerts()
            assert mock_alert.called

    async def test_alert_not_fired_twice(self, db_clean):
        await self._seed_budget(0.72)
        tm = TokenManagementAgent()
        with patch("src.agents.token_manager.agent._fire_alert") as mock_alert:
            await tm.check_and_fire_alerts()
            first_count = mock_alert.call_count
            await tm.check_and_fire_alerts()  # second run — already sent
        assert mock_alert.call_count == first_count

    async def test_all_three_tiers_fire_at_95(self, db_clean):
        await self._seed_budget(0.96)
        tm = TokenManagementAgent()
        with patch("src.agents.token_manager.agent._fire_alert") as mock_alert:
            await tm.check_and_fire_alerts()
        # 70, 85, 95 all crossed simultaneously
        assert mock_alert.call_count == 3


# ─────────────────────────────────────────────────────────────────────────────
# Gateway complete() — with mocked Anthropic client
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestComplete:
    async def test_complete_success_logs_usage(self, db_clean):
        tm = TokenManagementAgent()

        # Mock the Anthropic client response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="BUY signal")]
        mock_response.usage = MagicMock(
            input_tokens=250, output_tokens=120, cache_read_input_tokens=0
        )

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        tm._client = mock_client

        result = await tm.complete(
            agent_name="trading",
            task_type="trade_decision",
            system="You are a trader.",
            messages=[{"role": "user", "content": "AAPL?"}],
            complexity="complex",
            max_tokens=512,
        )

        assert result.text == "BUY signal"
        assert result.tokens_in == 250
        assert result.tokens_out == 120
        assert result.cost_usd > 0
        assert result.fallback_used is False

        # Wait briefly for background log_call task
        await asyncio.sleep(0.15)
        async with AsyncSessionLocal() as db:
            result_rows = await db.execute(select(TokenAuditLog))
            rows = result_rows.scalars().all()
        assert len(rows) >= 1
        assert rows[0].agent_name == "trading"

    async def test_complete_raises_when_p2_budget_exhausted(self, db_clean):
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            db.add(TokenBudget(
                month_start=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                month_end=now.replace(day=28, hour=0, minute=0, second=0, microsecond=0),
                budget_total=10_000_000,
                budget_used=9_000_000,  # 90%
                status="active",
            ))
            await db.commit()

        tm = TokenManagementAgent()
        with pytest.raises(BudgetExceededError):
            await tm.complete(
                agent_name="content_writer",
                task_type="blog",
                system="x",
                messages=[{"role": "user", "content": "y"}],
            )
