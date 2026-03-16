"""
routers/trading.py — Trading API endpoints for Unitrader.

Endpoints:
    POST /api/trading/execute             — Run analysis + execute trade
    GET  /api/trading/open-positions      — All open positions
    GET  /api/trading/history             — Closed trade history
    GET  /api/trading/performance         — Aggregated statistics
    POST /api/trading/close-position      — Manual close at market
    GET  /api/trading/risk-analysis       — Daily loss, remaining budget
    POST /api/trading/exchange-keys       — Save encrypted exchange API keys
    GET  /api/trading/exchange-keys       — List connected exchanges
    DELETE /api/trading/exchange-keys/{exchange} — Remove exchange keys
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import ExchangeAPIKey, Trade, UserSettings
from routers.auth import get_current_user
from schemas import SuccessResponse, TradeResponse
from security import encrypt_api_key, hash_api_key, decrypt_api_key
from src.agents.goal_tracking_agent import GoalTrackingAgent
from src.agents.shared_memory import SharedMemory
from src.integrations.market_data import classify_asset
from src.agents.orchestrator import get_orchestrator
from src.integrations.exchange_client import (
    get_exchange_client,
    validate_alpaca_keys,
    validate_binance_keys,
    validate_oanda_keys,
)
from src.services.trade_monitoring import enforce_loss_limits
from src.services.subscription import check_trade_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trading", tags=["Trading"])
performance_router = APIRouter(prefix="/api/performance", tags=["Performance"])


# ─────────────────────────────────────────────
# Request / Response Bodies
# ─────────────────────────────────────────────

class ExecuteTradeRequest(BaseModel):
    symbol: str
    exchange: str  # binance | alpaca | oanda


class AnalyzeTradeRequest(BaseModel):
    symbol: str
    exchange: str  # binance | alpaca | oanda
    trader_class: str | None = None


class ClosePositionRequest(BaseModel):
    trade_id: str


class ConnectExchangeRequest(BaseModel):
    exchange: str = Field(..., pattern="^(alpaca|binance|oanda)$")
    api_key: str = Field(..., min_length=1)
    api_secret: str = Field(..., min_length=1)
    is_paper: bool = Field(True, description="Whether these are paper/sandbox keys")


VALID_EXCHANGES = {"alpaca", "binance", "oanda"}


# ─────────────────────────────────────────────
# Validation dispatcher
# ─────────────────────────────────────────────

async def _validate_exchange_keys(exchange: str, api_key: str, api_secret: str, is_paper: bool) -> float:
    """Validate keys against the exchange and return the account balance.

    Raises HTTPException(400) on failure.
    """
    try:
        if exchange == "alpaca":
            valid = await validate_alpaca_keys(api_key, api_secret, paper=is_paper)
            if not valid:
                raise ValueError("Alpaca rejected the credentials")
        elif exchange == "binance":
            valid = await validate_binance_keys(api_key, api_secret)
            if not valid:
                raise ValueError("Binance rejected the credentials")
        elif exchange == "oanda":
            valid = await validate_oanda_keys(api_key, api_secret)
            if not valid:
                raise ValueError("OANDA rejected the credentials")

        client = get_exchange_client(exchange, api_key, api_secret)
        balance = await client.get_account_balance()
        await client.aclose()
        return balance
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not connect to {exchange}: {exc}",
        )


# ─────────────────────────────────────────────
# POST /api/trading/exchange-keys — Connect exchange
# ─────────────────────────────────────────────

@router.post("/exchange-keys")
async def connect_exchange(
    body: ConnectExchangeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save (or update) encrypted exchange API keys for the current user.

    Validates the keys against the exchange before storing them.
    Keys are encrypted with Fernet and never returned after saving.
    """
    exchange = body.exchange.lower()

    balance = await _validate_exchange_keys(exchange, body.api_key, body.api_secret, body.is_paper)

    try:
        enc_key, enc_secret = encrypt_api_key(body.api_key, body.api_secret)
        key_hash_val = hash_api_key(body.api_key)

        existing = await db.execute(
            select(ExchangeAPIKey).where(
                ExchangeAPIKey.user_id == current_user.id,
                ExchangeAPIKey.exchange == exchange,
                ExchangeAPIKey.is_active == True,  # noqa: E712
            )
        )
        old_key = existing.scalar_one_or_none()
        if old_key:
            old_key.is_active = False
            old_key.rotated_at = datetime.now(timezone.utc)

        now = datetime.now(timezone.utc)
        new_key = ExchangeAPIKey(
            user_id=current_user.id,
            exchange=exchange,
            encrypted_api_key=enc_key,
            encrypted_api_secret=enc_secret,
            key_hash=key_hash_val,
            is_active=True,
            is_paper=body.is_paper,
        )
        db.add(new_key)
        await db.commit()
        await db.refresh(new_key)
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to save exchange keys for user %s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save exchange keys. Please try again.",
        )

    return {
        "status": "success",
        "data": {
            "exchange": exchange,
            "connected_at": new_key.created_at.isoformat() if new_key.created_at else now.isoformat(),
            "is_paper": body.is_paper,
            "balance_usd": round(balance, 2),
            "message": f"{exchange.title()} connected successfully",
        },
    }


# ─────────────────────────────────────────────
# GET /api/trading/exchange-keys — List connected exchanges
# ─────────────────────────────────────────────

@router.get("/exchange-keys")
async def list_exchange_keys(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all connected exchanges for the current user (no secrets exposed)."""
    result = await db.execute(
        select(ExchangeAPIKey).where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.is_active == True,  # noqa: E712
        )
    )
    keys = result.scalars().all()
    return {
        "status": "success",
        "data": [
            {
                "exchange": k.exchange,
                "connected_at": k.created_at.isoformat() if k.created_at else None,
                "is_paper": k.is_paper,
                "last_used": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ],
    }


# ─────────────────────────────────────────────
# DELETE /api/trading/exchange-keys/{exchange} — Disconnect
# ─────────────────────────────────────────────

@router.delete("/exchange-keys/{exchange}")
async def disconnect_exchange(
    exchange: str = Path(..., pattern="^(alpaca|binance|oanda)$"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate exchange keys (soft-delete)."""
    result = await db.execute(
        select(ExchangeAPIKey).where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.exchange == exchange.lower(),
            ExchangeAPIKey.is_active == True,  # noqa: E712
        )
    )
    key_row = result.scalar_one_or_none()
    if not key_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active {exchange} connection found",
        )

    try:
        key_row.is_active = False
        key_row.rotated_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to disconnect %s for user %s: %s", exchange, current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect exchange. Please try again.",
        )

    return {"status": "success", "data": {"exchange": exchange, "message": f"{exchange.title()} disconnected"}}


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

    All exchanges can trade all products they offer. Free-tier users have
    a limit of 10 trades per calendar month.
    """
    try:
        # ── Trade limit (free tier: 10/month) ─────────────────────────────────
        trade_check = await check_trade_limit(current_user, db)
        if not trade_check["allowed"]:
            reason = trade_check.get("reason", "unknown")
            used = trade_check.get("trades_used", 0)
            limit = trade_check.get("trades_limit", 10)

            # Frontend displays `detail` directly; keep this as a stable code string.
            # If you want richer messaging, map these codes client-side.
            if reason in {"trial_limit_reached", "subscription_required"}:
                detail = reason
            else:
                detail = "subscription_required"

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail,
            )

        orchestrator = get_orchestrator()
        result = await orchestrator.route(
            user_id=current_user.id,
            action="trade_analyze",
            payload={"symbol": body.symbol.upper()},
            db=db,
        )

        # Agent/orchestrator returned no result
        if result is None:
            logger.error(
                "Trading agent returned no result for user %s on %s",
                current_user.id,
                body.symbol,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="agent_unavailable",
            )

        # Propagate explicit agent errors (e.g. market_data_unavailable)
        if isinstance(result, dict) and result.get("status") == "error":
            reason = result.get("reason", "market_data_unavailable")
            logger.error(
                "Trading agent error for user %s on %s: %s",
                current_user.id,
                body.symbol,
                reason,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=reason,
            )

        # Keep existing UI contract: return the trade result directly.
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Trade execute failed for user %s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc) or "Trade execution failed. Please try again.",
        )


# ─────────────────────────────────────────────
# POST /api/trading/analyze
# ─────────────────────────────────────────────

@router.post("/analyze")
async def analyze_trade(
    body: AnalyzeTradeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run analysis only (no execution)."""
    try:
        orchestrator = get_orchestrator()
        result = await orchestrator.route(
            user_id=current_user.id,
            action="trade_analyze",
            payload={"symbol": body.symbol.upper(), "trader_class": body.trader_class},
            db=db,
        )
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Trade analyze failed for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=500, detail="trade_analyze_failed")


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
# GET /api/trading/ohlcv
# ─────────────────────────────────────────────

@router.get("/ohlcv")
async def get_ohlcv(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    symbol: str = Query(..., description="Symbol, e.g. AAPL"),
    days: int = Query(30, ge=1, le=365),
    interval: str = Query("1day", description="Only '1day' supported"),
):
    """Fetch daily OHLCV bars for charts.

    Calls Alpaca:
      GET /v2/stocks/{symbol}/bars?timeframe=1Day&limit={days}
    """
    if interval.lower() != "1day":
        raise HTTPException(status_code=400, detail="Only interval=1day supported")

    sym = symbol.strip().upper()
    if "/" in sym or "_" in sym:
        raise HTTPException(status_code=400, detail="Only stock symbols supported for ohlcv")

    key_res = await db.execute(
        select(ExchangeAPIKey).where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.exchange == "alpaca",
            ExchangeAPIKey.is_active == True,  # noqa: E712
        )
    )
    key_row = key_res.scalars().first()
    if not key_row:
        raise HTTPException(status_code=404, detail="No active alpaca connection found")

    try:
        raw_key, raw_secret = decrypt_api_key(
            key_row.encrypted_api_key, key_row.encrypted_api_secret
        )
        headers = {
            "APCA-API-KEY-ID": raw_key,
            "APCA-API-SECRET-KEY": raw_secret,
        }
        base = (settings.alpaca_data_url or "https://data.alpaca.markets").rstrip("/")
        url = f"{base}/v2/stocks/{sym}/bars"
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            resp = await client.get(url, params={"timeframe": "1Day", "limit": days})
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        status_code = getattr(exc.response, "status_code", 500)
        logger.error("OHLCV fetch failed for %s: %s", sym, exc)
        raise HTTPException(status_code=status_code, detail="ohlcv_fetch_failed")
    except Exception as exc:
        logger.error("OHLCV fetch failed for %s: %s", sym, exc)
        raise HTTPException(status_code=500, detail="ohlcv_fetch_failed")

    bars = payload.get("bars", []) if isinstance(payload, dict) else []
    out = []
    for b in bars:
        t = b.get("t")
        day = t[:10] if isinstance(t, str) and len(t) >= 10 else ""
        out.append(
            {
                "time": day,
                "open": float(b.get("o", 0) or 0),
                "high": float(b.get("h", 0) or 0),
                "low": float(b.get("l", 0) or 0),
                "close": float(b.get("c", 0) or 0),
                "volume": float(b.get("v", 0) or 0),
            }
        )

    return {"status": "success", "data": out}


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


# ─────────────────────────────────────────────
# GET /api/performance/summary
# ─────────────────────────────────────────────

@performance_router.get("/summary")
async def performance_summary(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Trader-class-aware performance summary.

    Always includes:
      total_return_gbp, total_return_pct, win_rate, total_trades, paper_trades,
      best_trade, worst_trade, monthly_summary
    Additional fields are gated by trader_class.
    """
    ctx = await SharedMemory.load(current_user.id, db)
    trader_class = getattr(ctx, "trader_class", "complete_novice") or "complete_novice"

    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Trade).where(
            Trade.user_id == current_user.id,
            Trade.status == "closed",
            Trade.closed_at.isnot(None),
            Trade.closed_at >= since,
        )
    )
    trades = result.scalars().all()

    def trade_pnl(t: Trade) -> float:
        return float((t.profit or 0) - (t.loss or 0))

    total_return_gbp = sum(trade_pnl(t) for t in trades)
    total_trades = len(trades)
    wins = [t for t in trades if trade_pnl(t) > 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0

    # Use average entry value as a rough capital base proxy for return %
    base_cap = 0.0
    if trades:
        base_cap = sum(float(t.entry_price or 0) * float(t.quantity or 0) for t in trades) / max(
            1, len(trades)
        )
    total_return_pct = (total_return_gbp / base_cap * 100) if base_cap > 0 else 0.0

    best_trade = _trade_to_dict(max(trades, key=trade_pnl)) if trades else None
    worst_trade = _trade_to_dict(min(trades, key=trade_pnl)) if trades else None

    # Monthly summary: YYYY-MM -> pnl
    monthly_summary: dict[str, float] = {}
    for t in trades:
        if not t.closed_at:
            continue
        k = t.closed_at.strftime("%Y-%m")
        monthly_summary[k] = monthly_summary.get(k, 0.0) + trade_pnl(t)

    # Paper trades not currently recorded per trade in DB schema.
    paper_trades = 0

    payload: dict = {
        "total_return_gbp": round(total_return_gbp, 2),
        "total_return_pct": round(total_return_pct, 2),
        "win_rate": round(win_rate, 1),
        "total_trades": total_trades,
        "paper_trades": paper_trades,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "monthly_summary": monthly_summary,
    }

    # ── complete_novice / curious_saver ────────────────────────────────────
    if trader_class in {"complete_novice", "curious_saver"}:
        try:
            goal_agent = GoalTrackingAgent()
            report = await goal_agent.generate_progress_report(current_user.id, db)
            goal_progress_message = report.get("message")
        except Exception:
            goal_progress_message = None

        # Trust ladder summary derived from SharedContext; paper_trades_count unavailable in DB.
        stage = int(getattr(ctx, "trust_ladder_stage", 1) or 1)
        payload["goal_progress_message"] = goal_progress_message or "Keep going — Apex is tracking your progress."
        payload["trust_ladder_summary"] = {
            "stage": stage,
            "days_until_advance": 0,
            "paper_trades_count": 0,
        }

        # One warm sentence from Claude API (best-effort, falls back if not configured)
        encouragement = None
        try:
            if settings.anthropic_api_key:
                from anthropic import Anthropic
                import asyncio as _asyncio

                client = Anthropic()
                prompt = (
                    "Write exactly one warm, encouraging sentence for a beginner investor. "
                    "No numbers, no jargon."
                )
                resp = await _asyncio.to_thread(
                    lambda: client.messages.create(
                        model=settings.anthropic_model,
                        max_tokens=60,
                        messages=[{"role": "user", "content": prompt}],
                    )
                )
                encouragement = resp.content[0].text.strip()
        except Exception:
            encouragement = None
        payload["encouragement"] = encouragement or "You’re doing the right thing by learning step by step."

        # Omit technical metrics implicitly by not adding them.

    # ── self_taught ─────────────────────────────────────────────────────────
    if trader_class == "self_taught":
        # Benchmarks not available from DB-only data; return best-effort placeholders.
        avg_hold_time_days = None
        if trades:
            holds = []
            for t in trades:
                if t.created_at and t.closed_at:
                    holds.append((t.closed_at - t.created_at).total_seconds() / 86400)
            avg_hold_time_days = sum(holds) / len(holds) if holds else None
        payload.update(
            {
                "vs_buy_hold": 0.0,
                "vs_spy": 0.0,
                "avg_hold_time_days": round(avg_hold_time_days, 2) if avg_hold_time_days is not None else 0.0,
            }
        )

    # ── experienced / semi_institutional ────────────────────────────────────
    if trader_class in {"experienced", "semi_institutional"}:
        pnls = [trade_pnl(t) for t in trades]
        mean = (sum(pnls) / len(pnls)) if pnls else 0.0
        var = (sum((x - mean) ** 2 for x in pnls) / len(pnls)) if pnls else 0.0
        stddev = var ** 0.5
        sharpe = (mean / stddev * (252 ** 0.5)) if stddev > 0 else 0.0

        # Max drawdown from cumulative pnl
        peak = 0.0
        dd = 0.0
        cum = 0.0
        for x in pnls:
            cum += x
            peak = max(peak, cum)
            dd = min(dd, cum - peak)
        max_drawdown = (dd / peak * 100) if peak > 0 else float(dd)

        calmar = (total_return_pct / abs(max_drawdown)) if max_drawdown else 0.0

        # Avg hold time (days)
        holds = []
        for t in trades:
            if t.created_at and t.closed_at:
                holds.append((t.closed_at - t.created_at).total_seconds() / 86400)
        avg_hold_time_days = sum(holds) / len(holds) if holds else 0.0

        # Sector PnL not available (sector not stored on Trade). Return empty dict.
        sector_pnl: dict[str, float] = {}

        # Win rate by asset class (symbol classification)
        by_class: dict[str, list[Trade]] = {"stocks": [], "crypto": [], "forex": []}
        for t in trades:
            try:
                ac = classify_asset(t.symbol)
            except Exception:
                ac = "stock"
            key = "stocks" if ac == "stock" else ac
            if key in by_class:
                by_class[key].append(t)
        win_rate_by_asset_class: dict[str, float] = {}
        for k, ts in by_class.items():
            if not ts:
                win_rate_by_asset_class[k] = 0.0
            else:
                w = len([t for t in ts if trade_pnl(t) > 0])
                win_rate_by_asset_class[k] = round(w / len(ts) * 100, 1)

        payload.update(
            {
                "sharpe_ratio": round(sharpe, 3),
                "max_drawdown": round(float(max_drawdown), 3),
                "calmar_ratio": round(float(calmar), 3),
                "beta": 0.0,
                "alpha": 0.0,
                "avg_hold_time_days": round(float(avg_hold_time_days), 2),
                "sector_pnl": sector_pnl,
                "win_rate_by_asset_class": win_rate_by_asset_class,
            }
        )

    # ── crypto_native ───────────────────────────────────────────────────────
    if trader_class == "crypto_native":
        crypto_trades = [t for t in trades if classify_asset(t.symbol) == "crypto"] if trades else []
        best = None
        worst = None
        if crypto_trades:
            best_t = max(crypto_trades, key=lambda t: float(t.profit_percent or -1e9))
            worst_t = min(crypto_trades, key=lambda t: float(t.profit_percent or 1e9))
            best = {
                "symbol": best_t.symbol,
                "pct_gain": float(best_t.profit_percent or 0),
                "pnl_gbp": round(trade_pnl(best_t), 2),
            }
            worst = {
                "symbol": worst_t.symbol,
                "pct_loss": float(worst_t.profit_percent or 0),
                "pnl_gbp": round(trade_pnl(worst_t), 2),
            }
        payload.update(
            {
                "vs_bitcoin_hold": 0.0,
                "best_crypto": best,
                "worst_crypto": worst,
                "total_fees_paid": 0.0,
            }
        )

    return {"status": "success", "data": payload}
