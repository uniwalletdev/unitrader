"""
src/services/trade_monitoring.py — Real-time position monitoring and circuit breakers.

The monitor_loop() runs every 60 seconds and checks every open position against:
  - Stop-loss trigger (class-aware width)
  - Take-profit trigger (class-aware width)
  - Trailing stop update (class-aware frequency)
  - Daily / weekly / monthly loss limits
  - Anomaly / circuit-breaker conditions

Trader-class-specific monitoring:
  - Novices: Wider stops (avoid shakeouts), alerts when price approaches SL/TP
  - Pros: Tighter stops, minimal alerts (only on execution)
  - Crypto: Volatile-adjusted stops, market cycle context

No decrypted API keys are cached. Each connectivity check uses a fresh DB session
and loads ExchangeAPIKey by ID; missing keys are dropped from monitoring.
401 backoff: two consecutive 401s for a key pause that key for 60s.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import ExchangeAPIKey, Trade, User, UserSettings
from security import decrypt_api_key
from src.agents.shared_memory import SharedMemory
from src.integrations.exchange_client import get_exchange_client

logger = logging.getLogger(__name__)

# Backoff state only (no credentials). key_id -> {consecutive_401: int, backoff_until: datetime | None}
_key_backoff: dict[str, dict] = {}
# Key IDs currently being monitored; removed when key no longer exists in DB.
_monitored_key_ids: set[str] = set()

# ─────────────────────────────────────────────
# Trader-Class-Aware Monitoring Parameters
# ─────────────────────────────────────────────

MONITORING_CONFIG = {
    "complete_novice": {
        "stop_loss_width_pct": 1.5,      # Wiggle room (e.g., 1.5% wider)
        "take_profit_width_pct": -0.5,   # Tighter TP (lock in wins)
        "alert_on_approach": True,        # Notify when price gets close to SL/TP
        "approach_threshold_pct": 0.3,    # Alert when within 0.3% of SL/TP
        "trailing_stop_update_freq": 300, # Update every 5 min (slower, less confusing)
        "notification_style": "gentle",   # Warm messaging
    },
    "curious_saver": {
        "stop_loss_width_pct": 1.0,
        "take_profit_width_pct": -0.25,
        "alert_on_approach": True,
        "approach_threshold_pct": 0.4,
        "trailing_stop_update_freq": 300,
        "notification_style": "gentle",
    },
    "self_taught": {
        "stop_loss_width_pct": 0.5,
        "take_profit_width_pct": 0.0,
        "alert_on_approach": False,      # They know what they're doing
        "approach_threshold_pct": 0.5,
        "trailing_stop_update_freq": 180,
        "notification_style": "standard",
    },
    "experienced": {
        "stop_loss_width_pct": 0.0,      # Use their exact stop loss
        "take_profit_width_pct": 0.0,    # Use their exact take profit
        "alert_on_approach": False,
        "approach_threshold_pct": 0.0,
        "trailing_stop_update_freq": 120, # Update every 2 min
        "notification_style": "technical",
    },
    "semi_institutional": {
        "stop_loss_width_pct": -0.5,     # Tighter stops for risk control
        "take_profit_width_pct": 0.25,   # Wider TP to let winners run
        "alert_on_approach": False,
        "approach_threshold_pct": 0.0,
        "trailing_stop_update_freq": 60,  # Update every 1 min (tight control)
        "notification_style": "technical",
    },
    "crypto_native": {
        "stop_loss_width_pct": 0.75,     # Mid-range (crypto is volatile)
        "take_profit_width_pct": 0.5,    # Wider TP (don't miss moons)
        "alert_on_approach": True,        # They like market updates
        "approach_threshold_pct": 0.5,
        "trailing_stop_update_freq": 150, # Update every 2.5 min
        "notification_style": "crypto",   # Include market sentiment
    },
}



# ─────────────────────────────────────────────
# Position Monitoring
# ─────────────────────────────────────────────

async def monitor_positions(user_id: str) -> None:
    """Check every open position for stop/target hits and trailing stop updates.

    Uses fresh DB session per key; no cached credentials. Key IDs are resolved
    from active keys for this user, then each key is loaded by ID in its own session.
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
        key_result = await db.execute(
            select(ExchangeAPIKey.id).where(
                ExchangeAPIKey.user_id == user_id,
                ExchangeAPIKey.is_active == True,  # noqa: E712
            )
        )
        key_ids = [row[0] for row in key_result.all()]
    if not key_ids:
        logger.warning("No exchange API keys for user %s — skipping monitoring", user_id)
        return

    _monitored_key_ids.update(key_ids)
    for key_id in key_ids:
        await _run_position_checks_for_key(key_id)


async def _run_position_checks_for_key(key_id: str) -> None:
    """Run position checks for one exchange key. Fresh session per key; decrypt once per check."""
    now = datetime.now(timezone.utc)
    backoff = _key_backoff.get(key_id, {})
    if backoff.get("backoff_until") and now < backoff["backoff_until"]:
        return

    async with AsyncSessionLocal() as db:
        key_result = await db.execute(
            select(ExchangeAPIKey).where(ExchangeAPIKey.id == key_id)
        )
        key_row = key_result.scalar_one_or_none()
        if key_row is None:
            _monitored_key_ids.discard(key_id)
            logger.info(
                "Exchange key %s no longer exists, removing from monitoring",
                key_id,
            )
            return
        user_result = await db.execute(select(User).where(User.id == key_row.user_id))
        user = user_result.scalar_one_or_none()
        ai_name = user.ai_name if user else "Claude"
        
        # Load trader context for class-aware monitoring
        ctx = await SharedMemory.load(key_row.user_id, db)
        trader_class = ctx.trader_class
        config = MONITORING_CONFIG.get(trader_class, MONITORING_CONFIG["experienced"])
        
        trades_result = await db.execute(
            select(Trade).where(
                Trade.user_id == key_row.user_id,
                Trade.status == "open",
                Trade.exchange == key_row.exchange,
            )
        )
        trades = trades_result.scalars().all()
        # Copy minimal data so we don't hold session or ORM refs
        trade_data = [
            {
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
            }
            for t in trades
        ]

    if not trade_data:
        return

    raw_key = raw_secret = None
    try:
        raw_key, raw_secret = decrypt_api_key(
            key_row.encrypted_api_key, key_row.encrypted_api_secret
        )
        client = get_exchange_client(
            key_row.exchange, raw_key, raw_secret,
            is_paper=getattr(key_row, "is_paper", True),
        )
        raw_key = raw_secret = None
    except Exception as exc:
        logger.error("Could not decrypt key %s: %s", key_id, exc)
        return

    try:
        for td in trade_data:
            try:
                current_price = await client.get_current_price(td["symbol"])
                _clear_key_backoff(key_id)
            except httpx.HTTPStatusError as exc:
                if getattr(exc.response, "status_code", None) == 401:
                    _key_backoff.setdefault(key_id, {"consecutive_401": 0, "backoff_until": None})
                    _key_backoff[key_id]["consecutive_401"] = (
                        _key_backoff[key_id].get("consecutive_401", 0) + 1
                    )
                    if _key_backoff[key_id]["consecutive_401"] >= 2:
                        _key_backoff[key_id]["backoff_until"] = now + timedelta(seconds=60)
                        logger.warning(
                            "Exchange key %s received repeated 401s — pausing for 60s",
                            key_id,
                        )
                    return
                logger.error("Could not fetch price for %s: %s", td["symbol"], exc)
                return
            except Exception as exc:
                logger.error("Could not fetch price for %s: %s", td["symbol"], exc)
                return

            # ─── Apply trader-class-aware stop-loss / take-profit widths ─────────
            entry_price = td["entry_price"] or 0
            sl = td["stop_loss"] or 0
            tp = td["take_profit"] or float("inf")
            
            # Adjust stop-loss width based on trader class
            sl_width_adjustment = (entry_price * config["stop_loss_width_pct"] / 100)
            if td["side"] == "BUY":
                # BUY: SL is below entry. Add width_adjustment to make it wider (lower).
                sl_adjusted = sl - sl_width_adjustment if sl > 0 else sl
            else:
                # SELL: SL is above entry. Add width_adjustment to make it wider (higher).
                sl_adjusted = sl + sl_width_adjustment if sl > 0 else sl
            
            # Adjust take-profit width based on trader class
            tp_width_adjustment = (entry_price * config["take_profit_width_pct"] / 100)
            if td["side"] == "BUY":
                # BUY: TP is above entry. Adjust by the factor.
                tp_adjusted = tp + tp_width_adjustment if tp < float("inf") else tp
            else:
                # SELL: TP is below entry. Adjust by the factor.
                tp_adjusted = tp - tp_width_adjustment if tp > 0 else tp

            should_close = False
            close_reason = ""
            proximity_warning = ""
            
            if td["side"] == "BUY":
                # Check SL hit (use adjusted SL)
                if current_price <= sl_adjusted:
                    should_close = True
                    close_reason = f"stop-loss hit (trader_class={trader_class})"
                # Check TP hit (use adjusted TP)
                elif current_price >= tp_adjusted:
                    should_close = True
                    close_reason = f"take-profit hit (trader_class={trader_class})"
                # Alert on approach (novices and crypto natives)
                elif config["alert_on_approach"]:
                    dist_to_sl = current_price - sl_adjusted
                    dist_pct = (dist_to_sl / current_price * 100) if current_price > 0 else 0
                    if dist_pct < config["approach_threshold_pct"]:
                        proximity_warning = (
                            f"⚠️ {td['symbol']}: price ${current_price:.2f} approaching "
                            f"stop-loss ${sl_adjusted:.2f} ({dist_pct:.2f}%)"
                        )
            else:  # SELL
                # Check SL hit (use adjusted SL)
                if current_price >= sl_adjusted:
                    should_close = True
                    close_reason = f"stop-loss hit (trader_class={trader_class})"
                # Check TP hit (use adjusted TP)
                elif current_price <= tp_adjusted:
                    should_close = True
                    close_reason = f"take-profit hit (trader_class={trader_class})"
                # Alert on approach (novices and crypto natives)
                elif config["alert_on_approach"]:
                    dist_to_sl = sl_adjusted - current_price
                    dist_pct = (dist_to_sl / current_price * 100) if current_price > 0 else 0
                    if dist_pct < config["approach_threshold_pct"]:
                        proximity_warning = (
                            f"⚠️ {td['symbol']}: price ${current_price:.2f} approaching "
                            f"stop-loss ${sl_adjusted:.2f} ({dist_pct:.2f}%)"
                        )

            if should_close:
                async with AsyncSessionLocal() as db2:
                    trade_refresh = await db2.get(Trade, td["id"])
                    if trade_refresh and trade_refresh.status == "open":
                        await _close_position_at_price(
                            db2, trade_refresh, current_price, close_reason, ai_name
                        )
                        await db2.commit()
            elif proximity_warning:
                logger.info("Proximity warning [%s]: %s", trader_class, proximity_warning)
    finally:
        await client.aclose()


def _clear_key_backoff(key_id: str) -> None:
    _key_backoff[key_id] = {"consecutive_401": 0, "backoff_until": None}


async def _close_position_at_price(
    db: AsyncSession,
    trade: Trade,
    exit_price: float,
    reason: str,
    ai_name: str,
) -> None:
    """Record the closed position in the database and log the result.
    
    Args:
        db: Database session
        trade: Trade object to close
        exit_price: Exit price
        reason: Reason for closure (includes trader_class info from monitor)
        ai_name: Name to use in messages
    """
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
    # TODO: Feed the outcome back into shared memory using new orchestrator API
    # The learn_from_outcome() method needs to be implemented in the new orchestrator
    # For now, trade outcomes are logged but not fed back into the symbiotic learning system


# ─────────────────────────────────────────────
# Loss Limit Enforcement
# ─────────────────────────────────────────────

_LOSS_LIMIT_FALLBACK = {
    "action": "none",
    "daily_loss_usd": 0.0,
    "weekly_loss_usd": 0.0,
    "monthly_loss_usd": 0.0,
    "balance": 10_000.0,  # safe fallback — matches internal default
    "trader_class": "complete_novice",
}


async def enforce_loss_limits(user_id: str) -> dict:
    """Check daily, weekly, and monthly loss against user settings.
    
    Applies trader-class-aware loss thresholds:
    - Novices: Stricter limits (lower risk tolerance)
    - Pros: Standard limits
    - Crypto natives: Adjusted for volatility

    Returns:
        {"action": "none" | "halt_daily" | "reduce_weekly" | "close_all_monthly",
         "daily_loss_usd": ..., "weekly_loss_usd": ..., "monthly_loss_usd": ...,
         "trader_class": ..., "balance": ...}
    """
    try:
        return await _enforce_loss_limits_impl(user_id)
    except Exception:
        logger.exception("enforce_loss_limits failed for user %s — returning safe fallback", user_id)
        return _LOSS_LIMIT_FALLBACK


async def _enforce_loss_limits_impl(user_id: str) -> dict:
    """Internal implementation — called by enforce_loss_limits with outer try/except."""
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=now.weekday())
    month_start = day_start.replace(day=1)

    async with AsyncSessionLocal() as db:
        settings_result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        user_settings = settings_result.scalar_one_or_none()

        # Load trader context for class-aware limits
        ctx = await SharedMemory.load(user_id, db)
        trader_class = ctx.trader_class

        key_result = await db.execute(
            select(ExchangeAPIKey.id).where(
                ExchangeAPIKey.user_id == user_id,
                ExchangeAPIKey.is_active == True,  # noqa: E712
            ).limit(1)
        )
        key_id_row = key_result.first()
        key_id = key_id_row[0] if key_id_row else None

    balance = 10_000.0  # fallback
    if key_id:
        async with AsyncSessionLocal() as db_key:
            key_result = await db_key.execute(
                select(ExchangeAPIKey).where(ExchangeAPIKey.id == key_id)
            )
            key_row = key_result.scalar_one_or_none()
        if key_row:
            try:
                raw_key, raw_secret = decrypt_api_key(
                    key_row.encrypted_api_key, key_row.encrypted_api_secret
                )
                client = get_exchange_client(
                    key_row.exchange, raw_key, raw_secret,
                    is_paper=getattr(key_row, "is_paper", True),
                )
                balance = await client.get_account_balance()
                await client.aclose()
            except Exception:
                pass

    async with AsyncSessionLocal() as db:
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

        # Class-aware loss limits
        CLASS_LOSS_LIMITS = {
            "complete_novice":    {"daily_pct": 3.0, "weekly_pct": 7.0, "monthly_pct": 10.0},
            "curious_saver":      {"daily_pct": 4.0, "weekly_pct": 8.0, "monthly_pct": 12.0},
            "self_taught":        {"daily_pct": 5.0, "weekly_pct": 10.0, "monthly_pct": 15.0},
            "experienced":        {"daily_pct": 5.0, "weekly_pct": 10.0, "monthly_pct": 15.0},
            "semi_institutional": {"daily_pct": 7.0, "weekly_pct": 12.0, "monthly_pct": 20.0},
            "crypto_native":      {"daily_pct": 6.0, "weekly_pct": 11.0, "monthly_pct": 18.0},
        }
        
        limits = CLASS_LOSS_LIMITS.get(trader_class, CLASS_LOSS_LIMITS["experienced"])
        max_daily_pct = user_settings.max_daily_loss if user_settings else limits["daily_pct"]
        max_weekly_pct = limits["weekly_pct"]
        max_monthly_pct = limits["monthly_pct"]

        max_daily = balance * (max_daily_pct / 100)
        max_weekly = balance * (max_weekly_pct / 100)
        max_monthly = balance * (max_monthly_pct / 100)

        action = "none"

        if monthly_loss >= max_monthly:
            action = "close_all_monthly"
            await _close_all_positions(db, user_id)
            logger.warning(
                "Monthly loss limit hit for user %s (class=%s): %.2f%% lost — all positions closed",
                user_id, trader_class, (monthly_loss / balance * 100)
            )
        elif weekly_loss >= max_weekly:
            action = "reduce_weekly"
            logger.warning(
                "Weekly loss limit hit for user %s (class=%s): %.2f%% lost — reducing sizes",
                user_id, trader_class, (weekly_loss / balance * 100)
            )
        elif daily_loss >= max_daily:
            action = "halt_daily"
            logger.warning(
                "Daily loss limit hit for user %s (class=%s): %.2f%% lost — halting trades",
                user_id, trader_class, (daily_loss / balance * 100)
            )

        await db.commit()

    return {
        "action": action,
        "daily_loss_usd": round(daily_loss, 2),
        "weekly_loss_usd": round(weekly_loss, 2),
        "monthly_loss_usd": round(monthly_loss, 2),
        "balance": round(balance, 2),
        "trader_class": trader_class,
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
    Uses fresh DB session and key-by-ID load for balance; no cached credentials.
    """
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    key_id = None
    async with AsyncSessionLocal() as db:
        key_result = await db.execute(
            select(ExchangeAPIKey.id).where(
                ExchangeAPIKey.user_id == user_id,
                ExchangeAPIKey.is_active == True,  # noqa: E712
            ).limit(1)
        )
        key_id_row = key_result.first()
        key_id = key_id_row[0] if key_id_row else None

    balance = 10_000.0
    if key_id:
        # Respect the same backoff used by position monitoring — avoid hammering
        # a known-bad key every 60 s and flooding logs with repeated 401s.
        now = datetime.now(timezone.utc)
        backoff = _key_backoff.get(key_id, {})
        if backoff.get("backoff_until") and now < backoff["backoff_until"]:
            logger.debug(
                "detect_anomalies: skipping connectivity check for key %s (backoff active)",
                key_id,
            )
        else:
            async with AsyncSessionLocal() as db_key:
                key_result = await db_key.execute(
                    select(ExchangeAPIKey).where(ExchangeAPIKey.id == key_id)
                )
                key_row = key_result.scalar_one_or_none()
            if key_row:
                try:
                    raw_key, raw_secret = decrypt_api_key(
                        key_row.encrypted_api_key, key_row.encrypted_api_secret
                    )
                    client = get_exchange_client(
                        key_row.exchange, raw_key, raw_secret,
                        is_paper=getattr(key_row, "is_paper", True),
                    )
                    balance = await client.get_account_balance()
                    await client.aclose()
                    _clear_key_backoff(key_id)
                except httpx.HTTPStatusError as exc:
                    if getattr(exc.response, "status_code", None) == 401:
                        _key_backoff.setdefault(key_id, {"consecutive_401": 0, "backoff_until": None})
                        _key_backoff[key_id]["consecutive_401"] = (
                            _key_backoff[key_id].get("consecutive_401", 0) + 1
                        )
                        if _key_backoff[key_id]["consecutive_401"] >= 2:
                            _key_backoff[key_id]["backoff_until"] = now + timedelta(seconds=300)
                            logger.warning(
                                "detect_anomalies: key %s (user %s) repeated 401 — pausing for 5 min",
                                key_id, user_id,
                            )
                        else:
                            logger.warning(
                                "detect_anomalies: 401 for key %s (user %s) — credentials may be invalid",
                                key_id, user_id,
                            )
                    else:
                        logger.error("Exchange connectivity check failed for %s: %s", user_id, exc)
                    return {
                        "anomaly_detected": True,
                        "type": "exchange_unreachable",
                        "action_taken": "no_action_taken",
                    }
                except Exception as exc:
                    logger.error("Exchange connectivity check failed for %s: %s", user_id, exc)
                    return {
                        "anomaly_detected": True,
                        "type": "exchange_unreachable",
                        "action_taken": "no_action_taken",
                    }

    async with AsyncSessionLocal() as db:
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
