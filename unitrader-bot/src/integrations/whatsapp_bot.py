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
  CHAT <question>    — Ask the AI (same as plain chat when linked)
  ALERTS             — Coming-soon placeholder
  SETTINGS           — Deep-link to web settings
  UNLINK             — Disconnect this WhatsApp number
  HELP               — Command reference

When linked, plain text that is not a known keyword is treated as chat (web-parity
onboarding vs trading). Phrases like "show my portfolio" route to real DB commands.
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

    async def _whatsapp_resolve_pending_trade(
        self, phone: str, body: str, user: User
    ) -> str | None:
        """Handle YES/NO after a chat-suggested trade confirmation."""
        from src.services.bot_pending_trade import (
            get_pending_confirmation,
            pop_pending_confirmation,
        )

        parts = (body or "").strip().split()
        if not parts:
            return None
        head = parts[0].upper()
        if head not in ("YES", "NO"):
            return None
        pend = await get_pending_confirmation(phone)
        if not pend or pend["user_id"] != str(user.id):
            return None
        await pop_pending_confirmation(phone)
        if head == "NO":
            return "Cancelled — no trade placed."
        return await self._execute_whatsapp_confirmed_trade(
            user, pend["trade"], parts
        )

    async def _execute_whatsapp_confirmed_trade(
        self,
        user: User,
        trade: dict,
        yes_parts: list[str],
    ) -> str:
        """Place order via orchestrator after YES (optional USD: YES 50)."""
        from fastapi import HTTPException

        from src.agents.core.conversation_agent import (
            _format_execute_result_for_chat,
            _http_detail_str,
            _orchestrator_route,
        )
        from src.agents.shared_memory import SharedMemory

        side = str(trade.get("side") or "").upper()
        symbol = str(trade.get("symbol") or "").strip()
        if side not in ("BUY", "SELL") or not symbol:
            return "Invalid pending trade. Ask for a new quote in chat."

        async with AsyncSessionLocal() as db:
            sc = await SharedMemory.load(str(user.id), db)
            cap = float(sc.max_trade_amount or 100.0)
            amount = min(cap, 100.0)
            amount = max(amount, 10.0)
            if len(yes_parts) > 1:
                try:
                    custom = float(yes_parts[1])
                    if custom > 0:
                        amount = min(custom, cap)
                        amount = max(amount, 5.0)
                except ValueError:
                    pass

            if not sc.subscription_active:
                return "A subscription is required to execute trades."
            if sc.trading_paused:
                return "Trading is paused. Unpause in Settings before executing."

        try:
            result = await _orchestrator_route(
                str(user.id),
                "trade_execute",
                {"symbol": symbol, "side": side, "amount": amount},
            )
            from src.services.bot_orchestrator_chat import whatsapp_plain_chat_text

            return whatsapp_plain_chat_text(_format_execute_result_for_chat(result))
        except HTTPException as e:
            return f"Could not place order: {_http_detail_str(e.detail)}"
        except Exception as exc:
            logger.warning("WhatsApp confirmed trade failed: %s", exc)
            return "Could not complete the trade. Try the app Trade screen."

    async def _whatsapp_orchestrator_chat_turn(
        self, phone: str, user: User, message: str
    ) -> tuple[str, bool]:
        """Run Apex chat + action tags; plain text. Returns (text, already_sent_to_user)."""
        from src.services.bot_orchestrator_chat import (
            orchestrator_chat_with_actions,
            whatsapp_plain_chat_text,
        )
        from src.services.bot_pending_trade import store_pending_confirmation

        text_in = (message or "").strip()
        if not text_in:
            return "Send a message to continue.", False

        async with AsyncSessionLocal() as db:
            from src.agents.shared_memory import SharedMemory

            sc = await SharedMemory.load(str(user.id), db)
            await db.commit()
            data = await orchestrator_chat_with_actions(
                str(user.id),
                text_in,
                db=db,
                shared_context=sc,
                channel="whatsapp",
            )

        if data.get("requires_confirmation") and data.get("pending_trade"):
            trade = data["pending_trade"]
            confirm = (
                f"⚠️ Confirm trade: {trade['side'].upper()} {trade['symbol']}?\n"
                f"Reply YES to confirm or NO to cancel.\n"
                f"(Optional: YES 50 = $50 notional, up to your max trade setting.)"
            )
            await self.send_message(phone, _trunc(confirm))
            await store_pending_confirmation(
                phone,
                user_id=str(user.id),
                trade=trade,
                ttl_seconds=60,
            )
            return confirm, True

        plain = whatsapp_plain_chat_text(data["text"])
        return plain, False

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
        log_command = command

        t0   = time.perf_counter()
        user = await self._get_linked_user(phone)
        already_sent = False

        # ── Intercept: conversational onboarding in progress ──────────────
        from src.services.bot_onboarding_state import get_onboarding_step

        onb = await get_onboarding_step(phone)
        if onb and user:
            try:
                response = await self._onboarding_handle_step(
                    phone, user, (body or "").strip(), onb
                )
                log_command = "onboarding"
                status = "success"
            except Exception as exc:
                logger.error("WhatsApp onboarding error for %s: %s", phone, exc)
                response = "Something went wrong. Let's try again — what would you like to name your AI trader?"
                status = "error"
            ms = int((time.perf_counter() - t0) * 1000)
            await self.send_message(phone, _trunc(response))
            await self._log(
                external_user_id=phone,
                message_type="command",
                command=log_command,
                user_message=body,
                bot_response=response,
                status=status,
                user_id=user.id if user else None,
                response_time_ms=ms,
            )
            return

        try:
            pending_reply: str | None = None
            if user:
                pending_reply = await self._whatsapp_resolve_pending_trade(
                    phone, body, user
                )

            if pending_reply is not None:
                response = pending_reply
            elif command == "start":
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
                if not user:
                    response = "Send START to link your account first."
                elif not " ".join(args).strip():
                    response = (
                        "Ask a question here or send: CHAT <your question>\n\n"
                        "When linked, you can also type naturally without CHAT."
                    )
                else:
                    response, already_sent = await self._whatsapp_orchestrator_chat_turn(
                        phone, user, " ".join(args)
                    )
            elif command == "alerts":
                response = await self._cmd_alerts(user)
            elif command == "settings":
                response = await self._cmd_settings(user)
            elif command == "unlink":
                response = await self._cmd_unlink(user, phone)
            elif command == "help":
                response = self._cmd_help()
            elif not user and command.isdigit() and len(command) == 6:
                # Bare 6-digit code — treat as LINK <code>
                log_command = "link"
                response = await self._cmd_link(user, phone, [command])
            elif user:
                from src.services.bot_intent import classify_natural_intent

                full = (body or "").strip()
                intent = classify_natural_intent(full)
                if intent["route"] == "command":
                    log_command = intent["command"]
                    subargs = intent.get("args", [])
                    c = intent["command"]
                    if c == "portfolio":
                        response = await self._cmd_portfolio(user)
                    elif c == "trade":
                        response = await self._cmd_trade(user, subargs)
                    elif c == "close":
                        response = await self._cmd_close(user, subargs)
                    elif c == "history":
                        response = await self._cmd_history(user)
                    elif c == "performance":
                        response = await self._cmd_performance(user)
                    else:
                        response, already_sent = (
                            await self._whatsapp_orchestrator_chat_turn(
                                phone, user, full
                            )
                        )
                else:
                    log_command = "chat"
                    response, already_sent = (
                        await self._whatsapp_orchestrator_chat_turn(
                            phone, user, intent["message"]
                        )
                    )
            else:
                response = (
                    "I don't recognise that command.\n\n"
                    "Send START to link your account, or HELP for commands."
                )

            status = "success"

        except Exception as exc:
            logger.error(
                "WhatsApp handler error [%s] from %s: %s", log_command, phone, exc
            )
            response = "An error occurred. Please try again in a moment."
            status   = "error"

        ms = int((time.perf_counter() - t0) * 1000)

        if not already_sent:
            await self.send_message(phone, _trunc(response))
        await self._log(
            external_user_id=phone,
            message_type="command",
            command=log_command,
            user_message=body,
            bot_response=response,
            status=status,
            user_id=user.id if user else None,
            response_time_ms=ms,
        )

    # ── Commands ──────────────────────────────────────────────────────────────

    async def _cmd_start(self, user: User | None, phone: str) -> str:
        if user:
            # If user hasn't named their AI, kick off onboarding
            if not user.ai_name or user.ai_name in ("your AI", "Apex"):
                from src.services.bot_onboarding_state import (
                    STEP_AWAITING_AI_NAME,
                    set_onboarding_step,
                )
                await set_onboarding_step(phone, STEP_AWAITING_AI_NAME)
                return (
                    "👋 Welcome back! Let's finish setting up.\n\n"
                    "What would you like to name your AI trader? "
                    "(e.g. Apex, Nova, Max)\n\n"
                    "Just type a name:"
                )
            return (
                f"👋 Welcome back, *{user.ai_name}* is ready!\n\n"
                "Quick commands:\n"
                "PORTFOLIO — open positions\n"
                "TRADE BUY BTCUSDT 1.5 — execute trade\n"
                "PERFORMANCE — your stats\n"
                "Or ask in plain English (e.g. show my portfolio).\n"
                "HELP — all commands"
            )
        # Create a provisional (chat-only) account so the user can start immediately
        from src.services.provisional_user import create_provisional_user
        from database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            new_user = await create_provisional_user(
                db, platform="whatsapp", external_id=phone, external_username=phone,
            )

        if new_user:
            from src.services.bot_onboarding_state import (
                STEP_AWAITING_AI_NAME,
                set_onboarding_step,
            )
            await set_onboarding_step(phone, STEP_AWAITING_AI_NAME)
            return (
                "👋 Welcome to *Unitrader*!\n\n"
                "I'm your personal AI trading assistant. "
                "Let's get you set up in 30 seconds.\n\n"
                "First — what would you like to name your AI trader? "
                "(e.g. Apex, Nova, Max)\n\n"
                "Just type a name:"
            )

        # Fallback — provisional creation failed (rare edge case)
        return (
            "👋 Welcome to *Unitrader*!\n\n"
            "To start trading, link this WhatsApp number to your account:\n\n"
            f"1. Sign up at {settings.frontend_url}/register\n"
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
                ai_name = fetched.ai_name if fetched else None
                await db.commit()

            # If user hasn't named their AI yet, start onboarding
            if not ai_name or ai_name in ("your AI", "Apex"):
                from src.services.bot_onboarding_state import (
                    STEP_AWAITING_AI_NAME,
                    set_onboarding_step,
                )
                await set_onboarding_step(phone, STEP_AWAITING_AI_NAME)
                return (
                    "✅ Linked successfully!\n\n"
                    "Let's set up your AI trader.\n\n"
                    "First — what would you like to name your AI? "
                    "(e.g. Apex, Nova, Max)\n\n"
                    "Just type a name:"
                )

            return (
                f"✅ Linked successfully!\n\n"
                f"Your AI *{ai_name}* is ready to trade.\n\n"
                "Send HELP to see all commands."
            )

        # ── Mode B: no code supplied ─────────────────────────────────────────
        # Before generating a bot-initiated code, check if there's a recent
        # web-initiated code the user likely meant to include (they clicked
        # "Connect WhatsApp" on the web which generated a code, but the
        # pre-filled text was just "LINK" without the code).
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select
            recent_cutoff = _now() - timedelta(minutes=5)
            pending_rows = (await db.execute(
                sa_select(TelegramLinkingCode).where(
                    TelegramLinkingCode.is_used == False,  # noqa: E712
                    TelegramLinkingCode.expires_at > _now(),
                    TelegramLinkingCode.user_id.isnot(None),
                    TelegramLinkingCode.created_at >= recent_cutoff,
                ).order_by(TelegramLinkingCode.created_at.desc())
            )).scalars().all()

            if len(pending_rows) == 1:
                pending = pending_rows[0]
                pending.is_used = True
                pending.used_at = _now()

                existing = (await db.execute(
                    sa_select(UserExternalAccount).where(
                        UserExternalAccount.user_id == pending.user_id,
                        UserExternalAccount.platform == _PLATFORM,
                    )
                )).scalar_one_or_none()

                if existing:
                    existing.is_linked = True
                    existing.linked_at = _now()
                    existing.external_id = phone
                    existing.external_username = phone
                else:
                    db.add(UserExternalAccount(
                        user_id=pending.user_id,
                        platform=_PLATFORM,
                        external_id=phone,
                        external_username=phone,
                        is_linked=True,
                        settings={"notifications": True, "trade_alerts": True},
                    ))

                fetched = (await db.execute(
                    sa_select(User).where(User.id == pending.user_id)
                )).scalar_one_or_none()
                ai_name = fetched.ai_name if fetched else None
                await db.commit()

                if not ai_name or ai_name in ("your AI", "Apex"):
                    from src.services.bot_onboarding_state import (
                        STEP_AWAITING_AI_NAME,
                        set_onboarding_step,
                    )
                    await set_onboarding_step(phone, STEP_AWAITING_AI_NAME)
                    return (
                        "✅ Linked successfully!\n\n"
                        "Let's set up your AI trader.\n\n"
                        "First — what would you like to name your AI? "
                        "(e.g. Apex, Nova, Max)\n\n"
                        "Just type a name:"
                    )

                return (
                    f"✅ Linked successfully!\n\n"
                    f"Your AI *{ai_name}* is ready to trade.\n\n"
                    "Send HELP to see all commands."
                )

        # ── Mode B fallback: bot generates a code ─────────────────────────────
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

    async def _cmd_chat(self, user: User | None, question: str) -> str:
        """CHAT command / tests: delegate to orchestrator turn (dummy phone if no send)."""
        if not user:
            return "Send START to link your account first."
        q = (question or "").strip()
        if not q:
            return (
                "Ask a question here or send: CHAT <your question>\n\n"
                "When linked, you can also type naturally without CHAT."
            )
        text, _already = await self._whatsapp_orchestrator_chat_turn(
            "+00000000000", user, q
        )
        return text

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
            "When your account is linked, you can type questions directly "
            "(e.g. What is RSI?, show my open positions).\n\n"
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
            f"Help: {settings.frontend_url.rstrip('/')}/help"
        )

    # ── Conversational onboarding step handlers ───────────────────────────────

    async def _onboarding_handle_step(
        self, phone: str, user: User, text: str, onb: dict
    ) -> str:
        """Route to the correct onboarding step handler."""
        from src.services.bot_onboarding_state import (
            STEP_AWAITING_AI_NAME,
            STEP_AWAITING_TRADER_CLASS,
        )

        step = onb["step"]
        if step == STEP_AWAITING_AI_NAME:
            return await self._onboarding_set_name(phone, user, text)
        if step == STEP_AWAITING_TRADER_CLASS:
            return await self._onboarding_set_trader_class(phone, user, text)
        # Shouldn't reach here — clear stale state
        from src.services.bot_onboarding_state import clear_onboarding
        await clear_onboarding(phone)
        return "Setup complete! Send HELP to see what I can do."

    async def _onboarding_set_name(
        self, phone: str, user: User, text: str
    ) -> str:
        """Handle the user's AI name choice."""
        from src.services.bot_onboarding_state import (
            STEP_AWAITING_TRADER_CLASS,
            set_onboarding_step,
        )

        name = text.strip()

        # Let them skip / bail out
        if name.lower() in ("skip", "cancel"):
            from src.services.bot_onboarding_state import clear_onboarding
            await clear_onboarding(phone)
            return "No problem! You can name your AI later in Settings.\n\nSend HELP to see commands."

        if not 2 <= len(name) <= 20:
            return "Name must be 2-20 characters. Try again:"

        if not name.replace(" ", "").isalpha():
            return "Name can only contain letters (and spaces). Try again:"

        # Persist to User + UserSettings
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select, update as sa_update
            from models import UserSettings

            await db.execute(
                sa_update(User).where(User.id == user.id).values(ai_name=name)
            )

            us = (await db.execute(
                sa_select(UserSettings).where(UserSettings.user_id == user.id)
            )).scalar_one_or_none()
            if us:
                await db.execute(
                    sa_update(UserSettings)
                    .where(UserSettings.user_id == user.id)
                    .values(ai_name=name)
                )
            else:
                db.add(UserSettings(user_id=user.id, ai_name=name))
                await db.flush()
            await db.commit()

        # Generate first chat message
        try:
            from src.agents.core.conversation_agent import ConversationAgent
            from src.agents.shared_memory import SharedMemory
            from src.services.context_detection import GENERAL
            from src.services.conversation_memory import save_conversation

            SharedMemory.invalidate(user.id)
            async with AsyncSessionLocal() as db:
                sc = await SharedMemory.load(user.id, db)
                agent = ConversationAgent(user.id)
                first_msg = await agent.generate_first_message(sc)
                await save_conversation(
                    user_id=user.id,
                    message="You named your AI companion.",
                    response=first_msg,
                    context=GENERAL,
                    sentiment="neutral",
                    db=db,
                )
                await db.commit()
        except Exception as exc:
            logger.warning("Onboarding first message failed for %s: %s", user.id, exc)

        # Advance to trader class step
        await set_onboarding_step(phone, STEP_AWAITING_TRADER_CLASS)
        return (
            f"Nice to meet you! *{name}* is locked in. 🎯\n\n"
            "Now, which best describes your trading experience?\n\n"
            "1️⃣ Complete novice — never traded\n"
            "2️⃣ Curious saver — interested but cautious\n"
            "3️⃣ Self-taught — done some research\n"
            "4️⃣ Experienced — active trader\n"
            "5️⃣ Crypto native — DeFi / on-chain\n\n"
            "Reply with a number (1-5):"
        )

    async def _onboarding_set_trader_class(
        self, phone: str, user: User, text: str
    ) -> str:
        """Handle the user's trader class selection."""
        from src.services.bot_onboarding_state import (
            clear_onboarding,
            parse_trader_class_choice,
        )

        choice = parse_trader_class_choice(text)
        if not choice:
            return (
                "I didn't catch that. Reply with a number 1-5:\n\n"
                "1️⃣ Complete novice\n"
                "2️⃣ Curious saver\n"
                "3️⃣ Self-taught\n"
                "4️⃣ Experienced\n"
                "5️⃣ Crypto native"
            )

        # Persist trader class
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select, update as sa_update
            from models import UserSettings

            us = (await db.execute(
                sa_select(UserSettings).where(UserSettings.user_id == user.id)
            )).scalar_one_or_none()
            if us:
                await db.execute(
                    sa_update(UserSettings)
                    .where(UserSettings.user_id == user.id)
                    .values(
                        trader_class=choice,
                        class_detected_at=_now(),
                        class_detection_method="whatsapp_onboarding",
                        onboarding_complete=True,
                    )
                )
            else:
                db.add(UserSettings(
                    user_id=user.id,
                    trader_class=choice,
                    class_detected_at=_now(),
                    class_detection_method="whatsapp_onboarding",
                    onboarding_complete=True,
                ))
                await db.flush()
            await db.commit()

        # Clear onboarding state
        await clear_onboarding(phone)

        # Tailor response by experience level
        _LABEL = {
            "complete_novice": "Complete novice",
            "curious_saver": "Curious saver",
            "self_taught": "Self-taught researcher",
            "experienced": "Experienced trader",
            "crypto_native": "Crypto native",
        }
        label = _LABEL.get(choice, choice)

        # Include web CTA for provisional (chat-only) users
        from src.services.provisional_user import is_provisional

        web_hint = ""
        if is_provisional(user):
            web_hint = (
                f"\n\n🌐 Want the full web dashboard + live trading?\n"
                f"Tap: {settings.frontend_url}/register"
            )

        return (
            f"Got it — *{label}*. Your AI will adapt its style and risk levels accordingly.\n\n"
            "✅ Setup complete! Here's what you can do:\n\n"
            "💬 Just type naturally — ask questions, get analysis\n"
            "📊 PORTFOLIO — see open positions\n"
            f"⚙️ Settings: {settings.frontend_url}/settings\n\n"
            "To connect an exchange for live trading, visit:\n"
            f"{settings.frontend_url}/settings/exchange"
            f"{web_hint}\n\n"
            "Or just ask me anything to get started! 🚀"
        )

    # ── Outbound: trade alert ─────────────────────────────────────────────────

    async def send_trade_alert(
        self,
        whatsapp_number: str,
        user_id: str,
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
        from src.services.user_ai_name import get_user_ai_name

        async with AsyncSessionLocal() as db:
            ai_name = await get_user_ai_name(str(user_id), db)
        em   = "📈" if side == "BUY" else "📉"
        text = _trunc(
            f"✅ {ai_name} executed a trade\n\n"
            f"{em} {side} {symbol}\n"
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
