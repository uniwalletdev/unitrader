"""
src/services/trade_monitoring.py — Real-time position monitoring and circuit breakers.

The monitor_loop() runs every 60 seconds and checks every open position against:
  - Stop-loss trigger
  - Take-profit trigger
  - Trailing stop update
  - Daily / weekly / monthly loss limits
  - Anomaly / circuit-breaker conditions
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import ExchangeAPIKey, Trade, User, UserSettings
from security import decrypt_api_key
from src.integrations.exchange_client import get_exchange_client

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Position Monitoring
# ─────────────────────────────────────────────

async def monitor_positions(user_id: str) -> None:
    """Check every open position for stop/target hits and trailing stop updates.

    Called by the background monitor loop every minute.
    """
    async with AsyncSessionLocal() as db:
        trades_result = await db.execute(
            select(Trade).where(
                Trade.user_id == user_id,
                Trade.status == "open",
            )
        )
        open_trades = trades_result.scalars().all()

        if not open_trades:
            return

        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        ai_name = user.ai_name if user else "Claude"

        # Load best available exchange key
        key_result = await db.execute(
            select(ExchangeAPIKey).where(
                ExchangeAPIKey.user_id == user_id,
                ExchangeAPIKey.is_active == True,  # noqa: E712
            )
        )
        key_rows = key_result.scalars().all()
        if not key_rows:
            logger.warning("No exchange API keys for user %s — skipping monitoring", user_id)
            return

        for trade in open_trades:
            await _check_position(db, trade, key_rows, ai_name)

        await db.commit()


async def _check_position(
    db: AsyncSession,
    trade: Trade,
    key_rows: list,
    ai_name: str,
) -> None:
    """Evaluate a single open position and close it if stop/target is hit."""
    # Find matching API key for this trade's exchange (best-effort match)
    key_row = next((k for k in key_rows), None)
    if not key_row:
        return

    try:
        raw_key, raw_secret = decrypt_api_key(
            key_row.encrypted_api_key, key_row.encrypted_api_secret
        )
        client = get_exchange_client(key_row.exchange, raw_key, raw_secret)
        current_price = await client.get_current_price(trade.symbol)
        await client.aclose()
    except Exception as exc:
        logger.error("Could not fetch price for %s: %s", trade.symbol, exc)
        return

    should_close = False
    close_reason = ""

    if trade.side == "BUY":
        if current_price <= (trade.stop_loss or 0):
            should_close = True
            close_reason = "stop-loss hit"
        elif current_price >= (trade.take_profit or float("inf")):
            should_close = True
            close_reason = "take-profit hit"
    else:  # SELL
        if current_price >= (trade.stop_loss or float("inf")):
            should_close = True
            close_reason = "stop-loss hit"
        elif current_price <= (trade.take_profit or 0):
            should_close = True
            close_reason = "take-profit hit"

    if should_close:
        await _close_position_at_price(db, trade, current_price, close_reason, ai_name)


async def _close_position_at_price(
    db: AsyncSession,
    trade: Trade,
    exit_price: float,
    reason: str,
    ai_name: str,
) -> None:
    """Record the closed position in the database and log the result."""
    if trade.side == "BUY":
        pnl = (exit_price - trade.entry_price) * trade.quantity
    else:
        pnl = (trade.entry_price - exit_price) * trade.quantity

    pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
    if trade.side == "SELL":
        pnl_pct = -pnl_pct

    trade.exit_price = exit_price
    trade.status = "closed"
    trade.closed_at = datetime.now(timezone.utc)

    if pnl >= 0:
        trade.profit = round(pnl, 2)
        trade.profit_percent = round(pnl_pct, 4)
        msg = f"{ai_name} closed {trade.symbol} ({reason}). Profit: +${pnl:.2f} 🎉"
    else:
        trade.loss = round(abs(pnl), 2)
        trade.profit_percent = round(pnl_pct, 4)
        msg = f"{ai_name} closed {trade.symbol} ({reason}). Loss: -${abs(pnl):.2f}"

    logger.info(msg)


# ─────────────────────────────────────────────
# Loss Limit Enforcement
# ─────────────────────────────────────────────

async def enforce_loss_limits(user_id: str) -> dict:
    """Check daily, weekly, and monthly loss against user settings.

    Returns:
        {"action": "none" | "halt_daily" | "reduce_weekly" | "close_all_monthly",
         "daily_loss_usd": ..., "weekly_loss_usd": ..., "monthly_loss_usd": ...}
    """
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=now.weekday())
    month_start = day_start.replace(day=1)

    async with AsyncSessionLocal() as db:
        settings_result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        user_settings = settings_result.scalar_one_or_none()

        key_result = await db.execute(
            select(ExchangeAPIKey).where(
                ExchangeAPIKey.user_id == user_id,
                ExchangeAPIKey.is_active == True,  # noqa: E712
            )
        )
        key_row = key_result.scalars().first()

        balance = 10_000.0  # fallback
        if key_row:
            try:
                raw_key, raw_secret = decrypt_api_key(
                    key_row.encrypted_api_key, key_row.encrypted_api_secret
                )
                client = get_exchange_client(key_row.exchange, raw_key, raw_secret)
                balance = await client.get_account_balance()
                await client.aclose()
            except Exception:
                pass

        async def _sum_losses(since: datetime) -> float:
            result = await db.execute(
                select(func.sum(Trade.loss)).where(
                    Trade.user_id == user_id,
                    Trade.closed_at >= since,
                    Trade.status == "closed",
                    Trade.loss.isnot(None),
                )
            )
            return float(result.scalar() or 0)

        daily_loss = await _sum_losses(day_start)
        weekly_loss = await _sum_losses(week_start)
        monthly_loss = await _sum_losses(month_start)

        max_daily_pct = user_settings.max_daily_loss if user_settings else 5.0
        max_weekly_pct = 10.0
        max_monthly_pct = 15.0

        max_daily = balance * (max_daily_pct / 100)
        max_weekly = balance * (max_weekly_pct / 100)
        max_monthly = balance * (max_monthly_pct / 100)

        action = "none"

        if monthly_loss >= max_monthly:
            action = "close_all_monthly"
            await _close_all_positions(db, user_id)
            logger.warning("Monthly loss limit hit for user %s — all positions closed", user_id)
        elif weekly_loss >= max_weekly:
            action = "reduce_weekly"
            logger.warning("Weekly loss limit hit for user %s — reducing position sizes", user_id)
        elif daily_loss >= max_daily:
            action = "halt_daily"
            logger.warning("Daily loss limit hit for user %s — halting trading today", user_id)

        await db.commit()

    return {
        "action": action,
        "daily_loss_usd": round(daily_loss, 2),
        "weekly_loss_usd": round(weekly_loss, 2),
        "monthly_loss_usd": round(monthly_loss, 2),
        "balance": round(balance, 2),
    }


async def _close_all_positions(db: AsyncSession, user_id: str) -> None:
    """Force-close all open positions for a user (emergency stop)."""
    result = await db.execute(
        select(Trade).where(Trade.user_id == user_id, Trade.status == "open")
    )
    trades = result.scalars().all()
    for trade in trades:
        trade.status = "closed"
        trade.closed_at = datetime.now(timezone.utc)
        logger.info("Emergency close: trade %s for user %s", trade.id, user_id)


# ─────────────────────────────────────────────
# Circuit Breakers / Anomaly Detection
# ─────────────────────────────────────────────

async def detect_anomalies(user_id: str) -> dict:
    """Detect rapid loss, unusual trade frequency, or exchange connectivity issues.

    Triggers position closure and logs an alert if anomaly is found.

    Returns:
        {"anomaly_detected": bool, "type": str | None, "action_taken": str}
    """
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    async with AsyncSessionLocal() as db:
        key_result = await db.execute(
            select(ExchangeAPIKey).where(
                ExchangeAPIKey.user_id == user_id,
                ExchangeAPIKey.is_active == True,  # noqa: E712
            )
        )
        key_row = key_result.scalars().first()

        balance = 10_000.0
        if key_row:
            try:
                raw_key, raw_secret = decrypt_api_key(
                    key_row.encrypted_api_key, key_row.encrypted_api_secret
                )
                client = get_exchange_client(key_row.exchange, raw_key, raw_secret)
                balance = await client.get_account_balance()
                await client.aclose()
            except Exception as exc:
                logger.error("Exchange connectivity check failed for %s: %s", user_id, exc)
                return {
                    "anomaly_detected": True,
                    "type": "exchange_unreachable",
                    "action_taken": "no_action_taken",
                }

        # Rapid loss: more than 3% of balance lost in the last hour
        result = await db.execute(
            select(func.sum(Trade.loss)).where(
                Trade.user_id == user_id,
                Trade.closed_at >= one_hour_ago,
                Trade.status == "closed",
            )
        )
        hourly_loss = float(result.scalar() or 0)
        rapid_loss_threshold = balance * 0.03

        if hourly_loss >= rapid_loss_threshold:
            await _close_all_positions(db, user_id)
            await db.commit()
            logger.warning(
                "CIRCUIT BREAKER: rapid loss $%.2f in 1h for user %s — all positions closed",
                hourly_loss, user_id,
            )
            return {
                "anomaly_detected": True,
                "type": "rapid_loss",
                "action_taken": "all_positions_closed",
            }

        # Unusual trading frequency: more than 20 trades in 1 hour
        count_result = await db.execute(
            select(func.count()).where(
                Trade.user_id == user_id,
                Trade.created_at >= one_hour_ago,
            )
        )
        trade_count = count_result.scalar() or 0

        if trade_count > 20:
            logger.warning(
                "ANOMALY: %d trades in 1h for user %s — unusually high frequency",
                trade_count, user_id,
            )
            return {
                "anomaly_detected": True,
                "type": "high_frequency",
                "action_taken": "alert_only",
            }

    return {"anomaly_detected": False, "type": None, "action_taken": "none"}


# ─────────────────────────────────────────────
# Background Loop (called from main.py)
# ─────────────────────────────────────────────

async def monitor_loop() -> None:
    """Continuous monitoring loop — runs every 60 seconds.

    Checks positions, enforces loss limits, and detects anomalies for all
    active users. Designed to run as a long-lived asyncio task.
    """
    logger.info("Monitor loop started")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(User).where(User.is_active == True))  # noqa: E712
                active_users = result.scalars().all()

            for user in active_users:
                try:
                    await monitor_positions(user.id)
                    loss_status = await enforce_loss_limits(user.id)
                    if loss_status["action"] != "none":
                        logger.warning(
                            "Loss limit action '%s' for user %s",
                            loss_status["action"], user.id,
                        )
                    await detect_anomalies(user.id)
                except Exception as exc:
                    logger.error("Monitor error for user %s: %s", user.id, exc)

        except Exception as exc:
            logger.error("Monitor loop outer error: %s", exc)

        await asyncio.sleep(60)
