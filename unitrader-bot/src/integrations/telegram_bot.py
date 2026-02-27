"""
src/integrations/telegram_bot.py — Telegram bot service for Unitrader.

Handles the full lifecycle of bot updates via a webhook:
  - Account linking (web-initiated and bot-initiated via 6-digit OTP)
  - Portfolio, trade history, and performance queries (direct DB)
  - Trade execution and close (calls TradingAgent directly — no HTTP round-trip)
  - AI chat via ConversationAgent
  - Outbound trade alerts pushed from the backend

Commands:
  /start       — Welcome, show link status
  /link CODE   — Link Telegram to an existing Unitrader account via 6-digit OTP
  /portfolio   — Open positions
  /trade BUY BTC 1.5 — Execute a trade
  /close BTCUSDT — Close a position
  /history     — Last 10 closed trades
  /performance — Win rate, profit stats
  /chat <text> — Ask the AI anything
  /alerts      — Placeholder for price alerts
  /settings    — Deep-link to web settings
  /unlink      — Disconnect this Telegram account
  /help        — Command reference
"""

import logging
import random
import string
import time
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import settings
from database import AsyncSessionLocal
from models import (
    BotMessage,
    TelegramLinkingCode,
    Trade,
    User,
    UserExternalAccount,
)

logger = logging.getLogger(__name__)

_PLATFORM = "telegram"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_code(length: int = 6) -> str:
    """Generate a numeric OTP code for account linking."""
    return "".join(random.choices(string.digits, k=length))


def _chunk(text: str, size: int = 4096) -> list[str]:
    """Split text into Telegram-safe chunks (max 4096 chars)."""
    return [text[i : i + size] for i in range(0, len(text), size)]


# ─────────────────────────────────────────────────────────────────────────────
# TelegramBotService
# ─────────────────────────────────────────────────────────────────────────────

class TelegramBotService:
    """Async Telegram bot service — one instance, registered as a singleton in main.py."""

    def __init__(self, token: str):
        self.token = token
        self.app: Application | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Build the Application and register all handlers."""
        self.app = (
            ApplicationBuilder()
            .token(self.token)
            .build()
        )

        handlers: list[tuple] = [
            ("start",       self.cmd_start),
            ("link",        self.cmd_link),
            ("portfolio",   self.cmd_portfolio),
            ("trade",       self.cmd_trade),
            ("close",       self.cmd_close),
            ("history",     self.cmd_history),
            ("performance", self.cmd_performance),
            ("chat",        self.cmd_chat),
            ("alerts",      self.cmd_alerts),
            ("settings",    self.cmd_settings),
            ("unlink",      self.cmd_unlink),
            ("help",        self.cmd_help),
        ]
        for name, handler in handlers:
            self.app.add_handler(CommandHandler(name, handler))

        # Inline keyboard callbacks (e.g. confirm unlink)
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))

        # Catch-all text messages (non-commands)
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        await self.app.initialize()
        logger.info("Telegram bot initialised — %d handlers registered", len(handlers))

    async def set_webhook(self, url: str) -> None:
        """Register the webhook URL with Telegram."""
        await self.app.bot.set_webhook(url=url, allowed_updates=["message", "callback_query"])
        logger.info("Telegram webhook set: %s", url)

    async def delete_webhook(self) -> None:
        await self.app.bot.delete_webhook()
        logger.info("Telegram webhook deleted")

    async def process_update(self, update: Update) -> None:
        """Feed one incoming update into the application's handler pipeline."""
        await self.app.process_update(update)

    # ── /start ────────────────────────────────────────────────────────────────

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tg_id = str(update.effective_user.id)
        tg_name = update.effective_user.username or update.effective_user.first_name or "Trader"
        t0 = time.perf_counter()

        user = await self._get_linked_user(tg_id)

        if user:
            text = (
                f"👋 Welcome back, *{tg_name}*!\n\n"
                f"Your AI trading companion *{user.ai_name}* is ready.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "📊 `/portfolio` — open positions\n"
                "📈 `/trade BUY BTCUSDT 1.5` — execute trade\n"
                "❌ `/close BTCUSDT` — close position\n"
                "📜 `/history` — last 10 trades\n"
                "🏆 `/performance` — your stats\n"
                "💬 `/chat <question>` — ask your AI\n"
                "⚙️ `/settings` — manage settings\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Type /help for the full command list."
            )
        else:
            frontend = settings.frontend_url
            text = (
                f"👋 Welcome to *Unitrader Bot*, {tg_name}!\n\n"
                "To start trading, link this Telegram account to your Unitrader profile.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "📱 *Option 1 — Web-initiated (recommended)*\n"
                f"1. Log in at {frontend}\n"
                "2. Go to Settings → Connected Accounts → Link Telegram\n"
                "3. You'll receive a 6-digit code\n"
                "4. Send me: `/link 123456`\n\n"
                "📝 *Option 2 — Bot-initiated*\n"
                "1. Send me `/link` (no code)\n"
                "2. I'll generate a code for you\n"
                f"3. Enter it at {frontend}/link-telegram\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Need help? Visit unitrader.com/help"
            )

        ms = int((time.perf_counter() - t0) * 1000)
        await self._reply(update, text, parse_mode="Markdown")
        await self._log(tg_id, "command", "/start", "/start", text, "success",
                        user_id=user.id if user else None, response_time_ms=ms)

    # ── /link ────────────────────────────────────────────────────────────────

    async def cmd_link(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Two modes:
          /link CODE  → user supplies code generated on the website (web-initiated)
          /link       → bot generates a code; user enters it on the website (bot-initiated)
        """
        tg_id   = str(update.effective_user.id)
        tg_name = update.effective_user.username or update.effective_user.first_name or "Trader"

        # Guard: already linked?
        if await self._get_linked_user(tg_id):
            await self._reply(
                update,
                "✅ Your Telegram is already linked to a Unitrader account.\n"
                "Use /unlink first if you want to connect a different account.",
            )
            return

        args = ctx.args or []

        # ── Mode A: User provides the code ────────────────────────────────────
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
                    await self._reply(
                        update,
                        "❌ Invalid or expired code.\n\n"
                        "Codes expire after 15 minutes. "
                        "Please generate a new one at the Unitrader website.",
                    )
                    return

                # For web-initiated: user_id is already on the row
                user_id = row.user_id

                # For bot-initiated: user_id is null — store the Telegram ID so
                # the website can complete the link when the user enters the code there
                if not user_id:
                    row.telegram_user_id = tg_id
                    row.telegram_username = tg_name
                    await db.commit()
                    await self._reply(
                        update,
                        f"⏳ Code registered!\n\n"
                        f"Now go to {settings.frontend_url}/link-telegram and enter:\n\n"
                        f"🔑 *{code}*\n\n"
                        "The link will complete automatically.",
                        parse_mode="Markdown",
                    )
                    return

                # Mark code as used
                row.is_used  = True
                row.used_at  = _now()

                # Create the external account record
                ext = UserExternalAccount(
                    user_id=user_id,
                    platform=_PLATFORM,
                    external_id=tg_id,
                    external_username=tg_name,
                    is_linked=True,
                    settings={"notifications": True, "trade_alerts": True},
                )
                db.add(ext)
                await db.commit()

                # Fetch the user name for the welcome message
                user = (await db.execute(
                    sa_select(User).where(User.id == user_id)
                )).scalar_one_or_none()
                ai_name = user.ai_name if user else "your AI"

            await self._reply(
                update,
                f"🎉 *Linked successfully!*\n\n"
                f"Your Telegram is now connected to your Unitrader account.\n"
                f"Your AI companion *{ai_name}* is ready to trade.\n\n"
                "Type /help to see available commands.",
                parse_mode="Markdown",
            )
            await self._log(tg_id, "command", "/link", f"/link {code}",
                            "Account linked", "success", user_id=user_id)
            return

        # ── Mode B: Bot generates a code ──────────────────────────────────────
        code = _generate_code()
        expires = _now() + timedelta(minutes=15)

        async with AsyncSessionLocal() as db:
            new_row = TelegramLinkingCode(
                code=code,
                user_id=None,
                telegram_user_id=tg_id,
                telegram_username=tg_name,
                expires_at=expires,
            )
            db.add(new_row)
            await db.commit()

        text = (
            f"🔑 Your linking code is:\n\n"
            f"*{code}*\n\n"
            f"1. Go to {settings.frontend_url}/link-telegram\n"
            f"2. Log in and enter the code above\n"
            f"3. Your accounts will be linked automatically\n\n"
            f"⏱️ Code expires in 15 minutes."
        )
        await self._reply(update, text, parse_mode="Markdown")
        await self._log(tg_id, "command", "/link", "/link", text, "success")

    # ── /portfolio ────────────────────────────────────────────────────────────

    async def cmd_portfolio(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tg_id = str(update.effective_user.id)
        t0 = time.perf_counter()

        user = await self._require_linked(update, tg_id)
        if not user:
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select
            trades = (await db.execute(
                sa_select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.status == "open",
                ).order_by(Trade.created_at.desc())
            )).scalars().all()

        if not trades:
            text = (
                "📊 *No open positions*\n\n"
                "Start trading with:\n`/trade BUY BTCUSDT 1.5`"
            )
        else:
            lines = ["📊 *Open Positions*\n"]
            total_pnl = 0.0
            for t in trades:
                pnl = (t.profit or 0) - (t.loss or 0)
                pct = t.profit_percent or 0
                em  = "📈" if pnl >= 0 else "📉"
                total_pnl += pnl
                lines.append(
                    f"{em} *{t.symbol}* — {t.side}\n"
                    f"  Entry: `${t.entry_price:,.4f}`\n"
                    f"  SL: `${t.stop_loss:,.4f}`  TP: `${t.take_profit:,.4f}`\n"
                    f"  P&L: `${pnl:+,.2f}` ({pct:+.2f}%)\n"
                    f"  Size: `{t.quantity}`\n"
                )
            pnl_em = "💰" if total_pnl >= 0 else "🔻"
            lines.append(f"{pnl_em} *Total unrealised P&L: ${total_pnl:+,.2f}*")
            text = "\n".join(lines)

        ms = int((time.perf_counter() - t0) * 1000)
        await self._reply(update, text, parse_mode="Markdown")
        await self._log(tg_id, "command", "/portfolio", "/portfolio", text,
                        "success", user_id=user.id, response_time_ms=ms)

    # ── /trade ────────────────────────────────────────────────────────────────

    async def cmd_trade(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Usage: /trade BUY BTCUSDT 1.5
               /trade SELL ETHUSDT 0.5
        """
        tg_id   = str(update.effective_user.id)
        raw_msg = update.message.text or ""
        t0      = time.perf_counter()

        user = await self._require_linked(update, tg_id)
        if not user:
            return

        args = ctx.args or []
        if len(args) < 3:
            await self._reply(
                update,
                "❌ *Invalid format*\n\n"
                "Usage: `/trade BUY BTCUSDT 1.5`\n\n"
                "• Side: `BUY` or `SELL`\n"
                "• Symbol: `BTCUSDT`, `ETHUSDT`, etc.\n"
                "• Size: `0.1` – `2.0` (% of account balance)",
                parse_mode="Markdown",
            )
            return

        side   = args[0].upper()
        symbol = args[1].upper()
        try:
            size = float(args[2])
        except ValueError:
            await self._reply(update, "❌ Position size must be a number (e.g. `1.5`).",
                              parse_mode="Markdown")
            return

        if side not in ("BUY", "SELL"):
            await self._reply(update, "❌ Side must be `BUY` or `SELL`.", parse_mode="Markdown")
            return
        if not (0.1 <= size <= 2.0):
            await self._reply(update, "❌ Position size must be between `0.1` and `2.0`%.",
                              parse_mode="Markdown")
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            # Determine exchange from user's API keys
            exchange = await self._get_primary_exchange(user.id)
            if not exchange:
                await self._reply(
                    update,
                    "❌ No exchange API key configured.\n\n"
                    f"Add one at {settings.frontend_url}/settings/exchange",
                )
                return

            from src.agents.core.trading_agent import TradingAgent
            from src.integrations.market_data import full_market_analysis

            agent = TradingAgent(user_id=user.id)

            live_data  = await full_market_analysis(symbol, exchange)
            price      = live_data["price"]
            sl_dist    = price * 0.02         # 2% default stop
            tp_dist    = price * 0.04         # 4% default take-profit (2:1 R:R)
            stop_loss  = (price - sl_dist) if side == "BUY" else (price + sl_dist)
            take_profit = (price + tp_dist) if side == "BUY" else (price - tp_dist)

            decision = {
                "decision": side,
                "confidence": 70,
                "entry_price": price,
                "stop_loss":  round(stop_loss, 8),
                "take_profit": round(take_profit, 8),
                "position_size_pct": size,
                "reasoning": f"Manual trade via Telegram — {side} {symbol} at {size}%",
            }

            result = await agent.execute_trade(decision, symbol, exchange, user.ai_name)

            if result.get("status") == "executed":
                rr = round((take_profit - price) / (price - stop_loss), 2) if side == "BUY" \
                     else round((price - take_profit) / (stop_loss - price), 2)
                text = (
                    f"✅ *Trade Executed!*\n\n"
                    f"📊 {side} `{result.get('quantity', '')}` {symbol}\n"
                    f"💵 Entry: `${price:,.4f}`\n"
                    f"🛑 Stop Loss: `${stop_loss:,.4f}`\n"
                    f"🎯 Take Profit: `${take_profit:,.4f}`\n"
                    f"⚖️ R:R ≈ `1:{abs(rr):.1f}`\n\n"
                    f"Trade ID: `{result.get('trade_id', 'N/A')}`"
                )
                status_str = "success"
            else:
                reason = result.get("reason", "Unknown error")
                text = f"❌ Trade rejected: {reason}"
                status_str = "error"

        except Exception as exc:
            logger.error("cmd_trade error for user %s: %s", user.id, exc)
            text = f"❌ Error executing trade: {exc}"
            status_str = "error"

        ms = int((time.perf_counter() - t0) * 1000)
        await self._reply(update, text, parse_mode="Markdown")
        await self._log(tg_id, "trade", "/trade", raw_msg, text, status_str,
                        user_id=user.id, response_time_ms=ms)

    # ── /close ────────────────────────────────────────────────────────────────

    async def cmd_close(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Usage: /close BTCUSDT"""
        tg_id   = str(update.effective_user.id)
        raw_msg = update.message.text or ""
        t0      = time.perf_counter()

        user = await self._require_linked(update, tg_id)
        if not user:
            return

        args = ctx.args or []
        if not args:
            await self._reply(update, "❌ Usage: `/close BTCUSDT`", parse_mode="Markdown")
            return

        symbol = args[0].upper()
        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            from sqlalchemy import select as sa_select
            from src.agents.core.trading_agent import TradingAgent

            async with AsyncSessionLocal() as db:
                trade = (await db.execute(
                    sa_select(Trade).where(
                        Trade.user_id == user.id,
                        Trade.symbol == symbol,
                        Trade.status == "open",
                    ).order_by(Trade.created_at.desc()).limit(1)
                )).scalar_one_or_none()

            if not trade:
                text = f"❌ No open position found for `{symbol}`."
                await self._reply(update, text, parse_mode="Markdown")
                return

            agent  = TradingAgent(user_id=user.id)
            result = await agent.close_position(trade.id)

            if result.get("status") == "closed":
                pnl     = result.get("profit", 0) - result.get("loss", 0)
                pnl_pct = result.get("profit_percent", 0)
                em = "🎉" if pnl >= 0 else "📉"
                text = (
                    f"✅ *Position Closed!*\n\n"
                    f"📊 {symbol}\n"
                    f"💵 Entry: `${trade.entry_price:,.4f}`\n"
                    f"💵 Exit: `${result.get('exit_price', 0):,.4f}`\n"
                    f"{em} P&L: `${pnl:+,.2f}` ({pnl_pct:+.2f}%)\n"
                )
                status_str = "success"
            else:
                text = f"❌ Could not close: {result.get('reason', 'Unknown')}"
                status_str = "error"

        except Exception as exc:
            logger.error("cmd_close error for user %s: %s", user.id, exc)
            text = f"❌ Error closing position: {exc}"
            status_str = "error"

        ms = int((time.perf_counter() - t0) * 1000)
        await self._reply(update, text, parse_mode="Markdown")
        await self._log(tg_id, "trade", "/close", raw_msg, text, status_str,
                        user_id=user.id, response_time_ms=ms)

    # ── /history ──────────────────────────────────────────────────────────────

    async def cmd_history(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tg_id = str(update.effective_user.id)
        t0    = time.perf_counter()

        user = await self._require_linked(update, tg_id)
        if not user:
            return

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select
            trades = (await db.execute(
                sa_select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.status == "closed",
                ).order_by(Trade.closed_at.desc()).limit(10)
            )).scalars().all()

        if not trades:
            text = "📊 *No closed trades yet.*\n\nStart with `/trade BUY BTCUSDT 1.5`"
        else:
            lines = ["📜 *Last 10 Trades*\n"]
            for i, t in enumerate(trades, 1):
                pnl = (t.profit or 0) - (t.loss or 0)
                pct = t.profit_percent or 0
                em  = "✅" if pnl >= 0 else "❌"
                when = t.closed_at.strftime("%b %d %H:%M") if t.closed_at else "—"
                lines.append(
                    f"{i}. {em} *{t.symbol}* {t.side}  "
                    f"`${pnl:+,.2f}` ({pct:+.2f}%)  _{when}_"
                )
            text = "\n".join(lines)

        ms = int((time.perf_counter() - t0) * 1000)
        await self._reply(update, text, parse_mode="Markdown")
        await self._log(tg_id, "command", "/history", "/history", text,
                        "success", user_id=user.id, response_time_ms=ms)

    # ── /performance ──────────────────────────────────────────────────────────

    async def cmd_performance(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tg_id = str(update.effective_user.id)
        t0    = time.perf_counter()

        user = await self._require_linked(update, tg_id)
        if not user:
            return

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sa_select
            trades = (await db.execute(
                sa_select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.status == "closed",
                )
            )).scalars().all()

        if not trades:
            text = "📈 *No closed trades yet.*\n\nYour stats will appear here after your first trade."
        else:
            profits = [(t.profit or 0) - (t.loss or 0) for t in trades]
            wins    = [p for p in profits if p > 0]
            total   = sum(profits)
            wr      = len(wins) / len(profits) * 100
            best    = max(profits)
            worst   = min(profits)
            avg     = total / len(profits)
            streak  = _winning_streak(profits)
            wr_em   = "🔥" if wr >= 60 else ("⚠️" if wr < 40 else "📊")
            text = (
                f"📈 *{user.ai_name}'s Performance*\n\n"
                f"{wr_em} Win Rate:        `{wr:.1f}%`\n"
                f"💰 Total Profit:    `${total:+,.2f}`\n"
                f"📊 Total Trades:    `{len(profits)}`\n"
                f"🏆 Best Trade:      `+${best:,.2f}`\n"
                f"📉 Worst Trade:     `${worst:,.2f}`\n"
                f"📅 Avg per Trade:   `${avg:+,.2f}`\n"
                f"🔁 Best Win Streak: `{streak}`"
            )

        ms = int((time.perf_counter() - t0) * 1000)
        await self._reply(update, text, parse_mode="Markdown")
        await self._log(tg_id, "command", "/performance", "/performance", text,
                        "success", user_id=user.id, response_time_ms=ms)

    # ── /chat ─────────────────────────────────────────────────────────────────

    async def cmd_chat(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tg_id   = str(update.effective_user.id)
        raw_msg = update.message.text or ""
        t0      = time.perf_counter()

        user = await self._require_linked(update, tg_id)
        if not user:
            return

        question = " ".join(ctx.args or []).strip()
        if not question:
            await self._reply(
                update,
                "💬 Usage: `/chat Should I buy Bitcoin now?`\n\n"
                "Ask your AI anything about trading!",
                parse_mode="Markdown",
            )
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            from src.agents.core.conversation_agent import ConversationAgent
            agent    = ConversationAgent(user_id=user.id)
            response = await agent.respond(question)
            text     = response.get("response", "Sorry, I couldn't generate a response.")
            status_str = "success"
        except Exception as exc:
            logger.error("cmd_chat error for user %s: %s", user.id, exc)
            text = "❌ Could not get an AI response right now. Try again in a moment."
            status_str = "error"

        ms = int((time.perf_counter() - t0) * 1000)
        # Split if over Telegram's 4096-char limit
        for chunk in _chunk(text):
            await self._reply(update, chunk)
        await self._log(tg_id, "message", "/chat", question, text, status_str,
                        user_id=user.id, response_time_ms=ms)

    # ── /alerts ───────────────────────────────────────────────────────────────

    async def cmd_alerts(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tg_id = str(update.effective_user.id)
        user  = await self._require_linked(update, tg_id)
        if not user:
            return
        text = (
            "🔔 *Price Alerts* — Coming Soon!\n\n"
            "You'll be able to set alerts like:\n"
            "`/alerts set BTCUSDT 70000`\n\n"
            "Stay tuned for updates."
        )
        await self._reply(update, text, parse_mode="Markdown")
        await self._log(tg_id, "command", "/alerts", "/alerts", text, "success", user_id=user.id)

    # ── /settings ─────────────────────────────────────────────────────────────

    async def cmd_settings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tg_id = str(update.effective_user.id)
        user  = await self._require_linked(update, tg_id)
        if not user:
            return
        text = (
            f"⚙️ *Trading Settings*\n\n"
            f"Manage your settings at:\n{settings.frontend_url}/settings\n\n"
            "You can update:\n"
            "• Max position size\n"
            "• Daily loss limit\n"
            "• Trading hours (UTC)\n"
            "• Approved assets\n"
            "• Notification preferences"
        )
        await self._reply(update, text, parse_mode="Markdown")
        await self._log(tg_id, "command", "/settings", "/settings", text, "success", user_id=user.id)

    # ── /unlink ───────────────────────────────────────────────────────────────

    async def cmd_unlink(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tg_id = str(update.effective_user.id)

        user = await self._get_linked_user(tg_id)
        if not user:
            await self._reply(update, "ℹ️ No linked account found.")
            return

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, unlink", callback_data=f"unlink_confirm:{tg_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="unlink_cancel"),
        ]])
        await update.message.reply_text(
            "⚠️ Are you sure you want to disconnect this Telegram account from Unitrader?\n\n"
            "You can re-link at any time using `/link`.",
            reply_markup=keyboard,
        )

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline keyboard button presses."""
        query = update.callback_query
        await query.answer()
        data  = query.data or ""
        tg_id = str(query.from_user.id)

        if data.startswith("unlink_confirm:"):
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select as sa_select
                ext = (await db.execute(
                    sa_select(UserExternalAccount).where(
                        UserExternalAccount.external_id == tg_id,
                        UserExternalAccount.platform == _PLATFORM,
                    )
                )).scalar_one_or_none()
                if ext:
                    await db.delete(ext)
                    await db.commit()

            await query.edit_message_text(
                "✅ Unlinked!\n\n"
                "Your Telegram account has been disconnected from Unitrader.\n"
                "Use /start to link again at any time."
            )
            await self._log(tg_id, "command", "/unlink", "unlink_confirm",
                            "Unlinked", "success")

        elif data == "unlink_cancel":
            await query.edit_message_text("👍 Cancelled — your account remains linked.")

    # ── /help ─────────────────────────────────────────────────────────────────

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        text = (
            "🤖 *Unitrader Bot — Command Reference*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 *Trading*\n"
            "`/portfolio` — open positions\n"
            "`/trade BUY BTCUSDT 1.5` — execute trade\n"
            "`/close BTCUSDT` — close a position\n"
            "`/history` — last 10 closed trades\n"
            "`/performance` — win rate & stats\n\n"
            "💬 *AI*\n"
            "`/chat <question>` — ask your AI anything\n\n"
            "🔧 *Settings & Alerts*\n"
            "`/settings` — manage trading settings\n"
            "`/alerts` — price alert setup\n\n"
            "🔗 *Account*\n"
            "`/start` — show account status\n"
            "`/link CODE` — link to Unitrader\n"
            "`/unlink` — disconnect Telegram\n"
            "`/help` — this message\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📝 *Examples*\n"
            "`/trade BUY BTCUSDT 1.5`\n"
            "`/trade SELL ETHUSDT 0.5`\n"
            "`/close BTCUSDT`\n"
            "`/chat Should I buy Bitcoin now?`\n\n"
            "Help: unitrader.com/help"
        )
        await self._reply(update, text, parse_mode="Markdown")

    # ── Free-text message handler ─────────────────────────────────────────────

    async def handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tg_id = str(update.effective_user.id)
        user  = await self._get_linked_user(tg_id)

        if user:
            # Linked users: treat free-text as a chat message
            ctx.args = update.message.text.split()
            await self.cmd_chat(update, ctx)
        else:
            await self._reply(
                update,
                "👋 Use /start to link your Unitrader account and start trading.",
            )

    # ── Outbound: trade alert ─────────────────────────────────────────────────

    async def send_trade_alert(
        self,
        telegram_user_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        confidence: int,
        reasoning: str,
    ) -> bool:
        """Push a trade execution notification to a user's Telegram chat.

        Called by the trading loop after a trade is placed.
        Returns True if the message was sent successfully.
        """
        if not self.app:
            return False
        em = "📈" if side == "BUY" else "📉"
        text = (
            f"{em} *Trade Alert!*\n\n"
            f"📊 {side} `{symbol}`\n"
            f"💵 Entry: `${entry_price:,.4f}`\n"
            f"🛑 Stop Loss: `${stop_loss:,.4f}`\n"
            f"🎯 Take Profit: `${take_profit:,.4f}`\n"
            f"🧠 Confidence: `{confidence}%`\n\n"
            f"_{reasoning}_"
        )
        try:
            await self.app.bot.send_message(
                chat_id=telegram_user_id,
                text=text,
                parse_mode="Markdown",
            )
            return True
        except Exception as exc:
            logger.warning("Failed to send trade alert to %s: %s", telegram_user_id, exc)
            return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_linked_user(self, tg_id: str) -> User | None:
        """Return the Unitrader User linked to this Telegram ID, or None."""
        from sqlalchemy import select as sa_select
        async with AsyncSessionLocal() as db:
            ext = (await db.execute(
                sa_select(UserExternalAccount).where(
                    UserExternalAccount.external_id == tg_id,
                    UserExternalAccount.platform == _PLATFORM,
                    UserExternalAccount.is_linked == True,  # noqa: E712
                )
            )).scalar_one_or_none()
            if not ext:
                return None
            # Update last_used_at
            ext.last_used_at = _now()
            user = (await db.execute(
                sa_select(User).where(User.id == ext.user_id)
            )).scalar_one_or_none()
            await db.commit()
            return user if user and user.is_active else None

    async def _require_linked(self, update: Update, tg_id: str) -> User | None:
        """Return linked user or send an error message and return None."""
        user = await self._get_linked_user(tg_id)
        if not user:
            await self._reply(
                update,
                "❌ Your Telegram is not linked to Unitrader.\n\n"
                "Use /start to see linking instructions.",
            )
        return user

    async def _get_primary_exchange(self, user_id: str) -> str | None:
        """Return the name of the first active exchange API key for a user."""
        from sqlalchemy import select as sa_select
        from models import ExchangeAPIKey  # noqa: PLC0415 — lazy import avoids circular dep
        async with AsyncSessionLocal() as db:
            key = (await db.execute(
                sa_select(ExchangeAPIKey).where(
                    ExchangeAPIKey.user_id == user_id,
                    ExchangeAPIKey.is_active == True,  # noqa: E712
                ).limit(1)
            )).scalar_one_or_none()
        return key.exchange if key else None

    async def _reply(
        self, update: Update, text: str, parse_mode: str | None = None
    ) -> None:
        try:
            await update.message.reply_text(text, parse_mode=parse_mode)
        except Exception as exc:
            logger.error("Failed to send reply: %s", exc)

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
        """Persist one interaction to bot_messages — fire and forget."""
        try:
            async with AsyncSessionLocal() as db:
                db.add(BotMessage(
                    user_id=user_id,
                    platform=_PLATFORM,
                    external_user_id=external_user_id,
                    message_type=message_type,
                    command=command,
                    user_message=(user_message or "")[:4000],
                    bot_response=(bot_response or "")[:4000],
                    status=status,
                    error_message=error_message,
                    response_time_ms=response_time_ms,
                ))
                await db.commit()
        except Exception as exc:
            logger.warning("Failed to log bot message: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────────────

def _winning_streak(profits: list[float]) -> int:
    """Return the longest consecutive winning streak."""
    best = cur = 0
    for p in profits:
        if p > 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


