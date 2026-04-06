"""Unit tests for Apex [ACTION:...] parsing on chat responses."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routers.chat import (  # noqa: E402
    _normalize_action_symbol,
    process_chat_response,
)
from src.agents.shared_memory import SharedContext  # noqa: E402


def test_normalize_action_symbol_aapl():
    sym, ex = _normalize_action_symbol("AAPL")
    assert sym == "AAPL" and ex == "alpaca"


def test_normalize_action_symbol_btc_usd():
    sym, ex = _normalize_action_symbol("BTC-USD")
    assert sym == "BTC/USD" and ex == "alpaca"


@pytest.mark.asyncio
async def test_process_chat_trade_tag_strips_and_pending():
    ctx = SharedContext.default("user-1")
    db = MagicMock()
    out = await process_chat_response(
        "I'll queue a buy.\n[ACTION:TRADE:BUY:AAPL]",
        ctx,
        "buy apple",
        db,
    )
    assert "[ACTION" not in out["response"]
    assert out["action_taken"] == "trade_pending:buy:AAPL"
    assert out["requires_confirmation"] is True
    assert out["pending_trade"] == {"side": "buy", "symbol": "AAPL"}


@pytest.mark.asyncio
async def test_process_chat_analyse_tag_calls_orchestrator():
    ctx = SharedContext.default("user-1")
    ctx.subscription_active = True
    db = MagicMock()
    fake = {
        "decision": "BUY",
        "simple": "Momentum looks strong.",
        "expert": "RSI elevated.",
        "entry_price": 100.0,
    }
    with patch(
        "routers.chat._orchestrator_route",
        new=AsyncMock(return_value=fake),
    ) as mock_route:
        out = await process_chat_response(
            "Running analysis.\n[ACTION:ANALYSE:BTC-USD]",
            ctx,
            "analyse btc",
            db,
        )
    mock_route.assert_awaited_once()
    assert out["action_taken"] == "analyse:BTC/USD"
    assert "BTC/USD" in mock_route.await_args[0][2]["symbol"]
    assert "[ACTION" not in out["response"]
    assert "Signal" in out["response"] or "BUY" in out["response"]


@pytest.mark.asyncio
async def test_process_chat_no_tag_passthrough():
    ctx = SharedContext.default("user-1")
    out = await process_chat_response("Hello only", ctx, "hi", MagicMock())
    assert out["response"] == "Hello only"
    assert out["action_taken"] is None
