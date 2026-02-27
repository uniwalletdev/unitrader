"""
tests/test_telegram_bot.py — Unit tests for the Telegram bot integration.

All tests here are pure unit tests (no live API calls, no real DB).
They mock at the session / model / bot layer so the test suite runs offline.

Run:
    pytest tests/test_telegram_bot.py -v
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Path setup (mirrors conftest.py) ─────────────────────────────────────────
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — build fake Telegram objects without a real Bot instance
# ─────────────────────────────────────────────────────────────────────────────

def _tg_user(user_id: int = 123456789, username: str = "testtrader") -> MagicMock:
    """Minimal fake telegram.User."""
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.first_name = "Test"
    u.is_bot = False
    return u


def _tg_chat(chat_id: int = 123456789) -> MagicMock:
    chat = MagicMock()
    chat.id = chat_id
    chat.send_action = AsyncMock()
    return chat


def _tg_message(text: str = "/start", user_id: int = 123456789) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    msg.chat = _tg_chat(user_id)
    return msg


def _update(text: str = "/start", user_id: int = 123456789) -> MagicMock:
    """Fake telegram.Update."""
    upd = MagicMock()
    upd.effective_user = _tg_user(user_id)
    upd.message = _tg_message(text, user_id)
    upd.callback_query = None
    return upd


def _ctx(args: list[str] | None = None) -> MagicMock:
    """Fake telegram.ext.ContextTypes.DEFAULT_TYPE."""
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


def _fake_user(user_id: str = "user-001", ai_name: str = "Atlas") -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        ai_name=ai_name,
        is_active=True,
        email="trader@example.com",
        subscription_tier="trial",
    )


def _bot_service():
    """Return a TelegramBotService without calling initialize()."""
    from src.integrations.telegram_bot import TelegramBotService
    svc = TelegramBotService.__new__(TelegramBotService)
    svc.token = "fake:TOKEN"
    svc.app = MagicMock()
    svc.app.bot = AsyncMock()
    return svc


# ─────────────────────────────────────────────────────────────────────────────
# /start — unlinked user
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_unlinked_user():
    """/start for a user not yet linked shows the linking instructions."""
    svc = _bot_service()
    upd = _update("/start")

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=None)), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_start(upd, _ctx())

    reply_text: str = upd.message.reply_text.call_args[0][0]
    assert "/link" in reply_text
    assert "unitrader" in reply_text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /start — linked user
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_linked_user():
    """/start for a linked user shows the command menu."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/start")

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=user)), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_start(upd, _ctx())

    reply_text: str = upd.message.reply_text.call_args[0][0]
    assert "/portfolio" in reply_text
    assert user.ai_name in reply_text


# ─────────────────────────────────────────────────────────────────────────────
# /link — already linked
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_link_already_linked():
    """/link when already linked shows a friendly notice."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/link")

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=user)):
        await svc.cmd_link(upd, _ctx())

    reply_text: str = upd.message.reply_text.call_args[0][0]
    assert "already linked" in reply_text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /link — invalid / expired code
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_link_invalid_code():
    """/link BADCODE returns an error."""
    svc = _bot_service()
    upd = _update("/link BADCODE")

    # DB returns no matching code row
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=None)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal", return_value=mock_session):
        await svc.cmd_link(upd, _ctx(["BADCODE"]))

    reply_text: str = upd.message.reply_text.call_args[0][0]
    assert "invalid" in reply_text.lower() or "expired" in reply_text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /link — generate new code (bot-initiated, no args)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_link_generates_code_when_no_args():
    """/link with no args generates and returns a 6-digit code."""
    svc = _bot_service()
    upd = _update("/link")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_session.add     = MagicMock()
    mock_session.commit  = AsyncMock()

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=None)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal", return_value=mock_session):
        await svc.cmd_link(upd, _ctx([]))   # no args → bot-initiated

    reply_text: str = upd.message.reply_text.call_args[0][0]
    assert any(c.isdigit() for c in reply_text), "Reply should contain the generated code"
    assert "15 minutes" in reply_text.lower() or "expire" in reply_text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /portfolio — unlinked user
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_unlinked():
    """/portfolio before linking returns a link-first error."""
    svc = _bot_service()
    upd = _update("/portfolio")

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=None)):
        await svc.cmd_portfolio(upd, _ctx())

    text = upd.message.reply_text.call_args[0][0]
    assert "/start" in text or "not linked" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /portfolio — no open positions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_empty():
    """/portfolio with no open trades returns a friendly empty state."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/portfolio")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal", return_value=mock_session), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_portfolio(upd, _ctx())

    text = upd.message.reply_text.call_args[0][0]
    assert "no open" in text.lower() or "no position" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /portfolio — with open positions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_with_positions():
    """/portfolio formats each open trade with symbol, entry, and P&L."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/portfolio")

    trade = SimpleNamespace(
        symbol="BTCUSDT", side="BUY",
        entry_price=50_000.0, stop_loss=49_000.0, take_profit=52_000.0,
        quantity=0.001,
        profit=120.0, loss=0.0, profit_percent=0.24,
        created_at=datetime.now(timezone.utc),
    )

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [trade]
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal", return_value=mock_session), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_portfolio(upd, _ctx())

    text = upd.message.reply_text.call_args[0][0]
    assert "BTCUSDT" in text
    assert "50,000" in text or "50000" in text


# ─────────────────────────────────────────────────────────────────────────────
# /trade — argument validation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("args,expected_fragment", [
    ([], "invalid format"),
    (["BUY", "BTCUSDT"], "invalid format"),           # missing size
    (["HOLD", "BTCUSDT", "1.0"], "BUY"),                  # bad side
    (["BUY", "BTCUSDT", "0"], "0.1"),                  # size too small
    (["BUY", "BTCUSDT", "5.0"], "0.1"),                # size too large
])
async def test_trade_bad_args(args, expected_fragment):
    """/trade with bad args replies with a usage hint."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update(f"/trade {' '.join(args)}")

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)):
        await svc.cmd_trade(upd, _ctx(args))

    text = upd.message.reply_text.call_args[0][0]
    assert expected_fragment.lower() in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /trade — no exchange configured
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trade_no_exchange():
    """/trade when no exchange API key is configured shows a helpful message."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/trade BUY BTCUSDT 1.5")

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)), \
         patch.object(svc, "_get_primary_exchange", new=AsyncMock(return_value=None)), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_trade(upd, _ctx(["BUY", "BTCUSDT", "1.5"]))

    text = upd.message.reply_text.call_args[0][0]
    assert "exchange" in text.lower() or "api key" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /close — symbol not found
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_no_open_position():
    """/close BTCUSDT when no open trade exists for that symbol."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/close BTCUSDT")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal", return_value=mock_session), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_close(upd, _ctx(["BTCUSDT"]))

    text = upd.message.reply_text.call_args[0][0]
    assert "no open position" in text.lower() or "not found" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /history — no trades
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_empty():
    """/history with no closed trades shows an empty-state message."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/history")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal", return_value=mock_session), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_history(upd, _ctx())

    text = upd.message.reply_text.call_args[0][0]
    assert "no closed" in text.lower() or "no trade" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /history — with trades
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_with_trades():
    """/history lists closed trades with P&L."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/history")

    closed_at = datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc)
    trades = [
        SimpleNamespace(
            symbol="BTCUSDT", side="BUY",
            entry_price=48_000.0,
            profit=300.0, loss=0.0, profit_percent=0.625,
            closed_at=closed_at,
        ),
        SimpleNamespace(
            symbol="ETHUSDT", side="SELL",
            entry_price=3_200.0,
            profit=0.0, loss=50.0, profit_percent=-1.56,
            closed_at=closed_at,
        ),
    ]

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = trades
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal", return_value=mock_session), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_history(upd, _ctx())

    text = upd.message.reply_text.call_args[0][0]
    assert "BTCUSDT" in text
    assert "ETHUSDT" in text


# ─────────────────────────────────────────────────────────────────────────────
# /performance — no trades baseline
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_performance_no_trades():
    """/performance with zero closed trades returns the empty state."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/performance")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal", return_value=mock_session), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_performance(upd, _ctx())

    text = upd.message.reply_text.call_args[0][0]
    assert "no closed" in text.lower() or "no trade" in text.lower()


@pytest.mark.asyncio
async def test_performance_with_trades():
    """/performance shows win rate, total profit, and streak correctly."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/performance")

    trades = [
        SimpleNamespace(profit=200.0, loss=0.0),
        SimpleNamespace(profit=150.0, loss=0.0),
        SimpleNamespace(profit=0.0,   loss=80.0),
        SimpleNamespace(profit=300.0, loss=0.0),
    ]

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = trades
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal", return_value=mock_session), \
         patch.object(svc, "_log", new=AsyncMock()):
        await svc.cmd_performance(upd, _ctx())

    text = upd.message.reply_text.call_args[0][0]
    assert "75.0%" in text or "75%" in text   # 3/4 winning
    assert "570" in text                       # total profit 200+150+300-80 = 570


# ─────────────────────────────────────────────────────────────────────────────
# /chat — no question
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_no_question():
    """/chat with no text returns a usage hint."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/chat")

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)):
        await svc.cmd_chat(upd, _ctx([]))

    text = upd.message.reply_text.call_args[0][0]
    assert "usage" in text.lower() or "/chat" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /chat — with question, mocked AI response
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_with_question():
    """/chat forwards the question to ConversationAgent and replies."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/chat Should I buy Bitcoin?")

    mock_agent = AsyncMock()
    mock_agent.respond = AsyncMock(return_value={"response": "Based on current RSI levels, I suggest waiting."})

    with patch.object(svc, "_require_linked", new=AsyncMock(return_value=user)), \
         patch("src.integrations.telegram_bot.AsyncSessionLocal"), \
         patch.object(svc, "_log", new=AsyncMock()), \
         patch("src.agents.core.conversation_agent.ConversationAgent", return_value=mock_agent):
        await svc.cmd_chat(upd, _ctx(["Should", "I", "buy", "Bitcoin?"]))

    text = upd.message.reply_text.call_args[0][0]
    assert "rsi" in text.lower() or "waiting" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /unlink — shows confirmation keyboard
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unlink_shows_confirmation():
    """/unlink shows an inline keyboard asking the user to confirm."""
    svc  = _bot_service()
    user = _fake_user()
    upd  = _update("/unlink")

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=user)):
        await svc.cmd_unlink(upd, _ctx())

    upd.message.reply_text.assert_called_once()
    call_kwargs = upd.message.reply_text.call_args
    # The second positional arg or keyword arg should be a keyboard
    assert call_kwargs.kwargs.get("reply_markup") is not None or len(call_kwargs.args) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# /unlink — not linked
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unlink_not_linked():
    """/unlink when not linked shows a 'nothing to unlink' message."""
    svc = _bot_service()
    upd = _update("/unlink")

    with patch.object(svc, "_get_linked_user", new=AsyncMock(return_value=None)):
        await svc.cmd_unlink(upd, _ctx())

    text = upd.message.reply_text.call_args[0][0]
    assert "no linked" in text.lower() or "not found" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# /help — always works
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_help_shows_all_commands():
    """/help lists every major command."""
    svc = _bot_service()
    upd = _update("/help")

    await svc.cmd_help(upd, _ctx())

    text = upd.message.reply_text.call_args[0][0]
    for cmd in ("/portfolio", "/trade", "/close", "/history", "/performance", "/chat"):
        assert cmd in text, f"{cmd} missing from /help output"


# ─────────────────────────────────────────────────────────────────────────────
# _winning_streak helper
# ─────────────────────────────────────────────────────────────────────────────

def test_winning_streak_empty():
    from src.integrations.telegram_bot import _winning_streak
    assert _winning_streak([]) == 0


def test_winning_streak_all_wins():
    from src.integrations.telegram_bot import _winning_streak
    assert _winning_streak([100, 200, 300]) == 3


def test_winning_streak_mixed():
    from src.integrations.telegram_bot import _winning_streak
    # W W L W W W L W  → best streak = 3
    profits = [50, 80, -20, 90, 110, 70, -5, 30]
    assert _winning_streak(profits) == 3


def test_winning_streak_all_losses():
    from src.integrations.telegram_bot import _winning_streak
    assert _winning_streak([-10, -20, -5]) == 0


# ─────────────────────────────────────────────────────────────────────────────
# send_trade_alert — pushes notification when bot is initialised
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_trade_alert_success():
    """send_trade_alert returns True when Telegram message is sent."""
    svc = _bot_service()
    svc.app.bot.send_message = AsyncMock()

    result = await svc.send_trade_alert(
        telegram_user_id="987654321",
        symbol="BTCUSDT",
        side="BUY",
        entry_price=50_000.0,
        stop_loss=49_000.0,
        take_profit=52_000.0,
        confidence=82,
        reasoning="Strong momentum breakout above resistance.",
    )

    assert result is True
    svc.app.bot.send_message.assert_called_once()
    call_kwargs = svc.app.bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == "987654321"
    assert "BTCUSDT" in call_kwargs["text"]
    assert "82%" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_trade_alert_no_app():
    """send_trade_alert returns False when bot is not yet initialised."""
    from src.integrations.telegram_bot import TelegramBotService
    svc = TelegramBotService.__new__(TelegramBotService)
    svc.token = "fake:TOKEN"
    svc.app = None   # not initialised

    result = await svc.send_trade_alert(
        telegram_user_id="1",
        symbol="ETHUSDT",
        side="SELL",
        entry_price=3000.0,
        stop_loss=3060.0,
        take_profit=2940.0,
        confidence=70,
        reasoning="Test",
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_trade_alert_telegram_error():
    """send_trade_alert returns False and doesn't raise on Telegram errors."""
    svc = _bot_service()
    svc.app.bot.send_message = AsyncMock(side_effect=Exception("Telegram API error"))

    result = await svc.send_trade_alert(
        telegram_user_id="111",
        symbol="SOLUSDT",
        side="BUY",
        entry_price=150.0,
        stop_loss=145.0,
        take_profit=160.0,
        confidence=65,
        reasoning="Test error handling",
    )
    assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Webhook endpoint — POST /webhooks/telegram
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_returns_ok_when_bot_ready():
    """POST /webhooks/telegram → 200 {"status": "ok"} when bot is set."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from routers.telegram_webhooks import set_telegram_bot_service

    # Inject a mock bot service that accepts any update
    mock_svc = MagicMock()
    mock_svc.app = MagicMock()
    mock_svc.app.bot = AsyncMock()
    mock_svc.process_update = AsyncMock()

    # Patch Update.de_json to avoid real Telegram SDK validation
    fake_update = MagicMock()

    set_telegram_bot_service(mock_svc)

    with patch("routers.telegram_webhooks.Update") as mock_update_cls:
        mock_update_cls.de_json.return_value = fake_update
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/telegram",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 1,
                        "date": 1_700_000_000,
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 123, "is_bot": False, "first_name": "T"},
                        "text": "/start",
                    },
                },
            )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_svc.process_update.assert_called_once_with(fake_update)

    # Restore clean state
    set_telegram_bot_service(None)


@pytest.mark.asyncio
async def test_webhook_returns_ok_when_bot_not_ready():
    """POST /webhooks/telegram → 200 {"status": "ok"} even when bot is None (graceful)."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from routers.telegram_webhooks import set_telegram_bot_service

    set_telegram_bot_service(None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/telegram",
            json={"update_id": 1},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoints — linking code generation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_link_code_returns_6_digit_code():
    """POST /api/auth/telegram/linking-code returns a 6-digit code + instruction."""
    from httpx import AsyncClient, ASGITransport
    from main import app

    mock_user = _fake_user()

    async def _fake_get_current_user():
        return mock_user

    # Patch auth dependency + DB session
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete  = AsyncMock()
    mock_session.add     = MagicMock()
    mock_session.commit  = AsyncMock()

    from routers.auth import get_current_user, router as auth_router
    from database import get_db

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/telegram/linking-code",
                headers={"Authorization": "Bearer fake_token"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["code"]) == 6
    assert data["code"].isdigit()
    assert data["expires_in_minutes"] == 15
    assert data["code"] in data["instruction"]


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoints — link-account (bot calls this after /link CODE)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_link_account_success():
    """POST /api/auth/telegram/link-account with valid code creates the link."""
    from httpx import AsyncClient, ASGITransport
    from main import app

    valid_code_row = SimpleNamespace(
        code="123456",
        user_id="user-001",
        is_used=False,
        used_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)

    # First execute() → returns the TelegramLinkingCode
    # Second execute() → returns None (no existing UserExternalAccount)
    mock_session.execute = AsyncMock(side_effect=[
        MagicMock(**{"scalar_one_or_none.return_value": valid_code_row}),
        MagicMock(**{"scalar_one_or_none.return_value": None}),
    ])
    mock_session.add    = MagicMock()
    mock_session.commit = AsyncMock()

    from database import get_db
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/telegram/link-account",
                json={
                    "code": "123456",
                    "telegram_user_id": "987654321",
                    "telegram_username": "testtrader",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


@pytest.mark.asyncio
async def test_link_account_invalid_code():
    """POST /api/auth/telegram/link-account with bad code → 400."""
    from httpx import AsyncClient, ASGITransport
    from main import app
    from database import get_db

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(**{"scalar_one_or_none.return_value": None})
    )

    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/telegram/link-account",
                json={"code": "000000", "telegram_user_id": "111"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower() or "expired" in resp.json()["detail"].lower()
