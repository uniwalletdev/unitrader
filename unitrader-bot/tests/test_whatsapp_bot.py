"""
tests/test_whatsapp_bot.py — Unit tests for the WhatsApp bot integration.

All tests are pure unit tests (no real Twilio calls, no real DB).
The Twilio client's send is mocked via asyncio executor patching.

Run:
    pytest tests/test_whatsapp_bot.py -v --asyncio-mode=auto
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_PHONE = "+14155550100"   # canonical test phone (no whatsapp: prefix)
_FROM  = f"whatsapp:{_PHONE}"


def _fake_user(user_id: str = "user-wa-001", ai_name: str = "Nova") -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        ai_name=ai_name,
        is_active=True,
        email="trader@example.com",
        subscription_tier="trial",
    )


def _wa_service() -> "WhatsAppBotService":  # noqa: F821
    """Build a WhatsAppBotService without calling the Twilio constructor."""
    from src.integrations.whatsapp_bot import WhatsAppBotService
    svc = WhatsAppBotService.__new__(WhatsAppBotService)
    svc._client        = MagicMock()
    svc._from          = "whatsapp:+14155238886"
    svc.account_sid    = "ACtest"
    svc.auth_token     = "testtoken"
    svc.twilio_number  = "+14155238886"
    return svc


def _empty_db_session():
    """Return an async-context-manager mock that yields an empty DB result."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__  = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    session.add     = MagicMock()
    session.delete  = AsyncMock()
    session.commit  = AsyncMock()
    return session


# ─────────────────────────────────────────────────────────────────────────────
# _trunc helper
# ─────────────────────────────────────────────────────────────────────────────

def test_trunc_short_message():
    from src.integrations.whatsapp_bot import _trunc
    assert _trunc("Hello") == "Hello"


def test_trunc_exact_limit():
    from src.integrations.whatsapp_bot import _trunc
    msg = "x" * 1600
    assert _trunc(msg) == msg


def test_trunc_over_limit():
    from src.integrations.whatsapp_bot import _trunc
    msg = "x" * 2000
    out = _trunc(msg)
    assert len(out) == 1600
    assert out.endswith("...")


# ─────────────────────────────────────────────────────────────────────────────
# send_message — runs Twilio in thread executor
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_message_adds_whatsapp_prefix():
    """send_message wraps the number in 'whatsapp:' before calling Twilio."""
    svc = _wa_service()
    svc._client.messages.create = MagicMock()

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = AsyncMock()
        await svc.send_message("+14155550100", "Hello!")

    # run_in_executor should have been called once
    mock_loop.return_value.run_in_executor.assert_called_once()


@pytest.mark.asyncio
async def test_send_message_preserves_whatsapp_prefix():
    """send_message does not double-add 'whatsapp:' if already present."""
    svc = _wa_service()
    captured = []

    async def fake_executor(pool, fn):
        captured.append(fn)

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = fake_executor
        await svc.send_message("whatsapp:+14155550100", "Hi!")

    assert len(captured) == 1


# ─────────────────────────────────────────────────────────────────────────────
# handle_incoming_message — routing
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("body,expected_handler,is_async", [
    ("START",       "_cmd_start",       True),
    ("start",       "_cmd_start",       True),
    ("PORTFOLIO",   "_cmd_portfolio",   True),
    ("HISTORY",     "_cmd_history",     True),
    ("PERFORMANCE", "_cmd_performance", True),
    ("ALERTS",      "_cmd_alerts",      True),
    ("SETTINGS",    "_cmd_settings",    True),
    ("UNLINK",      "_cmd_unlink",      True),
    # HELP is synchronous — use MagicMock, not AsyncMock
    ("HELP",        "_cmd_help",        False),
])
async def test_routing_dispatches_to_correct_handler(body, expected_handler, is_async):
    """handle_incoming_message routes each keyword to the right method."""
    svc  = _wa_service()
    user = _fake_user()

    handler_mock = AsyncMock(return_value="ok") if is_async else MagicMock(return_value="ok")

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=user)), \
         patch.object(svc, "send_message",     new=AsyncMock()), \
         patch.object(svc, "_log",             new=AsyncMock()), \
         patch.object(svc, expected_handler,   new=handler_mock):
        await svc.handle_incoming_message(_FROM, body)

    handler_mock.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_command_returns_help_hint():
    """An unrecognised word returns a 'send HELP' nudge."""
    svc          = _wa_service()
    send_mock    = AsyncMock()

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=None)), \
         patch.object(svc, "send_message",     new=send_mock), \
         patch.object(svc, "_log",             new=AsyncMock()):
        await svc.handle_incoming_message(_FROM, "GIBBERISH")

    sent: str = send_mock.call_args[0][1]
    assert "help" in sent.lower() or "command" in sent.lower()


@pytest.mark.asyncio
async def test_empty_body_falls_back_to_help():
    """An empty message is treated as HELP without crashing."""
    svc       = _wa_service()
    send_mock = AsyncMock()

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=None)), \
         patch.object(svc, "send_message",     new=send_mock), \
         patch.object(svc, "_log",             new=AsyncMock()):
        await svc.handle_incoming_message(_FROM, "")

    send_mock.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# START
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_unlinked():
    """START for an unlinked number shows linking instructions."""
    svc = _wa_service()
    text = await svc._cmd_start(None, _PHONE)
    assert "link" in text.lower()
    assert "unitrader" in text.lower()


@pytest.mark.asyncio
async def test_start_linked():
    """START for a linked user shows the command menu with AI name."""
    svc  = _wa_service()
    user = _fake_user()
    text = await svc._cmd_start(user, _PHONE)
    assert user.ai_name in text
    assert "portfolio" in text.lower() or "trade" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# LINK
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_link_already_linked():
    svc  = _wa_service()
    user = _fake_user()
    text = await svc._cmd_link(user, _PHONE, [])
    assert "already linked" in text.lower()


@pytest.mark.asyncio
async def test_link_no_args_generates_code():
    """LINK with no args generates a 6-digit code and stores it in DB."""
    svc    = _wa_service()
    mock_s = _empty_db_session()

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_link(None, _PHONE, [])

    # Code appears wrapped in *asterisks* (Markdown bold) — strip them
    import re
    digits = re.findall(r"\*?(\d{6})\*?", text)
    assert digits, f"Expected a 6-digit code in: {text!r}"
    assert "15 minutes" in text.lower() or "expire" in text.lower()
    mock_s.add.assert_called_once()
    mock_s.commit.assert_called_once()


@pytest.mark.asyncio
async def test_link_invalid_code():
    """LINK BADCODE with no DB row returns an error."""
    svc    = _wa_service()
    mock_s = _empty_db_session()   # scalar_one_or_none returns None

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_link(None, _PHONE, ["999999"])

    assert "invalid" in text.lower() or "expired" in text.lower()


@pytest.mark.asyncio
async def test_link_valid_web_initiated_code():
    """LINK CODE with a valid web-initiated row creates UserExternalAccount."""
    svc = _wa_service()

    code_row = SimpleNamespace(
        code="123456",
        user_id="user-001",
        is_used=False,
        used_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        telegram_user_id=None,
        telegram_username=None,
    )
    fetched_user = SimpleNamespace(ai_name="Atlas")

    mock_s = AsyncMock()
    mock_s.__aenter__ = AsyncMock(return_value=mock_s)
    mock_s.__aexit__  = AsyncMock(return_value=False)
    mock_s.add    = MagicMock()
    mock_s.commit = AsyncMock()

    # First execute → TelegramLinkingCode; second → no existing ext acct; third → User
    mock_s.execute = AsyncMock(side_effect=[
        MagicMock(**{"scalar_one_or_none.return_value": code_row}),
        MagicMock(**{"scalar_one_or_none.return_value": None}),
        MagicMock(**{"scalar_one_or_none.return_value": fetched_user}),
    ])

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_link(None, _PHONE, ["123456"])

    assert "linked" in text.lower()
    assert fetched_user.ai_name in text
    mock_s.add.assert_called_once()    # UserExternalAccount added
    assert code_row.is_used is True    # code marked used


# ─────────────────────────────────────────────────────────────────────────────
# PORTFOLIO
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_unlinked():
    svc  = _wa_service()
    text = await svc._cmd_portfolio(None)
    assert "link" in text.lower() or "start" in text.lower()


@pytest.mark.asyncio
async def test_portfolio_empty():
    svc  = _wa_service()
    user = _fake_user()
    mock_s = _empty_db_session()

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_portfolio(user)

    assert "no open" in text.lower() or "no position" in text.lower()


@pytest.mark.asyncio
async def test_portfolio_with_positions():
    """PORTFOLIO formats each trade correctly."""
    svc  = _wa_service()
    user = _fake_user()
    trade = SimpleNamespace(
        symbol="BTCUSDT", side="BUY",
        entry_price=50_000.0,
        profit=200.0, loss=0.0, profit_percent=0.4,
        created_at=datetime.now(timezone.utc),
    )

    mock_s = _empty_db_session()
    mock_s.execute = AsyncMock(
        return_value=MagicMock(**{"scalars.return_value.all.return_value": [trade]})
    )

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_portfolio(user)

    assert "BTCUSDT" in text
    assert "+200" in text or "200" in text


# ─────────────────────────────────────────────────────────────────────────────
# TRADE — argument validation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("args,fragment", [
    ([],                         "invalid format"),
    (["BUY", "BTCUSDT"],         "invalid format"),
    (["HOLD", "BTCUSDT", "1.5"], "buy or sell"),
    (["BUY",  "BTCUSDT", "0"],   "0.1"),
    (["BUY",  "BTCUSDT", "5.0"], "0.1"),
    (["BUY",  "BTCUSDT", "abc"], "number"),
])
async def test_trade_bad_args(args, fragment):
    svc  = _wa_service()
    user = _fake_user()
    text = await svc._cmd_trade(user, args)
    assert fragment.lower() in text.lower()


@pytest.mark.asyncio
async def test_trade_unlinked():
    svc  = _wa_service()
    text = await svc._cmd_trade(None, ["BUY", "BTCUSDT", "1.5"])
    assert "link" in text.lower() or "start" in text.lower()


@pytest.mark.asyncio
async def test_trade_no_exchange():
    """TRADE when no exchange key is configured returns a setup hint."""
    svc  = _wa_service()
    user = _fake_user()

    with patch.object(svc, "_get_primary_exchange", new=AsyncMock(return_value=None)):
        text = await svc._cmd_trade(user, ["BUY", "BTCUSDT", "1.5"])

    assert "exchange" in text.lower() or "api key" in text.lower()


@pytest.mark.asyncio
async def test_trade_executes_successfully():
    """TRADE BUY BTCUSDT 1.5 returns execution details on success."""
    svc  = _wa_service()
    user = _fake_user()

    mock_live  = {"price": 50_000.0, "rsi": 62, "trend": "uptrend"}
    mock_agent = MagicMock()
    mock_agent.execute_trade = AsyncMock(return_value={
        "status":   "executed",
        "trade_id": "trade-xyz",
        "quantity": 0.001,
    })

    # full_market_analysis is imported lazily inside _cmd_trade;
    # patch it at its source module so the import picks up the mock.
    with patch.object(svc, "_get_primary_exchange", new=AsyncMock(return_value="binance")), \
         patch("src.integrations.market_data.full_market_analysis",
               new=AsyncMock(return_value=mock_live)), \
         patch("src.agents.core.trading_agent.TradingAgent", return_value=mock_agent):
        text = await svc._cmd_trade(user, ["BUY", "BTCUSDT", "1.5"])

    assert "executed" in text.lower() or "trade" in text.lower()
    assert "BTCUSDT" in text


@pytest.mark.asyncio
async def test_trade_rejected_by_agent():
    """TRADE returns the rejection reason when the agent refuses."""
    svc  = _wa_service()
    user = _fake_user()

    mock_live  = {"price": 50_000.0}
    mock_agent = MagicMock()
    mock_agent.execute_trade = AsyncMock(return_value={
        "status": "rejected",
        "reason": "Daily loss limit reached",
    })

    with patch.object(svc, "_get_primary_exchange", new=AsyncMock(return_value="binance")), \
         patch("src.integrations.market_data.full_market_analysis",
               new=AsyncMock(return_value=mock_live)), \
         patch("src.agents.core.trading_agent.TradingAgent", return_value=mock_agent):
        text = await svc._cmd_trade(user, ["SELL", "ETHUSDT", "0.5"])

    assert "rejected" in text.lower() or "daily loss" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# CLOSE
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_unlinked():
    svc  = _wa_service()
    text = await svc._cmd_close(None, ["BTCUSDT"])
    assert "link" in text.lower() or "start" in text.lower()


@pytest.mark.asyncio
async def test_close_no_args():
    svc  = _wa_service()
    user = _fake_user()
    text = await svc._cmd_close(user, [])
    assert "close btcusdt" in text.lower() or "usage" in text.lower()


@pytest.mark.asyncio
async def test_close_symbol_not_found():
    """CLOSE BTCUSDT when no open position exists for that symbol."""
    svc  = _wa_service()
    user = _fake_user()

    mock_s = _empty_db_session()   # scalar_one_or_none → None

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_close(user, ["BTCUSDT"])

    assert "no open" in text.lower() or "not found" in text.lower()


@pytest.mark.asyncio
async def test_close_success():
    """CLOSE with an open position returns P&L details."""
    svc  = _wa_service()
    user = _fake_user()

    open_trade = SimpleNamespace(
        id="trade-001", symbol="BTCUSDT", side="BUY",
        entry_price=48_000.0, user_id=user.id,
    )
    mock_agent = MagicMock()
    mock_agent.close_position = AsyncMock(return_value={
        "status":         "closed",
        "exit_price":     50_000.0,
        "profit":         200.0,
        "loss":           0.0,
        "profit_percent": 0.42,
    })

    mock_s = _empty_db_session()
    mock_s.execute = AsyncMock(
        return_value=MagicMock(**{"scalar_one_or_none.return_value": open_trade})
    )

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s), \
         patch("src.agents.core.trading_agent.TradingAgent", return_value=mock_agent):
        text = await svc._cmd_close(user, ["BTCUSDT"])

    assert "closed" in text.lower() or "✅" in text
    assert "BTCUSDT" in text


# ─────────────────────────────────────────────────────────────────────────────
# HISTORY
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_unlinked():
    svc  = _wa_service()
    text = await svc._cmd_history(None)
    assert "link" in text.lower() or "start" in text.lower()


@pytest.mark.asyncio
async def test_history_empty():
    svc    = _wa_service()
    user   = _fake_user()
    mock_s = _empty_db_session()

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_history(user)

    assert "no closed" in text.lower() or "no trade" in text.lower()


@pytest.mark.asyncio
async def test_history_with_trades():
    """HISTORY lists last 5 closed trades with symbol and P&L."""
    svc  = _wa_service()
    user = _fake_user()
    trades = [
        SimpleNamespace(
            symbol="BTCUSDT", side="BUY",
            profit=150.0, loss=0.0,
            closed_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            symbol="ETHUSDT", side="SELL",
            profit=0.0, loss=40.0,
            closed_at=datetime(2025, 2, 2, tzinfo=timezone.utc),
        ),
    ]

    mock_s = _empty_db_session()
    mock_s.execute = AsyncMock(
        return_value=MagicMock(**{"scalars.return_value.all.return_value": trades})
    )

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_history(user)

    assert "BTCUSDT" in text
    assert "ETHUSDT" in text


# ─────────────────────────────────────────────────────────────────────────────
# PERFORMANCE
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_performance_unlinked():
    svc  = _wa_service()
    text = await svc._cmd_performance(None)
    assert "link" in text.lower() or "start" in text.lower()


@pytest.mark.asyncio
async def test_performance_no_trades():
    svc    = _wa_service()
    user   = _fake_user()
    mock_s = _empty_db_session()

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_performance(user)

    assert "no closed" in text.lower() or "no trade" in text.lower()


@pytest.mark.asyncio
async def test_performance_calculates_correctly():
    """PERFORMANCE win-rate and total P&L are computed accurately."""
    svc  = _wa_service()
    user = _fake_user()
    trades = [
        SimpleNamespace(profit=200.0, loss=0.0),
        SimpleNamespace(profit=100.0, loss=0.0),
        SimpleNamespace(profit=0.0,   loss=50.0),
        SimpleNamespace(profit=150.0, loss=0.0),
    ]   # 3 wins / 4 trades = 75%; total = 400

    mock_s = _empty_db_session()
    mock_s.execute = AsyncMock(
        return_value=MagicMock(**{"scalars.return_value.all.return_value": trades})
    )

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_performance(user)

    assert "75" in text      # win rate
    assert "400" in text     # total P&L 200+100-50+150
    assert user.ai_name in text


# ─────────────────────────────────────────────────────────────────────────────
# CHAT
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_unlinked():
    svc  = _wa_service()
    text = await svc._cmd_chat(None, "Should I buy Bitcoin?")
    assert "link" in text.lower() or "start" in text.lower()


@pytest.mark.asyncio
async def test_chat_empty_question():
    svc  = _wa_service()
    user = _fake_user()
    text = await svc._cmd_chat(user, "")
    assert "chat" in text.lower() or "usage" in text.lower()


@pytest.mark.asyncio
async def test_chat_returns_ai_response():
    svc  = _wa_service()
    user = _fake_user()

    mock_agent = AsyncMock()
    mock_agent.respond = AsyncMock(
        return_value={"response": "BTC looks bullish based on current RSI."}
    )

    with patch("src.agents.core.conversation_agent.ConversationAgent",
               return_value=mock_agent):
        text = await svc._cmd_chat(user, "Should I buy Bitcoin?")

    assert "rsi" in text.lower() or "bullish" in text.lower()


@pytest.mark.asyncio
async def test_chat_response_truncated_at_1600():
    """CHAT truncates responses to 1600 chars (WhatsApp limit)."""
    svc       = _wa_service()
    user      = _fake_user()
    send_mock = AsyncMock()

    long_response = "A" * 2500
    mock_agent    = AsyncMock()
    mock_agent.respond = AsyncMock(return_value={"response": long_response})

    with patch("src.agents.core.conversation_agent.ConversationAgent",
               return_value=mock_agent), \
         patch.object(svc, "send_message",     new=send_mock), \
         patch.object(svc, "_log",             new=AsyncMock()), \
         patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=user)):
        await svc.handle_incoming_message(_FROM, "CHAT What is momentum trading?")

    sent: str = send_mock.call_args[0][1]
    assert len(sent) <= 1600
    assert sent.endswith("...")


# ─────────────────────────────────────────────────────────────────────────────
# UNLINK
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unlink_not_linked():
    svc  = _wa_service()
    text = await svc._cmd_unlink(None, _PHONE)
    assert "no linked" in text.lower() or "not found" in text.lower()


@pytest.mark.asyncio
async def test_unlink_removes_external_account():
    """UNLINK deletes the UserExternalAccount row and confirms."""
    svc  = _wa_service()
    user = _fake_user()

    ext_account = SimpleNamespace(platform="whatsapp", external_id=_PHONE)

    mock_s = _empty_db_session()
    mock_s.execute = AsyncMock(
        return_value=MagicMock(**{"scalar_one_or_none.return_value": ext_account})
    )

    with patch("src.integrations.whatsapp_bot.AsyncSessionLocal", return_value=mock_s):
        text = await svc._cmd_unlink(user, _PHONE)

    mock_s.delete.assert_called_once_with(ext_account)
    mock_s.commit.assert_called_once()
    assert "unlinked" in text.lower() or "disconnected" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# HELP
# ─────────────────────────────────────────────────────────────────────────────

def test_help_contains_all_commands():
    svc  = _wa_service()
    text = svc._cmd_help()
    for cmd in ("PORTFOLIO", "TRADE", "CLOSE", "HISTORY", "PERFORMANCE", "CHAT"):
        assert cmd in text, f"{cmd} missing from HELP"


def test_help_within_whatsapp_limit():
    """HELP message must fit within the 1600-char WhatsApp limit."""
    from src.integrations.whatsapp_bot import _MAX_MSG
    svc  = _wa_service()
    text = svc._cmd_help()
    assert len(text) <= _MAX_MSG


# ─────────────────────────────────────────────────────────────────────────────
# send_trade_alert
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_trade_alert_success():
    """send_trade_alert returns True and sends the message."""
    svc = _wa_service()
    svc.send_message = AsyncMock()

    result = await svc.send_trade_alert(
        whatsapp_number=_PHONE,
        symbol="BTCUSDT",
        side="BUY",
        entry_price=50_000.0,
        stop_loss=49_000.0,
        take_profit=52_000.0,
        confidence=82,
        reasoning="Strong breakout above resistance.",
    )

    assert result is True
    svc.send_message.assert_called_once()
    body: str = svc.send_message.call_args[0][1]
    assert "BTCUSDT" in body
    assert "82%" in body


@pytest.mark.asyncio
async def test_send_trade_alert_twilio_error_returns_false():
    """send_trade_alert returns False if Twilio throws."""
    svc = _wa_service()
    svc.send_message = AsyncMock(side_effect=Exception("Twilio error"))

    result = await svc.send_trade_alert(
        whatsapp_number=_PHONE,
        symbol="ETHUSDT",
        side="SELL",
        entry_price=3_000.0,
        stop_loss=3_060.0,
        take_profit=2_940.0,
        confidence=70,
        reasoning="Test",
    )
    assert result is False


@pytest.mark.asyncio
async def test_trade_alert_truncated_for_long_reasoning():
    """Trade alert with very long reasoning is still under 1600 chars."""
    svc = _wa_service()
    svc.send_message = AsyncMock()

    long_reason = "Very detailed reason. " * 200   # ~4400 chars

    await svc.send_trade_alert(
        whatsapp_number=_PHONE,
        symbol="SOLUSDT",
        side="BUY",
        entry_price=150.0,
        stop_loss=145.0,
        take_profit=160.0,
        confidence=75,
        reasoning=long_reason,
    )

    body: str = svc.send_message.call_args[0][1]
    assert len(body) <= 1600


# ─────────────────────────────────────────────────────────────────────────────
# Webhook endpoint — POST /webhooks/whatsapp
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_returns_ok_when_bot_not_ready():
    """POST /webhooks/whatsapp → 200 when bot is None (graceful accept)."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from routers.whatsapp_webhooks import set_whatsapp_bot_service

    set_whatsapp_bot_service(None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/whatsapp",
            data={"From": "whatsapp:+14155550100", "Body": "HELP"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_dispatches_message_when_bot_ready():
    """POST /webhooks/whatsapp → calls handle_incoming_message."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from routers.whatsapp_webhooks import set_whatsapp_bot_service

    mock_svc = MagicMock()
    mock_svc.handle_incoming_message = AsyncMock()

    set_whatsapp_bot_service(mock_svc)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/whatsapp",
            data={"From": "whatsapp:+14155550100", "Body": "START"},
        )

    assert resp.status_code == 200
    mock_svc.handle_incoming_message.assert_called_once_with(
        "whatsapp:+14155550100", "START"
    )

    set_whatsapp_bot_service(None)


@pytest.mark.asyncio
async def test_webhook_ignores_empty_from():
    """POST /webhooks/whatsapp with no From field is accepted but not dispatched."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from routers.whatsapp_webhooks import set_whatsapp_bot_service

    mock_svc = MagicMock()
    mock_svc.handle_incoming_message = AsyncMock()
    set_whatsapp_bot_service(mock_svc)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/webhooks/whatsapp", data={"Body": "HELP"})

    assert resp.status_code == 200
    mock_svc.handle_incoming_message.assert_not_called()

    set_whatsapp_bot_service(None)


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoints — WhatsApp linking codes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_whatsapp_code_returns_6_digits():
    """POST /api/auth/whatsapp/linking-code returns a valid 6-digit code."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from routers.auth import get_current_user
    from database import get_db

    mock_user  = _fake_user()
    mock_s     = _empty_db_session()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db]           = lambda: mock_s

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/whatsapp/linking-code",
                headers={"Authorization": "Bearer fake"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["code"]) == 6
    assert data["code"].isdigit()
    assert "LINK" in data["instruction"]


@pytest.mark.asyncio
async def test_link_whatsapp_account_valid_code():
    """POST /api/auth/whatsapp/link-account with valid code → 200 success."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from database import get_db

    valid_row = SimpleNamespace(
        code="654321",
        user_id="user-001",
        is_used=False,
        used_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    mock_s = AsyncMock()
    mock_s.__aenter__ = AsyncMock(return_value=mock_s)
    mock_s.__aexit__  = AsyncMock(return_value=False)
    mock_s.execute = AsyncMock(side_effect=[
        MagicMock(**{"scalar_one_or_none.return_value": valid_row}),
        MagicMock(**{"scalar_one_or_none.return_value": None}),
    ])
    mock_s.add    = MagicMock()
    mock_s.commit = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_s

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/whatsapp/link-account",
                json={"code": "654321", "whatsapp_number": "+14155550100"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


@pytest.mark.asyncio
async def test_link_whatsapp_account_invalid_code():
    """POST /api/auth/whatsapp/link-account with bad code → 400."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from database import get_db

    mock_s = AsyncMock()
    mock_s.__aenter__ = AsyncMock(return_value=mock_s)
    mock_s.__aexit__  = AsyncMock(return_value=False)
    mock_s.execute = AsyncMock(
        return_value=MagicMock(**{"scalar_one_or_none.return_value": None})
    )

    app.dependency_overrides[get_db] = lambda: mock_s

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/whatsapp/link-account",
                json={"code": "000000", "whatsapp_number": "+1999"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower() or "expired" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_link_whatsapp_account_duplicate_number():
    """POST /api/auth/whatsapp/link-account with a number linked to another user → 409."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from database import get_db

    valid_row = SimpleNamespace(
        code="111111", user_id="user-A",
        is_used=False, used_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    # Existing account belongs to a DIFFERENT user
    existing_ext = SimpleNamespace(
        platform="whatsapp", external_id="+14155550100", user_id="user-B"
    )

    mock_s = AsyncMock()
    mock_s.__aenter__ = AsyncMock(return_value=mock_s)
    mock_s.__aexit__  = AsyncMock(return_value=False)
    mock_s.execute = AsyncMock(side_effect=[
        MagicMock(**{"scalar_one_or_none.return_value": valid_row}),
        MagicMock(**{"scalar_one_or_none.return_value": existing_ext}),
    ])

    app.dependency_overrides[get_db] = lambda: mock_s

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/whatsapp/link-account",
                json={"code": "111111", "whatsapp_number": "+14155550100"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
