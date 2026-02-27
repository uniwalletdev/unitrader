"""
routers/trading.py — Trading API endpoints for Unitrader.

Endpoints:
    POST /api/trading/execute             — Run analysis + execute trade
    GET  /api/trading/open-positions      — All open positions
    GET  /api/trading/history             — Closed trade history
    GET  /api/trading/performance         — Aggregated statistics
    POST /api/trading/close-position      — Manual close at market
    GET  /api/trading/risk-analysis       — Daily loss, remaining budget
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Trade, UserSettings
from routers.auth import get_current_user
from schemas import SuccessResponse, TradeResponse
from src.agents.core.trading_agent import TradingAgent
from src.services.trade_monitoring import enforce_loss_limits
from src.services.subscription import check_free_tier_symbol, check_trade_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trading", tags=["Trading"])


# ─────────────────────────────────────────────
# Request / Response Bodies
# ─────────────────────────────────────────────

class ExecuteTradeRequest(BaseModel):
    symbol: str
    exchange: str  # binance | alpaca | oanda


class ClosePositionRequest(BaseModel):
    trade_id: str


# ─────────────────────────────────────────────
# POST /api/trading/execute
# ─────────────────────────────────────────────

@router.post("/execute")
async def execute_trade(
    body: ExecuteTradeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run a full market analysis cycle and execute a trade if conditions are met.

    Free-tier users (trial ended + chose free) are restricted to BTC/USD
    and 10 trades per calendar month.
    """
    # ── Free tier enforcement ─────────────────────────────────────────────
    check_free_tier_symbol(current_user, body.symbol)

    trade_check = await check_trade_limit(current_user, db)
    if not trade_check["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Free plan limit reached: {trade_check['trades_used']} / "
                f"{trade_check['trades_limit']} trades used this month. "
                "Upgrade to Pro for unlimited trades."
            ),
        )

    agent = TradingAgent(current_user.id)
    result = await agent.run_cycle(
        symbol=body.symbol.upper(),
        exchange_name=body.exchange.lower(),
    )
    return {"status": "success", "data": result}


# ─────────────────────────────────────────────
# GET /api/trading/open-positions
# ─────────────────────────────────────────────

@router.get("/open-positions")
async def get_open_positions(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all currently open positions for the authenticated user."""
    result = await db.execute(
        select(Trade)
        .where(Trade.user_id == current_user.id, Trade.status == "open")
        .order_by(Trade.created_at.desc())
    )
    trades = result.scalars().all()
    return {
        "status": "success",
        "data": {
            "count": len(trades),
            "positions": [_trade_to_dict(t) for t in trades],
        },
    }


# ─────────────────────────────────────────────
# GET /api/trading/history
# ─────────────────────────────────────────────

@router.get("/history")
async def get_trade_history(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    symbol: str | None = Query(None, description="Filter by symbol, e.g. BTCUSDT"),
    from_date: datetime | None = Query(None, description="Start date (ISO 8601)"),
    to_date: datetime | None = Query(None, description="End date (ISO 8601)"),
    outcome: str | None = Query(None, description="profit | loss"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return closed trade history with optional filters."""
    filters = [Trade.user_id == current_user.id, Trade.status == "closed"]

    if symbol:
        filters.append(Trade.symbol == symbol.upper())
    if from_date:
        filters.append(Trade.closed_at >= from_date)
    if to_date:
        filters.append(Trade.closed_at <= to_date)
    if outcome == "profit":
        filters.append(Trade.profit.isnot(None))
    elif outcome == "loss":
        filters.append(Trade.loss.isnot(None))

    result = await db.execute(
        select(Trade)
        .where(and_(*filters))
        .order_by(Trade.closed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    trades = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).where(and_(*filters))
    )
    total = count_result.scalar() or 0

    return {
        "status": "success",
        "data": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "trades": [_trade_to_dict(t) for t in trades],
        },
    }


# ─────────────────────────────────────────────
# GET /api/trading/performance
# ─────────────────────────────────────────────

@router.get("/performance")
async def get_performance(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    symbol: str | None = Query(None),
    market_condition: str | None = Query(None),
):
    """Return aggregated performance statistics.

    Optional filters: symbol, market_condition (uptrend / downtrend / consolidating).
    """
    base_filter = [
        Trade.user_id == current_user.id,
        Trade.status == "closed",
    ]
    if symbol:
        base_filter.append(Trade.symbol == symbol.upper())
    if market_condition:
        base_filter.append(Trade.market_condition == market_condition)

    result = await db.execute(select(Trade).where(and_(*base_filter)))
    trades = result.scalars().all()

    if not trades:
        return {"status": "success", "data": {"message": "No closed trades yet"}}

    wins = [t for t in trades if (t.profit or 0) > 0]
    losses = [t for t in trades if (t.loss or 0) > 0]

    total_profit = sum(t.profit or 0 for t in wins)
    total_loss = sum(t.loss or 0 for t in losses)
    net_pnl = total_profit - total_loss
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    avg_profit_pct = (
        sum(t.profit_percent or 0 for t in wins) / len(wins) if wins else 0
    )
    avg_loss_pct = (
        sum(t.profit_percent or 0 for t in losses) / len(losses) if losses else 0
    )

    # Best and worst trades
    best = max(trades, key=lambda t: t.profit or 0)
    worst = min(trades, key=lambda t: -(t.loss or 0))

    return {
        "status": "success",
        "data": {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 1),
            "total_profit_usd": round(total_profit, 2),
            "total_loss_usd": round(total_loss, 2),
            "net_pnl_usd": round(net_pnl, 2),
            "avg_profit_pct": round(avg_profit_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "best_trade": _trade_to_dict(best),
            "worst_trade": _trade_to_dict(worst),
        },
    }


# ─────────────────────────────────────────────
# POST /api/trading/close-position
# ─────────────────────────────────────────────

@router.post("/close-position")
async def close_position(
    body: ClosePositionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually close an open position at current market price.

    Fetches the live price, cancels pending stop/target orders, records P&L.
    """
    # Verify trade belongs to this user
    result = await db.execute(
        select(Trade).where(
            Trade.id == body.trade_id,
            Trade.user_id == current_user.id,
            Trade.status == "open",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Open trade not found",
        )

    agent = TradingAgent(current_user.id)
    result = await agent.close_position(body.trade_id)
    return {"status": "success", "data": result}


# ─────────────────────────────────────────────
# GET /api/trading/risk-analysis
# ─────────────────────────────────────────────

@router.get("/risk-analysis")
async def get_risk_analysis(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current daily loss, remaining budget, and loss limit status.

    Useful for the frontend dashboard to show risk indicators in real-time.
    """
    loss_status = await enforce_loss_limits(current_user.id)

    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    user_settings = settings_result.scalar_one_or_none()
    max_daily_pct = user_settings.max_daily_loss if user_settings else 5.0

    balance = loss_status["balance"]
    daily_loss = loss_status["daily_loss_usd"]
    max_daily_usd = balance * (max_daily_pct / 100)
    remaining = max(max_daily_usd - daily_loss, 0)
    used_pct = (daily_loss / max_daily_usd * 100) if max_daily_usd > 0 else 0

    alert = used_pct >= 80

    return {
        "status": "success",
        "data": {
            "balance_usd": round(balance, 2),
            "daily_loss_usd": round(daily_loss, 2),
            "daily_loss_pct": round(used_pct, 1),
            "max_daily_loss_usd": round(max_daily_usd, 2),
            "remaining_budget_usd": round(remaining, 2),
            "weekly_loss_usd": round(loss_status["weekly_loss_usd"], 2),
            "monthly_loss_usd": round(loss_status["monthly_loss_usd"], 2),
            "limit_action": loss_status["action"],
            "alert": alert,
            "alert_message": "Approaching daily loss limit!" if alert else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def _trade_to_dict(trade: Trade) -> dict:
    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "side": trade.side,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "profit": trade.profit,
        "loss": trade.loss,
        "profit_percent": trade.profit_percent,
        "status": trade.status,
        "claude_confidence": trade.claude_confidence,
        "market_condition": trade.market_condition,
        "execution_time_ms": trade.execution_time,
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
        "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
    }
