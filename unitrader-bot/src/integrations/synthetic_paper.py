"""
synthetic_paper.py — Synthetic paper trade execution for non-Alpaca exchanges.

Exchanges without a native paper trading API (Coinbase, Binance, Kraken, OANDA)
get simulated fills written to the trades table with is_paper=True. The user
experience is identical to Alpaca paper trading; the system never sends a real
order to the exchange.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Trade
from src.market_context import AssetClass

logger = logging.getLogger(__name__)


async def _fetch_current_price(symbol: str, exchange: str) -> float:
    """Fetch current market price using the existing market data layer."""
    from src.integrations.market_data import full_market_analysis

    data = await full_market_analysis(symbol, exchange)
    price = (data or {}).get("price")
    if not price:
        raise ValueError(f"Cannot execute synthetic paper trade: market data unavailable for {symbol}")
    return float(price)


def _round_qty(qty: float, asset_class: str) -> float:
    """Round quantity to appropriate precision for the asset class."""
    if asset_class == AssetClass.CRYPTO.value:
        return float(Decimal(str(qty)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN))
    return float(Decimal(str(qty)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


async def execute_synthetic_paper_trade(
    user_id: str,
    trading_account_id: str,
    symbol: str,
    side: str,
    notional_usd: float,
    exchange: str,
    asset_class: str,
    db: AsyncSession,
    *,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    confidence: float | None = None,
    reasoning: str | None = None,
) -> dict:
    """Execute a simulated paper trade using live market prices.

    The result is inserted into the ``trades`` table with ``is_paper=True``
    and ``account_scope='synthetic_paper'`` so existing queries that filter
    by ``is_paper`` continue to work transparently.
    """
    current_price = await _fetch_current_price(symbol, exchange)
    qty = _round_qty(notional_usd / current_price, asset_class)

    if qty <= 0:
        raise ValueError(f"Synthetic paper trade qty is zero for {symbol} at {current_price}")

    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    trade = Trade(
        id=trade_id,
        user_id=user_id,
        trading_account_id=trading_account_id,
        exchange=exchange,
        is_paper=True,
        account_scope="synthetic_paper",
        symbol=symbol,
        side=side.upper(),
        quantity=qty,
        entry_price=current_price,
        stop_loss=stop_loss or round(current_price * 0.95, 4),
        take_profit=take_profit or round(current_price * 1.10, 4),
        status="open",
        created_at=now,
        claude_confidence=confidence,
        reasoning=reasoning,
    )
    db.add(trade)
    await db.flush()

    logger.info(
        "Synthetic paper trade %s: %s %s %s qty=%.8f @ %.4f on %s",
        trade_id, side.upper(), symbol, asset_class, qty, current_price, exchange,
    )

    return {
        "id": trade_id,
        "symbol": symbol,
        "side": side.upper(),
        "qty": qty,
        "fill_price": current_price,
        "notional_usd": notional_usd,
        "status": "open",
        "paper_mode_type": "synthetic",
        "filled_at": now.isoformat(),
    }


async def get_synthetic_paper_positions(
    user_id: str,
    trading_account_id: str,
    db: AsyncSession,
) -> list[dict]:
    """Return aggregated open synthetic paper positions for a user + account."""
    result = await db.execute(
        select(Trade).where(
            and_(
                Trade.user_id == user_id,
                Trade.trading_account_id == trading_account_id,
                Trade.is_paper == True,  # noqa: E712
                Trade.account_scope == "synthetic_paper",
                Trade.status == "open",
            )
        )
    )
    trades = result.scalars().all()

    # Aggregate by symbol
    positions: dict[str, dict] = {}
    for t in trades:
        if t.symbol not in positions:
            positions[t.symbol] = {
                "symbol": t.symbol,
                "side": t.side,
                "qty": 0.0,
                "total_cost": 0.0,
                "trade_count": 0,
            }
        p = positions[t.symbol]
        if t.side == "BUY":
            p["qty"] += t.quantity
            p["total_cost"] += t.quantity * t.entry_price
        else:
            p["qty"] -= t.quantity
            p["total_cost"] -= t.quantity * t.entry_price
        p["trade_count"] += 1

    out: list[dict] = []
    for p in positions.values():
        if abs(p["qty"]) < 1e-10:
            continue
        avg_fill = abs(p["total_cost"] / p["qty"]) if p["qty"] else 0
        out.append({
            "symbol": p["symbol"],
            "side": "BUY" if p["qty"] > 0 else "SELL",
            "qty": abs(p["qty"]),
            "avg_fill_price": round(avg_fill, 8),
            "notional_usd": round(abs(p["qty"]) * avg_fill, 2),
            "unrealised_pnl": None,  # Filled by calculate_synthetic_pnl
        })
    return out


async def calculate_synthetic_pnl(
    positions: list[dict],
    exchange: str,
) -> list[dict]:
    """Fetch current prices and compute unrealised P&L for synthetic positions."""
    for pos in positions:
        try:
            current_price = await _fetch_current_price(pos["symbol"], exchange)
            pos["current_price"] = current_price
            if pos["side"] == "BUY":
                pos["unrealised_pnl"] = round(
                    (current_price - pos["avg_fill_price"]) * pos["qty"], 2
                )
            else:
                pos["unrealised_pnl"] = round(
                    (pos["avg_fill_price"] - current_price) * pos["qty"], 2
                )
        except Exception:
            pos["current_price"] = None
            pos["unrealised_pnl"] = None
    return positions
