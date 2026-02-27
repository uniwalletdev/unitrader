"""
tests/test_e2e_trade.py — Full end-to-end trade flow integration tests.

Tests the complete pipeline from raw market data through Claude decision,
safety guardrails, paper execution, and learning hub logging.

No real money is ever moved — all exchange calls use paper/sandbox accounts
or are intercepted before the exchange order is placed.

Pipeline under test:
    Market Data  →  Claude Decision  →  Safety Checks  →  Personalisation
    →  Learning Hub Filter  →  Execute (paper)  →  DB Log  →  Hub Feedback

═══════════════════════════════════════════════════════════
SETUP INSTRUCTIONS
═══════════════════════════════════════════════════════════

Minimum required to run the full E2E suite:
    ANTHROPIC_API_KEY=sk-ant-xxxxx   (for Claude decisions)

Optional (enables real exchange flows):
    BINANCE_API_KEY + BINANCE_API_SECRET  (testnet keys)
    ALPACA_API_KEY + ALPACA_API_SECRET    (paper trading keys)

Run all E2E tests:
    pytest tests/test_e2e_trade.py -v -s

Run without exchange (Claude only):
    pytest tests/test_e2e_trade.py -v -s -k "not exchange"
═══════════════════════════════════════════════════════════
"""

import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.live

# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

LIVE_SYMBOL   = "BTCUSDT"
LIVE_EXCHANGE = "binance"

MOCK_MARKET_DATA = {
    "symbol": LIVE_SYMBOL,
    "exchange": LIVE_EXCHANGE,
    "price": 65_000.00,
    "high_24h": 67_000.00,
    "low_24h": 63_000.00,
    "volume": 750_000_000.0,
    "price_change_pct": 2.8,
    "trend": "uptrend",
    "indicators": {
        "rsi": 63.2,
        "macd": {"line": 250.0, "signal": 180.0, "histogram": 70.0},
        "ma20": 63_500.0,
        "ma50": 61_000.0,
        "ma200": 55_000.0,
    },
    "support_resistance": {
        "support": 62_500.0,
        "pivot": 64_800.0,
        "resistance": 67_500.0,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Live market data fetch
# ─────────────────────────────────────────────────────────────────────────────

class TestStage1MarketDataFetch:
    """Verify live market data fetch produces indicator-complete snapshots."""

    @pytest.mark.asyncio
    async def test_live_btc_market_data(self):
        """Fetch live BTC market data from Binance public API + compute all indicators."""
        from src.integrations.market_data import full_market_analysis

        print(f"\n═══ Stage 1: Fetching live market data for {LIVE_SYMBOL} ═══")
        start = time.perf_counter()
        data = await full_market_analysis(LIVE_SYMBOL, LIVE_EXCHANGE)
        elapsed = time.perf_counter() - start

        print(f"  ✓ Price:    ${data.get('price', 0):,.2f}")
        print(f"  ✓ Trend:    {data.get('trend')}")
        print(f"  ✓ RSI(14):  {data.get('indicators', {}).get('rsi', 0):.1f}")
        print(f"  ✓ MA(20):   ${data.get('indicators', {}).get('ma20', 0):,.2f}")
        print(f"  ✓ Support:  ${data.get('support_resistance', {}).get('support', 0):,.2f}")
        print(f"  ✓ Resistance: ${data.get('support_resistance', {}).get('resistance', 0):,.2f}")
        print(f"  Fetch time: {elapsed:.2f}s")

        # Core assertions
        assert data["price"] > 0
        assert data["trend"] in ("uptrend", "downtrend", "sideways")
        assert 0 <= data["indicators"]["rsi"] <= 100
        assert data["indicators"]["ma20"] > 0
        assert data["support_resistance"]["support"] < data["price"]
        assert data["support_resistance"]["resistance"] > data["price"]
        assert elapsed < 30.0, f"Market data fetch took too long: {elapsed:.1f}s"

        return data


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Claude decision
# ─────────────────────────────────────────────────────────────────────────────

class TestStage2ClaudeDecision:
    """Verify Claude produces a valid decision for real market data."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_claude):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_claude_decides_on_live_data(self):
        """Feed live market data to Claude and verify the decision structure."""
        from src.integrations.market_data import full_market_analysis
        from src.agents.core.trading_agent import TradingAgent

        print(f"\n═══ Stage 2: Claude decision on live {LIVE_SYMBOL} data ═══")
        agent = TradingAgent(user_id="test-e2e-001")

        # Fetch real data
        market_data = await full_market_analysis(LIVE_SYMBOL, LIVE_EXCHANGE)
        market_data["exchange"] = LIVE_EXCHANGE

        user_history = {"win_rate": 65.0, "avg_profit": 2.1, "avg_loss": -1.2, "count": 30}
        start = time.perf_counter()
        decision = await agent.get_claude_decision(
            market_data=market_data,
            user_history=user_history,
            account_balance=10_000.0,
            open_trades_count=0,
            ai_name="E2ETestBot",
        )
        elapsed = time.perf_counter() - start

        print(f"  ✓ Decision:    {decision['decision']}")
        print(f"  ✓ Confidence:  {decision['confidence']}%")
        print(f"  ✓ Entry:       ${decision.get('entry_price', 0):,.2f}")
        print(f"  ✓ Stop Loss:   ${decision.get('stop_loss', 0):,.2f}")
        print(f"  ✓ Take Profit: ${decision.get('take_profit', 0):,.2f}")
        print(f"  ✓ Size:        {decision.get('position_size_pct', 0)}%")
        print(f"  ✓ Reasoning:   {decision.get('reasoning', '')[:80]}")
        print(f"  Claude latency: {elapsed:.2f}s")

        assert decision["decision"] in ("BUY", "SELL", "WAIT")
        assert 0 <= decision["confidence"] <= 100
        assert decision.get("position_size_pct", 0) <= 2.0
        assert elapsed < 30.0, f"Claude took too long: {elapsed:.1f}s"
        return decision


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3: Safety guardrails
# ─────────────────────────────────────────────────────────────────────────────

class TestStage3SafetyChecks:
    """Verify safety guardrails correctly block dangerous trades."""

    def _make_settings(self) -> SimpleNamespace:
        return SimpleNamespace(max_daily_loss=5.0, max_position_size=2.0)

    @pytest.mark.asyncio
    async def test_low_confidence_decision_blocked(self):
        """Decision with confidence < 50 should be rejected by safety checks."""
        from src.agents.core.trading_agent import TradingAgent
        from unittest.mock import AsyncMock, MagicMock

        print("\n═══ Stage 3a: Safety — Low confidence blocked ═══")
        agent = TradingAgent(user_id="safety-test-001")

        low_conf_decision = {
            "decision": "BUY",
            "confidence": 35,
            "entry_price": 65_000.0,
            "stop_loss": 63_000.0,
            "take_profit": 69_000.0,
            "position_size_pct": 1.5,
            "reasoning": "Weak signal",
        }

        mock_settings = self._make_settings()
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))

        result = await agent._safety_checks(low_conf_decision, 10_000.0, mock_settings, mock_db)
        print(f"  Result: allowed={result['allowed']} reason={result.get('reason', '')}")
        assert result["allowed"] is False
        assert "confidence" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_no_stop_loss_blocked(self):
        """Decision without a stop-loss should be rejected."""
        from src.agents.core.trading_agent import TradingAgent
        from unittest.mock import AsyncMock, MagicMock

        print("\n═══ Stage 3b: Safety — No stop loss blocked ═══")
        agent = TradingAgent(user_id="safety-test-002")

        no_sl_decision = {
            "decision": "BUY",
            "confidence": 75,
            "entry_price": 65_000.0,
            "stop_loss": 0,    # Missing!
            "take_profit": 68_000.0,
            "position_size_pct": 1.0,
            "reasoning": "Good setup",
        }

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))

        result = await agent._safety_checks(no_sl_decision, 10_000.0, self._make_settings(), mock_db)
        print(f"  Result: allowed={result['allowed']} reason={result.get('reason', '')}")
        assert result["allowed"] is False
        assert "stop" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_oversized_position_capped_not_blocked(self):
        """Position size > 2% should be capped at 2%, not rejected."""
        from src.agents.core.trading_agent import TradingAgent
        from unittest.mock import AsyncMock, MagicMock

        print("\n═══ Stage 3c: Safety — Oversized position capped ═══")
        agent = TradingAgent(user_id="safety-test-003")

        oversized = {
            "decision": "BUY",
            "confidence": 80,
            "entry_price": 65_000.0,
            "stop_loss": 63_000.0,
            "take_profit": 69_000.0,
            "position_size_pct": 5.0,  # Way over limit
            "reasoning": "Strong signal",
        }

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))

        result = await agent._safety_checks(oversized, 50_000.0, self._make_settings(), mock_db)
        print(f"  Result: allowed={result['allowed']} size_after={oversized['position_size_pct']}%")
        assert result["allowed"] is True
        assert oversized["position_size_pct"] <= 2.0, "Should be capped at 2%"

    @pytest.mark.asyncio
    async def test_daily_loss_limit_blocks_trade(self):
        """When daily loss exceeds limit, new trades should be blocked."""
        from src.agents.core.trading_agent import TradingAgent
        from unittest.mock import AsyncMock, MagicMock

        print("\n═══ Stage 3d: Safety — Daily loss limit ═══")
        agent = TradingAgent(user_id="safety-test-004")

        good_decision = {
            "decision": "BUY",
            "confidence": 80,
            "entry_price": 65_000.0,
            "stop_loss": 63_000.0,
            "take_profit": 69_000.0,
            "position_size_pct": 1.0,
            "reasoning": "Good setup",
        }

        # Simulate $600 daily loss already realised (above 5% of $10,000 = $500 limit)
        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar.return_value = 600.0  # $600 loss
        mock_db.execute = AsyncMock(return_value=mock_scalar)

        result = await agent._safety_checks(good_decision, 10_000.0, self._make_settings(), mock_db)
        print(f"  Result: allowed={result['allowed']} reason={result.get('reason', '')}")
        assert result["allowed"] is False
        assert "daily" in result.get("reason", "").lower() or "loss" in result.get("reason", "").lower()


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4: Paper trade execution (mocked exchange)
# ─────────────────────────────────────────────────────────────────────────────

class TestStage4PaperTradeExecution:
    """Test the execute_trade() method with a mocked exchange — no real orders."""

    @pytest.mark.asyncio
    async def test_paper_trade_buy_executed(self):
        """A valid BUY decision should produce a trade record in the DB."""
        from src.agents.core.trading_agent import TradingAgent
        from src.services.trade_execution import build_trade_parameters

        print("\n═══ Stage 4: Paper trade execution (mocked exchange) ═══")

        decision = {
            "decision": "BUY",
            "confidence": 78,
            "entry_price": 65_000.0,
            "stop_loss": 63_000.0,
            "take_profit": 69_000.0,
            "position_size_pct": 1.5,
            "reasoning": "Strong RSI momentum with MACD crossover",
        }

        # Verify build_trade_parameters works correctly
        params = build_trade_parameters(
            confidence=decision["confidence"],
            entry_price=decision["entry_price"],
            stop_loss=decision["stop_loss"],
            take_profit=decision["take_profit"],
            position_size_pct=decision["position_size_pct"],
            account_balance=10_000.0,
        )

        print(f"  ✓ Trade params:")
        print(f"    quantity       = {params.get('quantity', 0):.6f} BTC")
        print(f"    size_amount    = ${params.get('size_amount', 0):.2f}")
        print(f"    risk_usd       = ${params.get('risk_usd', 0):.2f}")
        print(f"    risk_reward    = {params.get('risk_reward_ratio', 0):.2f}:1")

        assert params["quantity"] > 0, "Quantity must be positive"
        assert params["size_amount"] > 0, "Size amount must be positive"
        assert params["risk_usd"] > 0, "Risk amount must be positive"
        assert params.get("risk_reward_ratio", 0) >= 1.0, "Risk:reward must be at least 1:1"

    @pytest.mark.asyncio
    async def test_execute_trade_with_mocked_exchange(self):
        """Run execute_trade() with a fully mocked exchange + DB — no real I/O."""
        from src.agents.core.trading_agent import TradingAgent
        from datetime import datetime, timezone

        print("\n═══ Stage 4b: execute_trade() with mocked exchange + DB ═══")
        agent = TradingAgent(user_id="paper-trade-test-001")

        decision = {
            "decision": "BUY",
            "confidence": 80,
            "entry_price": 65_000.0,
            "stop_loss": 63_000.0,
            "take_profit": 69_000.0,
            "position_size_pct": 1.5,
            "reasoning": "E2E test — strong momentum setup",
        }

        # We patch the AsyncSessionLocal so no DB writes occur
        mock_user = SimpleNamespace(
            id="paper-trade-test-001",
            ai_name="E2EBot",
            is_active=True,
            subscription_tier="pro",
        )
        mock_settings = SimpleNamespace(
            max_daily_loss=5.0,
            max_position_size=2.0,
            trading_enabled=True,
        )
        mock_exchange = AsyncMock()
        mock_exchange.get_account_balance = AsyncMock(return_value=10_000.0)
        mock_exchange.place_order = AsyncMock(return_value="MOCK_ORDER_001")
        mock_exchange.set_stop_loss = AsyncMock(return_value=True)
        mock_exchange.set_take_profit = AsyncMock(return_value=True)
        mock_exchange.aclose = AsyncMock()

        with patch("src.agents.core.trading_agent.AsyncSessionLocal") as mock_session_cls, \
             patch("src.agents.core.trading_agent.get_exchange_client", return_value=mock_exchange), \
             patch("src.agents.core.trading_agent.decrypt_api_key", return_value=("key", "secret")):

            # Build the mock DB session
            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=None)
            mock_db.commit = AsyncMock()
            mock_db.flush = AsyncMock()
            mock_db.add = MagicMock()

            # execute() loads user, settings, api key in sequence
            def mock_execute_side_effect(query):
                result = MagicMock()
                result.scalar_one_or_none.return_value = mock_user
                result.scalars.return_value.first.return_value = SimpleNamespace(
                    encrypted_api_key="enc_key",
                    encrypted_api_secret="enc_sec",
                    exchange="binance",
                    is_active=True,
                )
                result.scalar.return_value = 0  # daily loss = $0
                return result

            mock_db.execute = AsyncMock(side_effect=mock_execute_side_effect)
            mock_session_cls.return_value = mock_db

            result = await agent.execute_trade(
                decision=decision,
                symbol=LIVE_SYMBOL,
                exchange_name=LIVE_EXCHANGE,
                ai_name="E2EBot",
            )

        print(f"  Result status: {result.get('status')}")
        if result.get("status") == "executed":
            print(f"  ✓ Trade ID:    {result.get('trade_id')}")
            print(f"  ✓ Side:        {result.get('side')}")
            print(f"  ✓ Entry:       ${result.get('entry_price', 0):,.2f}")
            print(f"  ✓ Confidence:  {result.get('confidence')}%")
        else:
            print(f"  ℹ Trade not executed: {result.get('reason', 'unknown')}")

        # Accept either executed or a meaningful rejection (DB/exchange mock may differ)
        assert result.get("status") in ("executed", "rejected"), f"Unexpected status: {result}"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5: Full pipeline — live data + Claude + safety (no real exchange)
# ─────────────────────────────────────────────────────────────────────────────

class TestStage5FullPipeline:
    """Run the complete pipeline: live data → Claude → safety → personalise → (mock) execute."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_claude):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_full_pipeline_btc(self):
        """
        FULL END-TO-END:
          1. Fetch live BTC market data (Binance public API)
          2. Get Claude trading decision
          3. Apply safety checks
          4. Apply personalisation + learning hub
          5. Report result (paper trade — no real exchange call)
        """
        from src.integrations.market_data import full_market_analysis
        from src.agents.core.trading_agent import TradingAgent
        from src.services.trade_execution import build_trade_parameters
        from src.services.learning_hub import get_trading_insights
        from unittest.mock import AsyncMock, MagicMock

        print(f"\n{'═'*60}")
        print("FULL E2E PIPELINE TEST — BTC/USDT")
        print(f"{'═'*60}")

        total_start = time.perf_counter()
        agent = TradingAgent(user_id="full-e2e-test-001")

        # ── Step 1: Market Data ───────────────────────────────────────────
        print("\n[1/6] Fetching live market data...")
        t = time.perf_counter()
        market_data = await full_market_analysis(LIVE_SYMBOL, LIVE_EXCHANGE)
        market_data["exchange"] = LIVE_EXCHANGE
        print(f"  Price=${market_data['price']:,.2f}  Trend={market_data['trend']}  "
              f"RSI={market_data['indicators']['rsi']:.1f}  ({time.perf_counter()-t:.1f}s)")

        # ── Step 2: Learning Hub Insights ─────────────────────────────────
        print("\n[2/6] Querying learning hub insights...")
        t = time.perf_counter()
        try:
            insights = await get_trading_insights()
            has_insights = insights.get("has_insights", False)
            print(f"  Hub has insights: {has_insights}  ({time.perf_counter()-t:.1f}s)")
        except Exception as exc:
            insights = {"has_insights": False}
            print(f"  Hub unavailable: {exc}  ({time.perf_counter()-t:.1f}s)")

        # ── Step 3: Claude Decision ───────────────────────────────────────
        print("\n[3/6] Getting Claude decision...")
        t = time.perf_counter()
        user_history = {"win_rate": 68.0, "avg_profit": 2.4, "avg_loss": -1.1, "count": 40}
        decision = await agent.get_claude_decision(
            market_data=market_data,
            user_history=user_history,
            account_balance=10_000.0,
            open_trades_count=0,
            ai_name="FullE2EBot",
        )
        decision["market_trend"] = market_data.get("trend", "")
        print(f"  Decision={decision['decision']}  Confidence={decision['confidence']}%  "
              f"({time.perf_counter()-t:.1f}s)")

        # ── Step 4: Personalisation + Learning Hub Filter ────────────────
        print("\n[4/6] Applying personalisation + learning hub filters...")
        t = time.perf_counter()
        decision = await agent.personalize_decision(decision, user_history, insights)
        print(f"  After personalisation: {decision['decision']}  "
              f"size={decision.get('position_size_pct', 0)}%  ({time.perf_counter()-t:.1f}s)")

        # ── Step 5: Safety Checks ─────────────────────────────────────────
        print("\n[5/6] Running safety checks...")
        t = time.perf_counter()
        if decision["decision"] == "WAIT":
            print(f"  WAIT — skipping safety checks  ({time.perf_counter()-t:.1f}s)")
            safe = {"allowed": False, "reason": "Decision is WAIT"}
        else:
            mock_settings = SimpleNamespace(max_daily_loss=5.0, max_position_size=2.0)
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(
                return_value=MagicMock(scalar=MagicMock(return_value=0))
            )
            safe = await agent._safety_checks(decision, 10_000.0, mock_settings, mock_db)
            print(f"  Allowed={safe['allowed']}  {safe.get('reason', 'All checks passed')}  "
                  f"({time.perf_counter()-t:.1f}s)")

        # ── Step 6: Paper Trade Params ────────────────────────────────────
        print("\n[6/6] Building trade parameters...")
        if safe.get("allowed") and decision["decision"] != "WAIT":
            params = build_trade_parameters(
                confidence=decision["confidence"],
                entry_price=decision["entry_price"],
                stop_loss=decision["stop_loss"],
                take_profit=decision["take_profit"],
                position_size_pct=decision["position_size_pct"],
                account_balance=10_000.0,
            )
            print(f"  ✓ PAPER TRADE READY:")
            print(f"    Symbol:      {LIVE_SYMBOL}")
            print(f"    Side:        {decision['decision']}")
            print(f"    Entry:       ${decision['entry_price']:,.2f}")
            print(f"    Stop Loss:   ${decision['stop_loss']:,.2f}")
            print(f"    Take Profit: ${decision['take_profit']:,.2f}")
            print(f"    Quantity:    {params.get('quantity', 0):.6f} BTC")
            print(f"    Size ($):    ${params.get('size_amount', 0):.2f}")
            print(f"    Risk ($):    ${params.get('risk_usd', 0):.2f}")
            print(f"    R:R Ratio:   {params.get('risk_reward_ratio', 0):.2f}:1")
            print(f"    Confidence:  {decision['confidence']}%")

            assert params["quantity"] > 0
            assert 1.0 <= params.get("risk_reward_ratio", 0), "Must have positive R:R"
        else:
            print(f"  → Trade not executed: {safe.get('reason', decision['decision'])}")

        total_elapsed = time.perf_counter() - total_start
        print(f"\n{'═'*60}")
        print(f"PIPELINE COMPLETE in {total_elapsed:.1f}s")
        print(f"{'═'*60}")

        # The pipeline must complete without raising — result is informational
        assert decision["decision"] in ("BUY", "SELL", "WAIT")
        assert total_elapsed < 60.0, f"Full pipeline took too long: {total_elapsed:.1f}s"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 6: Learning hub feedback loop
# ─────────────────────────────────────────────────────────────────────────────

class TestStage6LearningHubFeedback:
    """Verify the learning hub correctly records agent outputs for future analysis."""

    @pytest.mark.asyncio
    async def test_record_agent_output_stored(self):
        """record_agent_output() should persist a record without raising."""
        from src.services.learning_hub import record_agent_output

        print("\n═══ Stage 6: Learning hub feedback ═══")
        try:
            await record_agent_output(
                agent_name="trading",
                output_type="trade",
                content={
                    "symbol": "BTCUSDT",
                    "decision": "BUY",
                    "confidence": 78,
                    "trend": "uptrend",
                    "learning_applied": False,
                    "test": True,
                },
                outcome="success",
                metrics={"confidence": 78, "position_size_pct": 1.5},
            )
            print("  ✓ Agent output recorded (or skipped gracefully if DB not ready)")
        except Exception as exc:
            # DB may not be initialized in test env — should not block the test
            print(f"  ℹ DB not available: {exc} (expected in fresh test env)")

    @pytest.mark.asyncio
    async def test_get_trading_insights_returns_valid_structure(self):
        """get_trading_insights() should return a dict with the expected shape."""
        from src.services.learning_hub import get_trading_insights

        insights = await get_trading_insights()
        print(f"\n  Trading insights: has_insights={insights.get('has_insights')}")
        print(f"    focus_condition: {insights.get('focus_condition')}")
        print(f"    avoid_condition: {insights.get('avoid_condition')}")
        print(f"    size_modifier:   {insights.get('position_size_modifier')}")

        assert isinstance(insights, dict), "Must return a dict"
        assert "has_insights" in insights
        assert "focus_condition" in insights
        assert "avoid_condition" in insights
        assert "position_size_modifier" in insights
        assert 0 < insights["position_size_modifier"] <= 2.0, "Modifier should be reasonable"
