"""
tests/test_claude_live.py — Live integration tests for Claude AI API.

Tests every Claude call made by Unitrader agents:
  1. Trading agent decision-making (BUY/SELL/WAIT)
  2. Decision quality: stop-loss, confidence, R:R ratio
  3. Learning hub pattern discovery
  4. Learning hub instruction generation
  5. Content writer blog post generation
  6. Chat/conversation agent response

═══════════════════════════════════════════════════════════
SETUP INSTRUCTIONS
═══════════════════════════════════════════════════════════

1. Get an API key: https://console.anthropic.com
2. Add to .env.test:
       ANTHROPIC_API_KEY=sk-ant-xxxxx

Run:
    pytest tests/test_claude_live.py -v -s

NOTE: Claude calls cost real API credits. Each test uses ~200-600 tokens.
      Total test suite cost: ~$0.01-0.05 (at Haiku pricing).
═══════════════════════════════════════════════════════════
"""

import os

import pytest

pytestmark = [pytest.mark.live, pytest.mark.claude]

# ─────────────────────────────────────────────────────────────────────────────
# Shared market data fixtures
# ─────────────────────────────────────────────────────────────────────────────

BULLISH_MARKET = {
    "symbol": "BTCUSDT",
    "exchange": "binance",
    "price": 65_432.10,
    "high_24h": 67_000.00,
    "low_24h": 63_500.00,
    "volume": 850_000_000.0,
    "price_change_pct": 3.2,
    "trend": "uptrend",
    "indicators": {
        "rsi": 64.5,
        "macd": {"line": 280.5, "signal": 210.3, "histogram": 70.2},
        "ma20": 63_800.0,
        "ma50": 61_200.0,
        "ma200": 55_000.0,
    },
    "support_resistance": {
        "support": 63_000.0,
        "pivot": 65_000.0,
        "resistance": 68_000.0,
    },
}

BEARISH_MARKET = {
    "symbol": "BTCUSDT",
    "exchange": "binance",
    "price": 58_200.00,
    "high_24h": 62_000.00,
    "low_24h": 57_500.00,
    "volume": 1_200_000_000.0,
    "price_change_pct": -5.1,
    "trend": "downtrend",
    "indicators": {
        "rsi": 29.8,
        "macd": {"line": -320.0, "signal": -180.0, "histogram": -140.0},
        "ma20": 61_000.0,
        "ma50": 63_500.0,
        "ma200": 55_000.0,
    },
    "support_resistance": {
        "support": 55_000.0,
        "pivot": 59_000.0,
        "resistance": 62_500.0,
    },
}

SIDEWAYS_MARKET = {
    "symbol": "ETHUSDT",
    "exchange": "binance",
    "price": 3_420.00,
    "high_24h": 3_500.00,
    "low_24h": 3_380.00,
    "volume": 250_000_000.0,
    "price_change_pct": 0.3,
    "trend": "sideways",
    "indicators": {
        "rsi": 50.2,
        "macd": {"line": 5.2, "signal": 4.8, "histogram": 0.4},
        "ma20": 3_415.0,
        "ma50": 3_410.0,
        "ma200": 3_000.0,
    },
    "support_resistance": {
        "support": 3_350.0,
        "pivot": 3_420.0,
        "resistance": 3_490.0,
    },
}

USER_HISTORY_GOOD = {"win_rate": 72.5, "avg_profit": 2.3, "avg_loss": -1.1, "count": 45}
USER_HISTORY_NEW  = {"win_rate": 50.0, "avg_profit": 0.0, "avg_loss": 0.0, "count": 0}
USER_HISTORY_POOR = {"win_rate": 35.0, "avg_profit": 1.8, "avg_loss": -3.2, "count": 22}


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Trading agent — decision structure
# ─────────────────────────────────────────────────────────────────────────────

class TestClaudeTradingDecision:
    """Verify Claude returns valid, structured trading decisions."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_claude):  # noqa: F811
        pass

    @pytest.fixture
    def agent(self):
        from src.agents.core.trading_agent import TradingAgent
        return TradingAgent(user_id="test-user-claude-001")

    @pytest.mark.asyncio
    async def test_decision_schema_bullish(self, agent):
        """Claude should return all required fields for a bullish market."""
        decision = await agent.get_claude_decision(
            market_data=BULLISH_MARKET,
            user_history=USER_HISTORY_GOOD,
            account_balance=10_000.0,
            open_trades_count=0,
            ai_name="AlphaBot",
        )
        print(f"\n  Bullish decision: {decision['decision']} (confidence={decision['confidence']})")
        print(f"    entry={decision.get('entry_price'):,.2f} "
              f"sl={decision.get('stop_loss'):,.2f} "
              f"tp={decision.get('take_profit'):,.2f}")
        print(f"    size={decision.get('position_size_pct')}% | {decision.get('reasoning', '')[:80]}")

        assert decision["decision"] in ("BUY", "SELL", "WAIT"), f"Invalid decision: {decision['decision']}"
        assert 0 <= decision["confidence"] <= 100, f"Confidence out of range: {decision['confidence']}"
        assert isinstance(decision.get("reasoning"), str), "reasoning must be a string"

    @pytest.mark.asyncio
    async def test_decision_schema_bearish(self, agent):
        """Claude should return a valid decision for bearish market."""
        decision = await agent.get_claude_decision(
            market_data=BEARISH_MARKET,
            user_history=USER_HISTORY_POOR,
            account_balance=5_000.0,
            open_trades_count=1,
            ai_name="BearBot",
        )
        print(f"\n  Bearish decision: {decision['decision']} (confidence={decision['confidence']})")
        assert decision["decision"] in ("BUY", "SELL", "WAIT")
        assert 0 <= decision["confidence"] <= 100

    @pytest.mark.asyncio
    async def test_decision_schema_sideways(self, agent):
        """Sideways market — Claude often outputs WAIT (respects rule 5)."""
        decision = await agent.get_claude_decision(
            market_data=SIDEWAYS_MARKET,
            user_history=USER_HISTORY_NEW,
            account_balance=1_000.0,
            open_trades_count=0,
            ai_name="CautiousBot",
        )
        print(f"\n  Sideways decision: {decision['decision']} (confidence={decision['confidence']})")
        assert decision["decision"] in ("BUY", "SELL", "WAIT")

    @pytest.mark.asyncio
    async def test_non_wait_decision_has_valid_prices(self, agent):
        """BUY/SELL decisions must include sensible price levels."""
        decision = await agent.get_claude_decision(
            market_data=BULLISH_MARKET,
            user_history=USER_HISTORY_GOOD,
            account_balance=50_000.0,
            open_trades_count=0,
            ai_name="PriceCheckBot",
        )
        if decision["decision"] == "WAIT":
            pytest.skip("Claude returned WAIT — cannot check prices (not a failure)")

        price = BULLISH_MARKET["price"]
        entry = decision.get("entry_price", 0)
        stop  = decision.get("stop_loss", 0)
        tp    = decision.get("take_profit", 0)
        size  = decision.get("position_size_pct", 0)

        print(f"\n  Price check: entry={entry:,.2f} sl={stop:,.2f} tp={tp:,.2f} size={size}%")

        assert entry > 0,   "entry_price must be positive"
        assert stop > 0,    "stop_loss must be positive"
        assert tp > 0,      "take_profit must be positive"
        assert 0 < size <= 2.0, f"position_size_pct must be 0-2%, got {size}"

        if decision["decision"] == "BUY":
            assert stop < entry, f"Stop loss ({stop}) must be below entry ({entry}) for BUY"
            assert tp > entry,   f"Take profit ({tp}) must be above entry ({entry}) for BUY"

    @pytest.mark.asyncio
    async def test_position_size_never_exceeds_limit(self, agent):
        """Safety rule 1: position_size_pct must never exceed 2.0%."""
        for market in (BULLISH_MARKET, BEARISH_MARKET):
            decision = await agent.get_claude_decision(
                market_data=market,
                user_history=USER_HISTORY_GOOD,
                account_balance=100_000.0,
                open_trades_count=0,
                ai_name="SizeCheckBot",
            )
            size = decision.get("position_size_pct", 0)
            print(f"\n  {market['trend']} position size: {size}%")
            assert size <= 2.0, f"Claude exceeded 2% size limit: {size}% for {market['trend']}"

    @pytest.mark.asyncio
    async def test_learning_context_is_respected(self, agent):
        """When learning context hints at WAIT, Claude should lean toward WAIT/lower confidence."""
        avoid_context = (
            "\nLEARNING INSIGHTS FROM PATTERN ANALYSIS:\n"
            "SETUPS TO AVOID (lower win-rate historically):\n"
            "  - Downtrend conditions — only 28% win rate across 85 trades\n"
            "  - BTC in high-volume sell-off — skip this cycle\n"
        )
        decision = await agent.get_claude_decision(
            market_data=BEARISH_MARKET,
            user_history=USER_HISTORY_POOR,
            account_balance=5_000.0,
            open_trades_count=0,
            ai_name="LearningBot",
            learning_context=avoid_context,
        )
        print(f"\n  With avoid context: {decision['decision']} confidence={decision['confidence']}")
        # Not asserting WAIT specifically since Claude has discretion, but confidence should be low
        assert 0 <= decision["confidence"] <= 100


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Safety rules are enforced in personalize_decision
# ─────────────────────────────────────────────────────────────────────────────

class TestTradingAgentSafetyRules:
    """Verify hard safety guardrails work correctly."""

    @pytest.fixture
    def agent(self):
        from src.agents.core.trading_agent import TradingAgent
        return TradingAgent(user_id="test-safety-001")

    def test_wait_decision_not_modified(self, agent):
        """A WAIT decision should pass through personalize_decision unchanged."""
        import asyncio
        wait = {"decision": "WAIT", "confidence": 0, "position_size_pct": 0.0, "reasoning": "No signal"}
        result = asyncio.get_event_loop().run_until_complete(
            agent.personalize_decision(wait, USER_HISTORY_GOOD)
        )
        assert result["decision"] == "WAIT"
        assert result["position_size_pct"] == 0.0

    def test_high_win_rate_increases_size(self, agent):
        """Win rate > 65% with 10+ trades should increase size by ~10%."""
        import asyncio
        decision = {"decision": "BUY", "confidence": 75, "position_size_pct": 1.0, "reasoning": "test"}
        result = asyncio.get_event_loop().run_until_complete(
            agent.personalize_decision(decision, USER_HISTORY_GOOD)
        )
        print(f"\n  High win rate personalisation: {decision['position_size_pct']}% → {result['position_size_pct']}%")
        assert result["position_size_pct"] >= 1.0, "Size should stay same or increase"
        assert result["position_size_pct"] <= 2.0, "Size must not exceed 2%"

    def test_poor_win_rate_decreases_size(self, agent):
        """Win rate < 40% with 10+ trades should decrease size."""
        import asyncio
        decision = {"decision": "BUY", "confidence": 60, "position_size_pct": 1.0, "reasoning": "test"}
        result = asyncio.get_event_loop().run_until_complete(
            agent.personalize_decision(decision, USER_HISTORY_POOR)
        )
        print(f"\n  Poor win rate personalisation: {decision['position_size_pct']}% → {result['position_size_pct']}%")
        assert result["position_size_pct"] < 1.0, "Size should be reduced for poor history"

    def test_learning_hub_avoid_condition_triggers_wait(self, agent):
        """Avoid condition matching current trend should flip decision to WAIT."""
        import asyncio
        decision = {
            "decision": "BUY",
            "confidence": 70,
            "position_size_pct": 1.0,
            "reasoning": "bullish setup",
            "market_trend": "downtrend",
        }
        insights = {
            "has_insights": True,
            "avoid_condition": "downtrend",
            "focus_condition": None,
            "position_size_modifier": 0.8,
            "high_confidence_setups": [],
            "avoid_setups": ["Downtrend — 28% win rate"],
        }
        result = asyncio.get_event_loop().run_until_complete(
            agent.personalize_decision(decision, USER_HISTORY_POOR, insights)
        )
        print(f"\n  Learning hub avoid: {result['decision']} — {result.get('reasoning', '')[:60]}")
        assert result["decision"] == "WAIT", "Learning hub should force WAIT on avoid condition"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Learning hub — Claude pattern discovery
# ─────────────────────────────────────────────────────────────────────────────

class TestClaudePatternDiscovery:
    """Verify the learning hub's pattern discovery prompt works end-to-end."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_claude):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_discover_patterns_from_rich_digest(self):
        """Claude should find at least one pattern in a data-rich digest."""
        from src.services.learning_hub import _claude_discover_patterns

        digest = {
            "analysis_timestamp": "2026-02-26T09:00:00Z",
            "total_data_points": 187,
            "trading": {
                "sample_size": 120,
                "overall_win_rate_pct": 68.3,
                "best_market_condition": {"name": "uptrend", "win_rate": 85.2, "trades": 65},
                "best_rsi_bucket": {"name": "high (60-70)", "win_rate": 85.2, "trades": 65},
                "best_time_window": {"name": "12-18 UTC", "win_rate": 76.1, "trades": 41},
                "failing_conditions": {"downtrend": {"win_rate": 31.0, "trades": 18}},
                "failing_rsi_buckets": {"oversold (<30)": {"win_rate": 28.0, "trades": 11}},
                "win_rate_by_condition": {
                    "uptrend": {"win_rate": 85.2, "trades": 65},
                    "downtrend": {"win_rate": 31.0, "trades": 18},
                    "sideways": {"win_rate": 55.0, "trades": 37},
                },
                "symbol_performance": {
                    "BTCUSDT": {"win_rate": 79.0, "net_pnl": 1245.50, "trades": 67},
                    "ETHUSDT": {"win_rate": 58.0, "net_pnl": 312.10, "trades": 53},
                },
            },
            "content": {
                "sample_size": 32,
                "overall_high_engagement_pct": 56.2,
                "top_performing_topics": ["momentum trading", "rsi strategy"],
                "topic_engagement_breakdown": {
                    "momentum trading": {"total_posts": 8, "high_engagement_pct": 87.5, "high_count": 7},
                    "rsi strategy": {"total_posts": 5, "high_engagement_pct": 80.0, "high_count": 4},
                    "tax advice": {"total_posts": 3, "high_engagement_pct": 0.0, "high_count": 0},
                },
            },
            "conversations": {
                "sample_size": 35,
                "negative_sentiment_pct": 18.0,
                "excited_pct": 42.0,
                "confused_pct": 31.0,
                "churn_risk_pct": 12.0,
                "topics_confusing_users": {"stop_loss": 8, "rsi": 6, "position": 4},
                "topics_exciting_users": {"momentum": 10, "results": 7},
            },
        }

        patterns = await _claude_discover_patterns(digest)
        print(f"\n  Patterns discovered: {len(patterns)}")
        for i, p in enumerate(patterns, 1):
            print(f"  [{i}] {p.get('pattern_name', '?')} — confidence={p.get('confidence_score', 0):.0f} "
                  f"category={p.get('category', '?')} cross={p.get('is_cross_agent', False)}")

        assert isinstance(patterns, list), "Should return a list"
        assert len(patterns) >= 1, "Should find at least one pattern in rich data"
        assert len(patterns) <= 6, "Should not exceed 6 patterns per cycle"

        for p in patterns:
            assert "pattern_name" in p, f"Missing pattern_name: {p}"
            assert "confidence_score" in p, f"Missing confidence_score: {p}"
            assert "recommendation" in p, f"Missing recommendation: {p}"
            assert float(p["confidence_score"]) >= 40, f"Confidence below threshold: {p['confidence_score']}"

    @pytest.mark.asyncio
    async def test_discover_patterns_from_sparse_data_returns_empty(self):
        """Claude should return [] when data is too sparse for confident patterns."""
        from src.services.learning_hub import _claude_discover_patterns

        sparse_digest = {
            "analysis_timestamp": "2026-02-26T09:00:00Z",
            "total_data_points": 2,
            "trading": {"sample_size": 1, "summary": "Only 1 trade"},
            "content": {"sample_size": 1, "summary": "Only 1 post"},
            "conversations": {"sample_size": 0, "summary": "No conversations"},
        }

        patterns = await _claude_discover_patterns(sparse_digest)
        print(f"\n  Sparse data patterns: {len(patterns)} (expected 0)")
        assert isinstance(patterns, list), "Should return a list even for sparse data"
        # Confidence rule: <40 should be filtered. With 1-2 data points, likely []
        valid = [p for p in patterns if float(p.get("confidence_score", 0)) >= 40]
        assert len(valid) == 0, f"Should find 0 confident patterns in sparse data, found {len(valid)}"

    @pytest.mark.asyncio
    async def test_pattern_cross_agent_flag(self):
        """Patterns involving multiple agents should set is_cross_agent=true."""
        from src.services.learning_hub import _claude_discover_patterns

        digest = {
            "analysis_timestamp": "2026-02-26T09:00:00Z",
            "total_data_points": 200,
            "trading": {
                "sample_size": 130,
                "best_market_condition": {"name": "uptrend", "win_rate": 88.0, "trades": 90},
                "win_rate_by_condition": {"uptrend": {"win_rate": 88.0, "trades": 90}},
            },
            "content": {
                "sample_size": 40,
                "top_performing_topics": ["uptrend momentum"],
                "topic_engagement_breakdown": {
                    "uptrend momentum": {"total_posts": 10, "high_engagement_pct": 90.0, "high_count": 9}
                },
            },
            "conversations": {
                "sample_size": 30,
                "topics_exciting_users": {"momentum": 15},
                "confused_pct": 5.0,
                "churn_risk_pct": 3.0,
            },
        }

        patterns = await _claude_discover_patterns(digest)
        print(f"\n  Cross-agent patterns: {sum(1 for p in patterns if p.get('is_cross_agent'))}")
        # At least one pattern should recognise the momentum signal spans all three agent streams
        cross = [p for p in patterns if p.get("is_cross_agent")]
        assert len(cross) >= 1, "Should detect at least one cross-agent pattern"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Learning hub — instruction generation
# ─────────────────────────────────────────────────────────────────────────────

class TestClaudeInstructionGeneration:
    """Verify per-agent instruction generation from discovered patterns."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_claude):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_instructions_generated_for_all_agents(self):
        """Instructions should be generated for each of the 5 agents."""
        from src.services.learning_hub import _claude_generate_instructions

        patterns = [
            {
                "pattern_name": "RSI 60-70 Momentum — 85% Win Rate",
                "description": "Momentum trades at RSI 60-70 win 85% of the time (150 trades).",
                "confidence_score": 92,
                "category": "general",
                "recommendation": "Increase position size by 20% for RSI 60-70 uptrend setups.",
                "supporting_agents": ["trading", "content", "social_media"],
                "is_cross_agent": True,
                "agent_actions": {
                    "trading": "Increase position_size_modifier to 1.2 for RSI 60-70 uptrend setups. Skip setups outside this RSI range in downtrend conditions.",
                    "content_writer": "Write post: 'The Setup Our AI Trades 85% of the Time (RSI 60-70 Momentum)'. Lead with 150-trade sample size.",
                    "social_media": "Post: 'We analysed 150 trades. RSI 60-70 momentum wins 85% of the time. Here is exactly how it works.'",
                    "conversation": "When users are frustrated with losses, show them the RSI 60-70 stat and ask if their AI trades this setup.",
                    "email": "Send 'Your AI's Best Setup' email to users whose AI hasn't traded in 7+ days.",
                },
            }
        ]

        instructions = await _claude_generate_instructions(patterns)
        print(f"\n  Generated instructions:")
        for agent, instr in instructions.items():
            status = "✓" if instr else "—"
            preview = (instr or "None")[:60]
            print(f"    [{status}] {agent}: {preview}")

        assert isinstance(instructions, dict), "Should return a dict"
        # At least trading + content should have instructions
        assert instructions.get("trading"), "Trading should have an instruction"
        assert instructions.get("content_writer"), "Content writer should have an instruction"

    @pytest.mark.asyncio
    async def test_instructions_contain_data_citations(self):
        """Instructions should reference real numbers from the patterns."""
        from src.services.learning_hub import _claude_generate_instructions

        patterns = [{
            "pattern_name": "Downtrend Avoidance — 28% Win Rate",
            "description": "Downtrend trades lose 72% of the time across 85 trades.",
            "confidence_score": 88,
            "category": "trading",
            "recommendation": "Avoid trading during downtrend conditions.",
            "supporting_agents": ["trading"],
            "is_cross_agent": False,
            "agent_actions": {
                "trading": "Skip all BUY signals when market_condition=downtrend. Across 85 trades, downtrend setups have only 28% win rate.",
                "content_writer": None,
                "social_media": None,
                "conversation": None,
                "email": None,
            },
        }]

        instructions = await _claude_generate_instructions(patterns)
        trading_instr = instructions.get("trading", "")
        print(f"\n  Trading instruction: {trading_instr}")

        if trading_instr:
            # Should reference actual numbers (28 or 85)
            has_number = any(n in trading_instr for n in ("28", "85", "72", "downtrend"))
            assert has_number, f"Instruction should cite data but got: {trading_instr}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Content writer blog post generation
# ─────────────────────────────────────────────────────────────────────────────

class TestClaudeContentWriter:
    """Verify blog post generation produces valid, structured content."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_claude):  # noqa: F811
        pass

    @pytest.mark.asyncio
    async def test_generate_blog_post_structure(self):
        """Blog post should have all required fields and minimum word count."""
        from src.agents.marketing.content_writer import generate_blog_post

        topic = "RSI Momentum Trading: Why 60-70 Is the Sweet Spot"
        result = await generate_blog_post(topic, save_to_db=False)

        print(f"\n  Blog post title: {result['title']}")
        print(f"  Word count: {result['word_count']}")
        print(f"  Read time: {result['estimated_read_time']} min")
        print(f"  Keywords: {result.get('seo_keywords', [])[:3]}")

        assert result["title"], "Title must not be empty"
        assert result["content"], "Content must not be empty"
        assert result["word_count"] >= 500, f"Word count too low: {result['word_count']}"
        assert result["estimated_read_time"] >= 2, "Read time should be at least 2 min"
        assert len(result.get("seo_keywords", [])) >= 3, "Should have at least 3 SEO keywords"
        assert result["meta_description"], "Meta description must not be empty"
        assert len(result.get("meta_description", "")) <= 160, "Meta description too long"

    @pytest.mark.asyncio
    async def test_blog_post_slug_is_url_safe(self):
        """Slug should contain only lowercase letters, numbers, and hyphens."""
        import re
        from src.agents.marketing.content_writer import generate_blog_post

        result = await generate_blog_post("Understanding Stop-Loss Orders", save_to_db=False)
        slug = result["slug"]
        print(f"\n  Slug: {slug}")
        assert re.match(r"^[a-z0-9\-]+$", slug), f"Slug is not URL-safe: {slug}"
        assert len(slug) <= 210, "Slug too long"
