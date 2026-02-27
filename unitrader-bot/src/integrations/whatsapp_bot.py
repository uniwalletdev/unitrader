"""
src/integrations/whatsapp_bot.py — WhatsApp bot service for Unitrader via Twilio.

WhatsApp-specific constraints vs Telegram:
  - No slash-prefixed commands — users type plain-text keywords (TRADE, HELP, etc.)
  - 1600-char message limit per WhatsApp message
  - Twilio `Client.messages.create()` is synchronous; wrapped in asyncio executor
  - No inline keyboards — confirmations use plain-text round-trips
  - Request authentication via Twilio HMAC signature (validated in the router)

Supported commands (case-insensitive):
  START              — Welcome / link status
  LINK [CODE]        — Link WhatsApp to Unitrader account
  PORTFOLIO          — Open positions
  TRADE BUY BTC 1.5  — Execute a trade
  CLOSE BTCUSDT      — Close an open position
  HISTORY            — Last 5 closed trades
  PERFORMANCE        — Win-rate and profit stats
  CHAT <question>    — Ask the AI anything
  ALERTS             — Coming-soon placeholder
  SETTINGS           — Deep-link to web settings
  UNLINK             — Disconnect this WhatsApp number
  HELP               — Command reference
"""

import asyncio
import logging
import random
import string
import time
from datetime import datetime, timedelta, timezone
from functools import partial

from config import settings
from database import AsyncSessionLocal
from models import (
    BotMessage,
    TelegramLinkingCode,   # reused for WhatsApp — same OTP mechanic
    Trade,
    User,
    UserExternalAccount,
)

logger = logging.getLogger(__name__)

_PLATFORM = "whatsapp"
_MAX_MSG   = 1_600   # Twilio WhatsApp limit


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def _trunc(text: str, limit: int = _MAX_MSG) -> str:
    """Truncate a message to WhatsApp's per-message character limit."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


# ─────────────────────────────────────────────────────────────────────────────
# WhatsAppBotService
# ─────────────────────────────────────────────────────────────────────────────

class WhatsAppBotService:
    """
    WhatsApp bot service using Twilio Messaging API.

    Twilio's Python client is synchronous; outbound sends are dispatched via
    asyncio's default thread-pool executor so they never block the event loop.
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        twilio_whatsapp_number: str,
    ) -> None:
        from twilio.rest import Client  # lazy import — not installed in test env by default
        self._client = Client(account_sid, auth_token)
        self._from   = f"whatsapp:{twilio_whatsapp_number}"
        self.account_sid  = account_sid
        self.auth_token   = auth_token
        self.twilio_number = twilio_whatsapp_number

    # ── Entry point ───────────────────────────────────────────────────────────

    async def handle_incoming_message(
        self, from_field: str, body: str
    ) -> None:
        """Dispatch a Twilio webhook payload to the correct command handler.

        Args:
            from_field: The 'From' field from Twilio, e.g. ``whatsapp:+14155552671``
            body: The raw message text sent by the user.
        """
        # Normalise: strip the "whatsapp:" prefix Twilio adds
        phone = from_field.removeprefix("whatsapp:").strip()

        parts   = (body or "").strip().split()
        command = (parts[0] if parts else "help").lower()
        args    = parts[1:]

        t0   = time.perf_counter()
        user = await self._get_linked_user(phone)

        try:
            if command == "start":
                response = await self._cmd_start(user, phone)
            elif command == "link":
                response = await self._cmd_link(user, phone, args)
            elif command == "portfolio":
                response = await self._cmd_portfolio(user)
            elif command == "trade":
                response = await self._cmd_trade(user, args)
            elif command == "close":
                response = await self._cmd_close(user, args)
            elif command == "history":
                response = await self._cmd_history(user)
            elif command == "performance":
                response = await self._cmd_performance(user)
            elif command == "chat":
                response = await self._cmd_chat(user, " ".join(args))
            elif command == "alerts":
                response = await self._cmd_alerts(user)
            elif command == "settings":
                response = await self._cmd_settings(user)
            elif command == "unlink":
                response = await self._cmd_unlink(user, phone)
            elif command == "help":
                response = self._cmd_help()
            else:
                response = (
                    "Unknown command.\n\n"
                    "Send HELP to see all available commands."
                )

            status = "success"

        except Exception as exc:
            logger.error("WhatsApp handler error [%s] from %s: %s", command, phone, exc)
            response = "An error occurred. Please try again in a moment."
            status   = "error"

        ms = int((time.perf_counter() - t0) * 1000)

        await self.send_message(phone, _trunc(response))
        await self._log(
            external_user_id=phone,
            message_type="command",
            command=command,
            user_message=body,
            bot_response=response,
            status=status,
            user_id=user.id if user else None,
            response_time_ms=ms,
        )

    # ── Commands ──────────────────────────────────────────────────────────────

    async def _cmd_start(self, user: User | None, phone: str) -> str:
        if user:
            return (
                f"👋 Welcome back, *{user.ai_name}* is ready!\n\n"
                "Quick commands:\n"
                "PORTFOLIO — open positions\n"
                "TRADE BUY BTCUSDT 1.5 — execute trade\n"
                "PERFORMANCE — your stats\n"
                "HELP — all commands"
            )
        return (
            "👋 Welcome to *Unitrader*!\n\n"
            "To start trading, link this WhatsApp number to your account:\n\n"
            f"1. Log in at {settings.frontend_url}\n"
            "2. Go to Settings → Connected Accounts\n"
            "3. Copy your 6-digit code\n"
            "4. Reply: LINK 123456\n\n"
            "Or send LINK to generate a code from here."
        )

    async def _cmd_link(
        self, user: User | None, phone: str, args: list[str]
    ) -> str:
        if user:
            return (
                "Your WhatsApp is already linked.\n"
                "Send UNLINK first to connect a different account."
            )

        # ── Mode A: user supplies code from the website ───────────────────────
        if args:
            code = args[0].strip().upper()
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select as sa_select
                row = (await db.execute(
                    sa_select(TelegramLinkingCode).where(
                        TelegramLinkingCode.code == code,
                        TelegramLinkingCode.is_used == False,  # noqa: E712
                        TelegramLinkingCode.expires_at > _now(),
                    )
                )).scalar_one_or_none()

                if not row:
                    return (
                        "Invalid or expired code.\n\n"
                        "Codes expire after 15 minutes.\n"
                        "Generate a new one at the Unitrader website."
                    )

                user_id = row.user_id

                # Bot-initiated: store our phone number; web completes the link
                if not user_id:
                    row.telegram_user_id = phone   # reusing the field
                    row.telegram_username = phone
                    await db.commit()
                    return (
                        f"Code registered!\n\n"
                        f"Go to {settings.frontend_url}/link-whatsapp "
                        f"and enter:\n\n*{code}*\n\n"
                        "The link will complete automatically."
                    )

                # Web-initiated: create the account link now
                row.is_used  = True
                row.used_at  = _now()

                existing = (await db.execute(
                    sa_select(UserExternalAccount).where(
                        UserExternalAccount.user_id == user_id,
                        UserExternalAccount.platform == _PLATFORM,
                    )
                )).scalar_one_or_none()

                if existing:
                    existing.is_linked         = True
                    existing.linked_at         = _now()
                    existing.external_id       = phone
                    existing.external_username = phone
                else:
                    db.add(UserExternalAccount(
                        user_id=user_id,
                        platform=_PLATFORM,
                        external_id=phone,
                        external_username=phone,
                        is_linked=True,
                        settings={"notifications": True, "trade_alerts": True},
                    ))

                fetched = (await db.execute(
                    sa_select(User).where(User.id == user_id)
                )).scalar_one_or_none()
                ai_name = fetched.ai_name if fetched else "your AI"
                await db.commit()

            return (
                f"✅ Linked successfully!\n\n"
                f"Your AI *{ai_name}* is ready to trade.\n\n"
                "Send HELP to see all commands."
            )

        # ── Mode B: bot generates a code ──────────────────────────────────────
        code    = _generate_code()
        expires = _now() + timedelta(minutes=15)

        async with AsyncSessionLocal() as db:
            db.add(TelegramLinkingCode(
                code=code,
                user_id=None,
                telegram_user_id=phone,
                telegram_username=phone,
                expires_at=expires,
            ))
            await db.commit()

        return (
            f"Your linking code:\n\n*{code}*\n\n"
            f"1. Go to {settings.frontend_url}/link-whatsapp\n"
            "2. Log in and enter the code above\n\n"
            "Code expires in 15 minutes."
        )

    async def _cmd_portfolio(self, user: User | None) -> str:
        if not user:
            return "Send START to link your account first."

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select
            trades = (await db.execute(
                sa_select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.status == "open",
                ).order_by(Trade.created_at.desc())
            )).scalars().all()

        if not trades:
            return "No open positions.\n\nStart trading:\nTRADE BUY BTCUSDT 1.5"

        lines = ["📊 OPEN POSITIONS\n"]
        total_pnl = 0.0
        for t in trades:
            pnl = (t.profit or 0) - (t.loss or 0)
            total_pnl += pnl
            em = "📈" if pnl >= 0 else "📉"
            lines.append(f"{em} {t.symbol} {t.side}  P&L: ${pnl:+,.2f}")
        lines.append(f"\nTotal P&L: ${total_pnl:+,.2f}")
        return "\n".join(lines)

    async def _cmd_trade(self, user: User | None, args: list[str]) -> str:
        if not user:
            return "Send START to link your account first."

        if len(args) < 3:
            return (
                "Invalid format.\n\n"
                "Usage: TRADE BUY BTCUSDT 1.5\n"
                "  Side: BUY or SELL\n"
                "  Size: 0.1 to 2.0 (% of balance)"
            )

        side   = args[0].upper()
        symbol = args[1].upper()
        try:
            size = float(args[2])
        except ValueError:
            return "Position size must be a number (e.g. 1.5)."

        if side not in ("BUY", "SELL"):
            return "Side must be BUY or SELL."
        if not (0.1 <= size <= 2.0):
            return "Position size must be between 0.1 and 2.0%."

        # Resolve exchange
        exchange = await self._get_primary_exchange(user.id)
        if not exchange:
            return (
                "No exchange API key configured.\n\n"
                f"Add one at {settings.frontend_url}/settings/exchange"
            )

        from src.agents.core.trading_agent import TradingAgent
        from src.integrations.market_data import full_market_analysis

        live   = await full_market_analysis(symbol, exchange)
        price  = live["price"]
        sl_d   = price * 0.02
        tp_d   = price * 0.04
        sl     = round((price - sl_d) if side == "BUY" else (price + sl_d), 8)
        tp     = round((price + tp_d) if side == "BUY" else (price - tp_d), 8)

        decision = {
            "decision":          side,
            "confidence":        70,
            "entry_price":       price,
            "stop_loss":         sl,
            "take_profit":       tp,
            "position_size_pct": size,
            "reasoning":         f"Manual WhatsApp trade — {side} {symbol} at {size}%",
        }

        agent  = TradingAgent(user_id=user.id)
        result = await agent.execute_trade(decision, symbol, exchange, user.ai_name)

        if result.get("status") == "executed":
            rr = abs(tp - price) / abs(price - sl) if price != sl else 0
            return (
                f"✅ TRADE EXECUTED\n\n"
                f"{side} {symbol}\n"
                f"Entry: ${price:,.4f}\n"
                f"Stop:  ${sl:,.4f}\n"
                f"TP:    ${tp:,.4f}\n"
                f"R:R ≈ 1:{rr:.1f}\n"
                f"ID: {result.get('trade_id', 'N/A')}"
            )
        return f"Trade rejected: {result.get('reason', 'Unknown')}"

    async def _cmd_close(self, user: User | None, args: list[str]) -> str:
        if not user:
            return "Send START to link your account first."
        if not args:
            return "Usage: CLOSE BTCUSDT"

        symbol = args[0].upper()

        from sqlalchemy import select as sa_select
        from src.agents.core.trading_agent import TradingAgent

        async with AsyncSessionLocal() as db:
            trade = (await db.execute(
                sa_select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.symbol  == symbol,
                    Trade.status  == "open",
                ).order_by(Trade.created_at.desc()).limit(1)
            )).scalar_one_or_none()

        if not trade:
            return f"No open {symbol} position found."

        agent  = TradingAgent(user_id=user.id)
        result = await agent.close_position(trade.id)

        if result.get("status") == "closed":
            pnl = result.get("profit", 0) - result.get("loss", 0)
            pct = result.get("profit_percent", 0)
            em  = "✅" if pnl >= 0 else "📉"
            return (
                f"{em} CLOSED {symbol}\n\n"
                f"Entry: ${trade.entry_price:,.4f}\n"
                f"Exit:  ${result.get('exit_price', 0):,.4f}\n"
                f"P&L:   ${pnl:+,.2f} ({pct:+.2f}%)"
            )
        return f"Could not close: {result.get('reason', 'Unknown')}"

    async def _cmd_history(self, user: User | None) -> str:
        if not user:
            return "Send START to link your account first."

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select
            trades = (await db.execute(
                sa_select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.status  == "closed",
                ).order_by(Trade.closed_at.desc()).limit(5)
            )).scalars().all()

        if not trades:
            return "No closed trades yet."

        lines = ["📜 LAST 5 TRADES\n"]
        for i, t in enumerate(trades, 1):
            pnl = (t.profit or 0) - (t.loss or 0)
            em  = "✅" if pnl >= 0 else "❌"
            when = t.closed_at.strftime("%b %d") if t.closed_at else "—"
            lines.append(f"{i}. {em} {t.symbol} {t.side}  ${pnl:+,.2f}  {when}")
        return "\n".join(lines)

    async def _cmd_performance(self, user: User | None) -> str:
        if not user:
            return "Send START to link your account first."

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select
            trades = (await db.execute(
                sa_select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.status  == "closed",
                )
            )).scalars().all()

        if not trades:
            return "No closed trades yet. Your stats will appear here after your first trade."

        profits = [(t.profit or 0) - (t.loss or 0) for t in trades]
        wins    = [p for p in profits if p > 0]
        total   = sum(profits)
        wr      = len(wins) / len(profits) * 100
        best    = max(profits)
        worst   = min(profits)
        avg     = total / len(profits)

        return (
            f"📈 {user.ai_name}'s STATS\n\n"
            f"Win Rate:   {wr:.1f}%\n"
            f"Total P&L:  ${total:+,.2f}\n"
            f"Trades:     {len(profits)}\n"
            f"Best:       +${best:,.2f}\n"
            f"Worst:      ${worst:,.2f}\n"
            f"Avg/Trade:  ${avg:+,.2f}"
        )

    async def _cmd_chat(self, user: User | None, question: str) -> str:
        if not user:
            return "Send START to link your account first."
        if not question.strip():
            return "Usage: CHAT Should I buy Bitcoin now?"

        from src.agents.core.conversation_agent import ConversationAgent
        agent    = ConversationAgent(user_id=user.id)
        response = await agent.respond(question)
        return response.get("response", "Could not get an AI response right now.")

    async def _cmd_alerts(self, user: User | None) -> str:
        if not user:
            return "Send START to link your account first."
        return (
            "🔔 Price Alerts — Coming Soon!\n\n"
            "You'll be able to set alerts like:\n"
            "ALERT BTCUSDT 70000\n\n"
            "Stay tuned for updates."
        )

    async def _cmd_settings(self, user: User | None) -> str:
        if not user:
            return "Send START to link your account first."
        return (
            f"⚙️ Manage your settings at:\n"
            f"{settings.frontend_url}/settings\n\n"
            "Update max position size, daily loss limit, trading hours, and more."
        )

    async def _cmd_unlink(self, user: User | None, phone: str) -> str:
        if not user:
            return "No linked account found."

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select
            ext = (await db.execute(
                sa_select(UserExternalAccount).where(
                    UserExternalAccount.external_id == phone,
                    UserExternalAccount.platform    == _PLATFORM,
                )
            )).scalar_one_or_none()

            if ext:
                await db.delete(ext)
                await db.commit()

        return (
            "✅ Unlinked!\n\n"
            "Your WhatsApp has been disconnected from Unitrader.\n"
            "Send START to link again at any time."
        )

    def _cmd_help(self) -> str:
        return (
            "📱 UNITRADER COMMANDS\n\n"
            "PORTFOLIO — open positions\n"
            "TRADE BUY BTCUSDT 1.5 — execute trade\n"
            "CLOSE BTCUSDT — close a position\n"
            "HISTORY — last 5 closed trades\n"
            "PERFORMANCE — win rate & stats\n"
            "CHAT <question> — ask your AI\n\n"
            "SETTINGS — manage settings\n"
            "ALERTS — price alert setup\n\n"
            "LINK CODE — link to Unitrader\n"
            "UNLINK — disconnect WhatsApp\n"
            "START — account status\n"
            "HELP — this message\n\n"
            "Examples:\n"
            "TRADE BUY BTCUSDT 1.5\n"
            "CLOSE BTCUSDT\n"
            "CHAT Should I buy Bitcoin?\n\n"
            "Help: unitrader.com/help"
        )

    # ── Outbound: trade alert ─────────────────────────────────────────────────

    async def send_trade_alert(
        self,
        whatsapp_number: str,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        confidence: int,
        reasoning: str,
    ) -> bool:
        """Push a trade execution notification to a user's WhatsApp.

        Called by the trading loop after a trade is placed.
        Returns True if the message was sent successfully.
        """
        em   = "📈" if side == "BUY" else "📉"
        text = _trunc(
            f"{em} TRADE ALERT\n\n"
            f"{side} {symbol}\n"
            f"Entry: ${entry_price:,.4f}\n"
            f"Stop:  ${stop_loss:,.4f}\n"
            f"TP:    ${take_profit:,.4f}\n"
            f"Confidence: {confidence}%\n\n"
            f"{reasoning}"
        )
        try:
            await self.send_message(whatsapp_number, text)
            return True
        except Exception as exc:
            logger.warning("Failed to send WhatsApp trade alert to %s: %s", whatsapp_number, exc)
            return False

    # ── Outbound send ─────────────────────────────────────────────────────────

    async def send_message(self, to_number: str, body: str) -> None:
        """Send a WhatsApp message via Twilio (runs sync client in thread-pool)."""
        to = f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(
                self._client.messages.create,
                from_=self._from,
                to=to,
                body=body,
            ),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_linked_user(self, phone: str) -> User | None:
        """Return the Unitrader User linked to this WhatsApp number, or None."""
        from sqlalchemy import select as sa_select
        async with AsyncSessionLocal() as db:
            ext = (await db.execute(
                sa_select(UserExternalAccount).where(
                    UserExternalAccount.external_id == phone,
                    UserExternalAccount.platform    == _PLATFORM,
                    UserExternalAccount.is_linked   == True,  # noqa: E712
                )
            )).scalar_one_or_none()
            if not ext:
                return None
            ext.last_used_at = _now()
            user = (await db.execute(
                sa_select(User).where(User.id == ext.user_id)
            )).scalar_one_or_none()
            await db.commit()
            return user if user and user.is_active else None

    async def _get_primary_exchange(self, user_id: str) -> str | None:
        from sqlalchemy import select as sa_select
        from models import ExchangeAPIKey
        async with AsyncSessionLocal() as db:
            key = (await db.execute(
                sa_select(ExchangeAPIKey).where(
                    ExchangeAPIKey.user_id   == user_id,
                    ExchangeAPIKey.is_active == True,  # noqa: E712
                ).limit(1)
            )).scalar_one_or_none()
        return key.exchange if key else None

    async def _log(
        self,
        external_user_id: str,
        message_type: str,
        command: str | None,
        user_message: str | None,
        bot_response: str | None,
        status: str,
        *,
        user_id: str | None = None,
        error_message: str | None = None,
        response_time_ms: int | None = None,
    ) -> None:
        """Persist one interaction to bot_messages (fire-and-forget)."""
        try:
            async with AsyncSessionLocal() as db:
                db.add(BotMessage(
                    user_id=user_id,
                    platform=_PLATFORM,
                    external_user_id=external_user_id,
                    message_type=message_type,
                    command=command,
                    user_message=(user_message or "")[:4_000],
                    bot_response=(bot_response or "")[:4_000],
                    status=status,
                    error_message=error_message,
                    response_time_ms=response_time_ms,
                ))
                await db.commit()
        except Exception as exc:
            logger.warning("Failed to log WhatsApp bot message: %s", exc)
