"""
src/services/unitrader_notifications.py — Unitrader outbound notification engine.

Persists notifications to the database first, then attempts delivery over any
linked channels without interrupting the calling trade or scheduler flow.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import ApexNotification, UserExternalAccount, UserSettings

logger = logging.getLogger(__name__)

_unitrader_notification_engine = None


def set_unitrader_notification_engine(service) -> None:
    global _unitrader_notification_engine
    _unitrader_notification_engine = service


def get_unitrader_notification_engine():
    return _unitrader_notification_engine


class UnitraderNotificationEngine:
    """Create and deliver Unitrader notifications across supported user channels."""

    def __init__(self, telegram_bot=None, whatsapp_bot=None, claude_client=None):
        self.telegram_bot = telegram_bot
        self.whatsapp_bot = whatsapp_bot
        self.claude_client = claude_client

    async def send_auto_trade_executed(
        self,
        user_id: str,
        trade: dict,
        convergence: dict,
        undo_token: str,
        db: AsyncSession,
    ) -> None:
        symbol = trade["symbol"]
        asset_name = trade.get("asset_name", symbol)
        side = str(trade["side"]).upper()
        amount = float(trade.get("amount", 0) or 0)
        price = float(trade.get("entry_price", 0) or 0)
        confidence = int(round(float(convergence.get("confidence", 0) or 0)))
        votes_for = convergence.get("votes_for", 0)
        reasoning = convergence.get("reasoning_simple", "") or ""
        stop_loss_pct = float(trade.get("stop_loss_pct", 2) or 2)
        take_profit_pct = float(trade.get("take_profit_pct", 5) or 5)

        side_word = "bought" if side == "BUY" else "sold"
        direction_arrow = "▲" if side == "BUY" else "▼"

        channel_msg = f"""{direction_arrow} Unitrader just {side_word} {asset_name}

Amount: £{amount:.2f} at £{price:.4f}
Confidence: {confidence}% ({votes_for}/7 signals agreed)

Why Unitrader acted:
{reasoning}

Protection:
  Stop-loss: -{stop_loss_pct}% (Unitrader auto-closes if price drops)
  Target: +{take_profit_pct}% (Unitrader takes profit here)

↩ Undo this trade (60 seconds):
{self._undo_url(undo_token)}

⏸ Pause Unitrader: /pause

⚠️ Not financial advice. Capital at risk."""

        push_title = f"{direction_arrow} Unitrader {side_word} {asset_name}"
        push_body = f"£{amount:.2f} · {confidence}% confidence · Tap to see details"

        await self._dispatch(
            user_id=user_id,
            notification_type="auto_trade_executed",
            title=push_title,
            body=push_body,
            channel_message=channel_msg,
            data={
                "trade_id": str(trade.get("id", "")),
                "symbol": symbol,
                "undo_token": undo_token,
                "deep_link": "unitrader://positions",
            },
            undo_token=undo_token,
            trade_id=str(trade.get("id", "")) or None,
            db=db,
        )

    async def send_apex_selects_ready(
        self,
        user_id: str,
        selected_signals: list,
        total_scanned: int,
        approve_token: str,
        db: AsyncSession,
    ) -> None:
        count = len(selected_signals)
        top = selected_signals[0] if selected_signals else {}
        top_name = top.get("asset_name", top.get("symbol", ""))
        top_conf = top.get("confidence", 0)
        top_signal = str(top.get("signal", "buy")).upper()
        threshold = top.get("threshold_used", 75)

        signal_lines = []
        for signal in selected_signals[:3]:
            signal_lines.append(
                f"  {str(signal.get('signal', 'buy')).upper()} "
                f"{signal.get('asset_name', signal.get('symbol', ''))} "
                f"— {signal.get('confidence', 0)}% confidence"
            )

        channel_msg = f"""Unitrader found {count} signal{'s' if count != 1 else ''} matching your criteria

Scanned: {total_scanned} assets
Your threshold: {threshold}%+

Selected:
{chr(10).join(signal_lines)}

To execute all {count} trade{'s' if count != 1 else ''}:
{self._approve_url(approve_token)}

Or open Unitrader to review and choose individually.

This offer expires in 30 minutes.
⚠️ Not financial advice. Capital at risk."""

        push_title = f"Unitrader found {count} signal{'s' if count != 1 else ''} for you"
        push_body = f"Best: {top_signal} {top_name} at {top_conf}%. Tap to approve."

        await self._dispatch(
            user_id=user_id,
            notification_type="apex_selects_ready",
            title=push_title,
            body=push_body,
            channel_message=channel_msg,
            data={
                "approve_token": approve_token,
                "signal_count": count,
                "deep_link": f"unitrader://trade?mode=apex_selects&token={approve_token}",
            },
            db=db,
        )

    async def send_apex_selects_executed(
        self,
        user_id: str,
        executed_trades: list,
        db: AsyncSession,
    ) -> None:
        count = len(executed_trades)
        lines = []
        for trade in executed_trades[:3]:
            asset_name = trade.get("asset_name", trade.get("symbol", ""))
            side = str(trade.get("side", "buy")).upper()
            amount = float(trade.get("amount", 0) or 0)
            lines.append(f"  {side} {asset_name} — £{amount:.2f}")

        channel_msg = f"""Unitrader executed {count} approved trade{'s' if count != 1 else ''}

Executed:
{chr(10).join(lines) if lines else '  No trades were included.'}

Open Unitrader to review the positions Unitrader is now monitoring.
⚠️ Not financial advice. Capital at risk."""

        await self._dispatch(
            user_id=user_id,
            notification_type="apex_selects_executed",
            title=f"Unitrader executed {count} approved trade{'s' if count != 1 else ''}",
            body="Your approved Unitrader Selects trades have been placed.",
            channel_message=channel_msg,
            data={
                "trade_count": count,
                "deep_link": "unitrader://positions",
            },
            db=db,
        )

    async def send_browse_morning_briefing(
        self,
        user_id: str,
        top_signals: list,
        total_scanned: int,
        trader_class: str,
        db: AsyncSession,
    ) -> None:
        count = len(top_signals)
        if count == 0:
            return

        top = top_signals[0]
        top_name = top.get("asset_name", top.get("symbol", ""))
        top_conf = top.get("confidence", 0)
        top_signal = str(top.get("signal", "buy")).upper()
        top_reason = top.get("reasoning_simple", "") or ""

        if trader_class in ("complete_novice", "curious_saver"):
            greeting = "Good morning! Unitrader has been watching the markets."
            cta = "Tap to see what Unitrader found and decide if you want to trade."
        elif trader_class == "crypto_native":
            greeting = "GM. Unitrader ran the overnight scan."
            cta = "Open Unitrader to browse and execute."
        else:
            greeting = f"Morning briefing — Unitrader scanned {total_scanned} assets."
            cta = "Open Unitrader to review and execute."

        signal_lines = []
        for signal in top_signals[:3]:
            arrow = "▲" if signal.get("signal") == "buy" else "▼"
            signal_lines.append(
                f"  {arrow} {signal.get('asset_name', signal.get('symbol', ''))} "
                f"— {str(signal.get('signal', 'buy')).upper()} {signal.get('confidence', 0)}%"
            )

        channel_msg = f"""{greeting}

Today's top signals ({count} found):
{chr(10).join(signal_lines)}

Best signal: {top_signal} {top_name}
Why: {top_reason}

Open Unitrader to trade:
{settings.frontend_url.rstrip('/')}/trade

{cta}

Remember: In Browse mode, Unitrader never trades without your tap.
⚠️ Not financial advice. Capital at risk."""

        push_title = f"Unitrader found {count} signal{'s' if count != 1 else ''} this morning"
        push_body = f"Best: {top_signal} {top_name} at {top_conf}% confidence"

        await self._dispatch(
            user_id=user_id,
            notification_type="browse_morning_briefing",
            title=push_title,
            body=push_body,
            channel_message=channel_msg,
            data={
                "signal_count": count,
                "deep_link": "unitrader://trade?mode=browse",
            },
            db=db,
        )

    async def send_stop_loss_triggered(
        self,
        user_id: str,
        trade: dict,
        close_price: float,
        loss_amount: float,
        loss_pct: float,
        db: AsyncSession,
    ) -> None:
        asset_name = trade.get("asset_name", trade.get("symbol", ""))
        entry = float(trade.get("entry_price", 0) or 0)

        channel_msg = f"""🛡️ Unitrader protected you — Stop-loss triggered

{asset_name} closed automatically
Entry: £{entry:.4f} → Close: £{close_price:.4f}
Loss: -£{abs(loss_amount):.2f} (-{abs(loss_pct):.1f}%)

Without the stop-loss, losses could have continued.
Unitrader closed the position to protect your capital.

Your remaining portfolio is unaffected.
⚠️ Not financial advice. Capital at risk."""

        await self._dispatch(
            user_id=user_id,
            notification_type="stop_loss_triggered",
            title=f"Stop-loss triggered — {asset_name} closed",
            body=f"Unitrader protected you. Loss: -£{abs(loss_amount):.2f}",
            channel_message=channel_msg,
            data={"trade_id": str(trade.get("id", ""))},
            trade_id=str(trade.get("id", "")) or None,
            db=db,
        )

    async def send_take_profit_triggered(
        self,
        user_id: str,
        trade: dict,
        close_price: float,
        profit_amount: float,
        profit_pct: float,
        db: AsyncSession,
    ) -> None:
        asset_name = trade.get("asset_name", trade.get("symbol", ""))
        exchange = trade.get("exchange", "exchange")

        channel_msg = f"""Unitrader took profit on {asset_name}

Profit: +£{profit_amount:.2f} (+{profit_pct:.1f}%)
Position closed at target price (£{close_price:.4f}).

This profit is now cash in your {exchange} account.

Open Unitrader to see your updated portfolio.
⚠️ Not financial advice. Capital at risk."""

        await self._dispatch(
            user_id=user_id,
            notification_type="take_profit_triggered",
            title=f"+£{profit_amount:.2f} — Unitrader hit the target on {asset_name}",
            body=f"+{profit_pct:.1f}% profit. Cash is in your account.",
            channel_message=channel_msg,
            data={"trade_id": str(trade.get("id", ""))},
            trade_id=str(trade.get("id", "")) or None,
            db=db,
        )

    async def send_daily_digest(
        self,
        user_id: str,
        digest: dict,
        db: AsyncSession,
    ) -> None:
        trades_today = digest.get("trades_today", 0)
        pnl_today = float(digest.get("pnl_today", 0) or 0)
        signals_skipped = digest.get("signals_skipped", 0)
        open_positions = digest.get("open_positions", 0)
        watchlist = digest.get("watchlist", []) or []

        pnl_arrow = "+" if pnl_today >= 0 else ""
        watchlist_str = ", ".join(watchlist[:5]) if watchlist else "your watchlist"

        channel_msg = f"""Good morning — Unitrader daily report

Yesterday:
  Trades: {trades_today}
  P&L: {pnl_arrow}£{pnl_today:.2f}
  Signals skipped: {signals_skipped} (below threshold)
  Open positions: {open_positions}

Today: Unitrader is watching {watchlist_str}
Next scan: in 30 minutes

Open Unitrader to review positions.
⏸ Pause Unitrader anytime: /pause
⚠️ Not financial advice. Capital at risk."""

        await self._dispatch(
            user_id=user_id,
            notification_type="daily_digest",
            title="Unitrader daily report",
            body=(
                f"{trades_today} trades · {pnl_arrow}£{pnl_today:.2f} P&L · "
                f"{open_positions} positions open"
            ),
            channel_message=channel_msg,
            data={"deep_link": "unitrader://performance"},
            db=db,
        )

    async def _dispatch(
        self,
        user_id: str,
        notification_type: str,
        title: str,
        body: str,
        channel_message: str,
        data: dict,
        db: AsyncSession,
        undo_token: str | None = None,
        trade_id: str | None = None,
    ) -> None:
        telegram_id = await self._get_platform_id(user_id, "telegram", db)
        whatsapp_id = await self._get_platform_id(user_id, "whatsapp", db)
        push_token = await self._get_push_token(user_id, db)
        channels = []
        if telegram_id:
            channels.append("telegram")
        if whatsapp_id:
            channels.append("whatsapp")
        if push_token:
            channels.append("push")

        try:
            db.add(
                ApexNotification(
                    user_id=user_id,
                    notification_type=notification_type,
                    title=title,
                    body=body,
                    data=data,
                    channels=channels,
                    undo_token=undo_token,
                    undo_expires_at=(
                        datetime.now(timezone.utc) + timedelta(seconds=60)
                        if undo_token
                        else None
                    ),
                    trade_id=trade_id,
                )
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error(
                "Failed to persist Unitrader notification for user %s (%s): %s",
                user_id,
                notification_type,
                exc,
            )
            return

        if telegram_id:
            try:
                if self.telegram_bot and getattr(self.telegram_bot, "app", None):
                    await self.telegram_bot.app.bot.send_message(
                        chat_id=telegram_id,
                        text=channel_message,
                        parse_mode="Markdown",
                    )
                else:
                    logger.debug(
                        "Unitrader notification skipped Telegram send; bot not initialised for user %s",
                        user_id,
                    )
            except Exception as exc:
                logger.error("Telegram notification failed for %s: %s", user_id, exc)

        if whatsapp_id:
            try:
                if self.whatsapp_bot:
                    await self.whatsapp_bot.send_message(whatsapp_id, channel_message)
                else:
                    logger.debug(
                        "Unitrader notification skipped WhatsApp send; bot not initialised for user %s",
                        user_id,
                    )
            except Exception as exc:
                logger.error("WhatsApp notification failed for %s: %s", user_id, exc)

        if push_token:
            try:
                await self._send_push(push_token, title, body, data)
            except Exception as exc:
                logger.error("Push notification failed for %s: %s", user_id, exc)

    async def _get_platform_id(
        self, user_id: str, platform: str, db: AsyncSession
    ) -> str | None:
        result = await db.execute(
            select(UserExternalAccount.external_id).where(
                and_(
                    UserExternalAccount.user_id == user_id,
                    UserExternalAccount.platform == platform,
                    UserExternalAccount.is_linked == True,  # noqa: E712
                )
            )
        )
        return result.scalar_one_or_none()

    async def _get_push_token(self, user_id: str, db: AsyncSession) -> str | None:
        result = await db.execute(
            select(UserSettings.push_token).where(UserSettings.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def _send_push(
        self,
        push_token: str,
        title: str,
        body: str,
        data: dict[str, Any],
    ) -> None:
        logger.info(
            "Push provider not configured; skipping push send for token=%s title=%s payload_keys=%s",
            f"{push_token[:8]}..." if push_token else "missing",
            title,
            sorted(data.keys()),
        )

    def _undo_url(self, token: str) -> str:
        return f"{settings.api_base_url.rstrip('/')}/api/trading/undo/{token}"

    def _approve_url(self, token: str) -> str:
        return (
            f"{settings.api_base_url.rstrip('/')}/api/signals/apex-selects/approve/{token}"
        )
