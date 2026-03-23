"""
src/agents/goal_tracking_agent.py — Goal tracking and weekly progress reporting.

Generates personalized weekly progress reports:
- Calculates performance metrics (win rate, P&L, portfolio change)
- Uses class-aware Claude prompts (novice, pro, crypto)
- Sends reports via in-app notification and Telegram
- Scheduled for Mondays 8am UTC via APScheduler
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from anthropic import Anthropic
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import BotMessage, Trade, User, UserExternalAccount
from src.agents.shared_memory import SharedContext, SharedMemory

logger = logging.getLogger(__name__)


class GoalTrackingAgent:
    """Generates personalized weekly progress reports and sends via notification + Telegram."""

    def __init__(self):
        self.claude_client = Anthropic()

    async def generate_progress_report(self, user_id: str, db: AsyncSession) -> dict:
        """Generate a weekly progress report for a user.

        Args:
            user_id: User ID to generate report for
            db: Database session

        Returns:
            dict with keys:
            - message: str — The generated progress summary
            - pct_change: float — Portfolio percentage change
            - win_rate: float — Win rate percentage (0-100)
            - on_track: bool — True if pct_change >= 0
            - trader_class: str — Trader class used for prompt selection
        """
        ctx = await SharedMemory.load(user_id, db)
        trades = await self._get_closed_trades(user_id, db)

        # ─────────────────────────────────────────────────────────────────────────
        # Empty case: no trades yet
        # ─────────────────────────────────────────────────────────────────────────
        if not trades:
            empty_msg = {
                "complete_novice": (
                    "No trades yet - Unitrader is watching the market for you in practice mode."
                ),
                "curious_saver": "No trades yet - Unitrader is getting ready. Check back soon.",
                "self_taught": "No closed trades yet. Unitrader is building your strategy.",
                "experienced": "No closed positions. Unitrader is monitoring open positions.",
                "semi_institutional": "No closed positions this period.",
                "crypto_native": "No trades yet - Unitrader is watching the crypto market.",
            }
            return {
                "message": empty_msg.get(ctx.trader_class, "No trades yet."),
                "on_track": True,
            }

        # ─────────────────────────────────────────────────────────────────────────
        # Calculate metrics
        # ─────────────────────────────────────────────────────────────────────────
        total_pnl = sum(float(t.pnl or 0) for t in trades)
        start_amt = float(ctx.max_trade_amount) * 10
        pct_change = (total_pnl / start_amt * 100) if start_amt > 0 else 0
        win_count = len([t for t in trades if float(t.pnl or 0) > 0])
        win_rate = (win_count / len(trades) * 100) if trades else 0

        # ─────────────────────────────────────────────────────────────────────────
        # Build class-aware prompt
        # ─────────────────────────────────────────────────────────────────────────
        if ctx.is_pro():
            prompt = (
                f"You are Unitrader. Write a concise 3-sentence performance analysis.\n"
                f"Trader class: {ctx.trader_class}. Goal: {ctx.goal}.\n"
                f"Stats: {len(trades)} trades, {pct_change:+.1f}% change, {win_rate:.0f}% win rate.\n"
                f"Include win rate vs typical retail benchmark (40%), and one strategy adjustment.\n"
                f"Be direct and technical."
            )
        elif ctx.is_crypto_native():
            prompt = (
                f"You are Unitrader. Write a 3-sentence crypto portfolio update.\n"
                f"Stats: {len(trades)} trades, {pct_change:+.1f}% change, {win_rate:.0f}% win rate.\n"
                f"Reference market cycle context if relevant. End with one actionable insight."
            )
        else:
            # Novice, curious saver, self-taught
            goal_text = {
                "grow_savings": "grow your savings steadily",
                "generate_income": "generate regular income",
                "learn_trading": "learn how markets work",
                "crypto_focus": "capitalise on crypto opportunities",
            }.get(ctx.goal, "achieve your financial goals")

            prompt = (
                f"You are Unitrader, a warm and friendly AI trading companion.\n"
                f"Write a 3-sentence weekly update for someone who wants to {goal_text}.\n"
                f"Stats: {len(trades)} trades, {pct_change:+.1f}% portfolio change, "
                f"{win_rate:.0f}% success rate.\n"
                f"Use simple language - no financial jargon. Be encouraging but honest.\n"
                f"End with one concrete tip they can act on."
            )

        # ─────────────────────────────────────────────────────────────────────────
        # Call Claude for summary
        # ─────────────────────────────────────────────────────────────────────────
        try:
            resp = await asyncio.to_thread(
                lambda: self.claude_client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=220,
                    messages=[{"role": "user", "content": prompt}],
                )
            )
            summary = resp.content[0].text.strip()
        except Exception as e:
            logger.error("Claude API error generating progress report: %s", e)
            summary = (
                f"Weekly update: {len(trades)} trades, "
                f"{pct_change:+.1f}% portfolio change, {win_rate:.0f}% win rate."
            )

        # ─────────────────────────────────────────────────────────────────────────
        # Send notifications (async fire-and-forget)
        # ─────────────────────────────────────────────────────────────────────────
        try:
            await self._create_notification(user_id, "weekly_goal_update", summary, db)
            await self._send_telegram(user_id, summary, db)
        except Exception as e:
            logger.error("Error sending notifications for user %s: %s", user_id, e)

        return {
            "message": summary,
            "pct_change": pct_change,
            "win_rate": win_rate,
            "on_track": pct_change >= 0,
            "trader_class": ctx.trader_class,
        }

    async def _get_closed_trades(self, user_id: str, db: AsyncSession) -> list:
        """Get all closed trades for a user (closed in the past week)."""
        try:
            result = await db.execute(
                select(Trade).where(
                    and_(
                        Trade.user_id == user_id,
                        Trade.status.in_(["closed", "completed"]),
                    )
                )
            )
            return result.scalars().all()
        except Exception as e:
            logger.error("Error fetching closed trades for user %s: %s", user_id, e)
            return []

    async def _create_notification(
        self, user_id: str, notification_type: str, message: str, db: AsyncSession
    ) -> None:
        """Store notification in BotMessage table as alert."""
        try:
            bot_msg = BotMessage(
                user_id=user_id,
                platform="web",  # In-app notification
                external_user_id=user_id,
                message_type="alert",
                command=notification_type,
                user_message=None,
                bot_response=message,
                status="sent",
            )
            db.add(bot_msg)
            await db.commit()
            logger.info("Notification created for user %s: %s", user_id, notification_type)
        except Exception as e:
            logger.error("Error creating notification for user %s: %s", user_id, e)

    async def _send_telegram(self, user_id: str, message: str, db: AsyncSession) -> None:
        """Send message to user's linked Telegram account if available."""
        try:
            # Get user's Telegram account
            result = await db.execute(
                select(UserExternalAccount).where(
                    and_(
                        UserExternalAccount.user_id == user_id,
                        UserExternalAccount.platform == "telegram",
                        UserExternalAccount.is_linked == True,  # noqa: E712
                    )
                )
            )
            ext_account = result.scalar_one_or_none()

            if not ext_account:
                logger.debug("No linked Telegram account for user %s", user_id)
                return

            # Send message via telegram bot
            try:
                from routers.telegram_webhooks import get_telegram_bot_service

                bot_service = get_telegram_bot_service()
                if not bot_service or not bot_service.app:
                    logger.warning("Telegram bot service not initialized")
                    return

                tg_chat_id = int(ext_account.external_id)
                await bot_service.app.bot.send_message(
                    chat_id=tg_chat_id,
                    text=f"📈 *Your Unitrader Weekly Report*\n\n{message}",
                    parse_mode="Markdown",
                )
                logger.info("Telegram message sent to user %s", user_id)
            except ValueError:
                logger.warning(
                    "Invalid Telegram ID for user %s: %s",
                    user_id,
                    ext_account.external_id,
                )
            except Exception as e:
                logger.error("Error sending Telegram message to user %s: %s", user_id, e)

        except Exception as e:
            logger.error("Error fetching Telegram account for user %s: %s", user_id, e)
