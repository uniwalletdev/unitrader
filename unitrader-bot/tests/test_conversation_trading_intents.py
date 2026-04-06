"""Unit tests for ConversationAgent chat → orchestrator trading intents."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.shared_memory import SharedContext  # noqa: E402


def _ctx(**kwargs) -> SharedContext:
    base = SharedContext.default("user-test-1")
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


@pytest.mark.asyncio
async def test_confirm_trade_routes_execute():
    from src.agents.core.conversation_agent import ConversationAgent

    agent = ConversationAgent("user-test-1")
    shared = _ctx(
        subscription_active=True,
        trading_paused=False,
    )

    with patch(
        "src.agents.core.conversation_agent._orchestrator_route",
        new=AsyncMock(
            return_value={
                "status": "executed",
                "message": "Executed BUY BTCUSDT",
                "trade_id": "t1",
            }
        ),
    ) as mock_route:
        out = await agent._maybe_route_trading_via_orchestrator(
            "CONFIRM BUY BTCUSDT 25",
            shared,
            "trading_question",
        )

    assert out and "Executed" in out
    mock_route.assert_awaited_once()
    call = mock_route.await_args
    assert call[0][1] == "trade_execute"
    assert call[0][2]["symbol"] == "BTCUSDT"
    assert call[0][2]["side"] == "BUY"
    assert call[0][2]["amount"] == 25.0


@pytest.mark.asyncio
async def test_propose_trade_without_amount_returns_hint():
    from src.agents.core.conversation_agent import ConversationAgent

    agent = ConversationAgent("user-test-1")
    shared = _ctx(trading_paused=False)

    out = await agent._maybe_route_trading_via_orchestrator(
        "BUY BTCUSDT",
        shared,
        "general",
    )
    assert out and "notional" in out.lower() and "CONFIRM" in out


@pytest.mark.asyncio
async def test_propose_trade_with_amount_calls_analyze_and_lists_confirm():
    from src.agents.core.conversation_agent import ConversationAgent

    agent = ConversationAgent("user-test-1")
    shared = _ctx(
        subscription_active=True,
        trading_paused=False,
        trader_class="complete_novice",
    )

    analyze_payload = {
        "decision": "WAIT",
        "simple": "Momentum is mixed; consider waiting.",
        "expert": "RSI neutral.",
        "entry_price": 50000.0,
    }

    async def fake_route(uid, action, payload):
        if action == "trade_analyze":
            return analyze_payload
        raise AssertionError(f"unexpected action {action}")

    with patch(
        "src.agents.core.conversation_agent._orchestrator_route",
        new=AsyncMock(side_effect=fake_route),
    ):
        out = await agent._maybe_route_trading_via_orchestrator(
            "SELL ETHUSDT 10",
            shared,
            "trading_question",
        )

    assert out
    assert "SELL" in out and "ETHUSDT" in out
    assert "CONFIRM SELL ETHUSDT 10" in out
    assert "mixed" in out.lower() or "WAIT" in out


@pytest.mark.asyncio
async def test_analyze_intent_routes_trade_analyze():
    from src.agents.core.conversation_agent import ConversationAgent

    agent = ConversationAgent("user-test-1")
    shared = _ctx(
        subscription_active=True,
        trading_paused=False,
        trader_class="experienced",
    )

    with patch(
        "src.agents.core.conversation_agent._orchestrator_route",
        new=AsyncMock(
            return_value={
                "decision": "BUY",
                "expert": "Strong uptrend.",
                "simple": "Looks good.",
                "entry_price": 100.0,
            }
        ),
    ) as mock_route:
        out = await agent._maybe_route_trading_via_orchestrator(
            "analyze AAPL for me",
            shared,
            "market_analysis",
        )

    assert out and "BUY" in out and "Strong uptrend" in out
    mock_route.assert_awaited_once()
    assert mock_route.await_args[0][1] == "trade_analyze"
    assert mock_route.await_args[0][2]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_trading_paused_skips_routing():
    from src.agents.core.conversation_agent import ConversationAgent

    agent = ConversationAgent("user-test-1")
    shared = _ctx(trading_paused=True, subscription_active=True)

    with patch(
        "src.agents.core.conversation_agent._orchestrator_route",
        new=AsyncMock(),
    ) as mock_route:
        out = await agent._maybe_route_trading_via_orchestrator(
            "CONFIRM BUY BTCUSDT 25",
            shared,
            "trading_question",
        )

    assert out is None
    mock_route.assert_not_called()
