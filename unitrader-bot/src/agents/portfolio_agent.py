"""
src/agents/portfolio_agent.py — Portfolio diversification and concentration management.

Evaluates new trades against position limits and sector concentration thresholds.
Limits scale with trader experience level (novice traders get stricter limits).

Class-based limits ensure novices stay diversified while experienced traders
can concentrate more aggressively.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Trade
from src.agents.shared_memory import SharedContext

logger = logging.getLogger(__name__)

# Sector mapping for common symbols
SECTOR_MAP = {
    # Tech
    "AAPL": "tech",
    "MSFT": "tech",
    "GOOGL": "tech",
    "META": "tech",
    "NVDA": "tech",
    "AMZN": "tech",
    "NFLX": "tech",
    # Finance
    "JPM": "finance",
    "GS": "finance",
    "BAC": "finance",
    # Crypto
    "BTC/USD": "crypto",
    "ETH/USD": "crypto",
    "SOL/USD": "crypto",
    "XRP/USD": "crypto",
    # Forex
    "EUR_USD": "forex",
    "GBP_USD": "forex",
    "USD_JPY": "forex",
    # Indices & Commodities
    "SPY": "index",
    "GLD": "commodity",
}

# Portfolio limits by trader class
CLASS_LIMITS = {
    "complete_novice": {
        "max_positions": 3,
        "max_sector_pct": 50,
        "cash_reserve_pct": 30,
    },
    "curious_saver": {
        "max_positions": 4,
        "max_sector_pct": 55,
        "cash_reserve_pct": 25,
    },
    "self_taught": {
        "max_positions": 5,
        "max_sector_pct": 60,
        "cash_reserve_pct": 20,
    },
    "experienced": {
        "max_positions": 8,
        "max_sector_pct": 70,
        "cash_reserve_pct": 10,
    },
    "semi_institutional": {
        "max_positions": 15,
        "max_sector_pct": 80,
        "cash_reserve_pct": 5,
    },
    "crypto_native": {
        "max_positions": 6,
        "max_sector_pct": 80,
        "cash_reserve_pct": 15,
    },
}

# User-friendly messages for novices
NOVICE_MESSAGES = {
    "max_positions": {
        "reason": "Apex thinks you have enough trades open right now.",
        "suggestion": "Close one of your current positions before opening a new one — this keeps your risk manageable.",
    },
    "sector_concentration": {
        "reason": "You already have quite a few similar companies in your portfolio.",
        "suggestion": "Adding more of the same type increases your risk. Consider something different.",
    },
}


class PortfolioAgent:
    """Evaluates trades against portfolio diversification rules.

    Enforces position limits and sector concentration thresholds that scale
    with trader experience. Novices get stricter limits to encourage diversification.
    """

    async def evaluate_new_trade(
        self,
        user_id: str,
        symbol: str,
        side: str,
        amount: float,
        ctx: SharedContext,
        db: AsyncSession,
    ) -> dict:
        """Evaluate if a new trade meets portfolio requirements.

        Checks:
        1. Total open positions < class limit
        2. Sector concentration < class limit (after adding this trade)

        Args:
            user_id: User ID
            symbol: Trading pair (e.g., "AAPL", "BTC/USD")
            side: "BUY" or "SELL"
            amount: Trade amount in USD
            ctx: SharedContext with trader_class for limit lookup
            db: AsyncSession for database queries

        Returns:
            dict with keys:
              - approved: bool
              - reason: str (why decision was made)
              - suggestion: str | None (how to fix if rejected)
        """
        # For SELL orders, skip checks (closing positions reduces portfolio risk)
        if side.upper() == "SELL":
            return {
                "approved": True,
                "reason": "Sell orders do not require portfolio evaluation",
                "suggestion": None,
            }

        # Get trader class limits (default to novice if not found)
        limits = CLASS_LIMITS.get(ctx.trader_class, CLASS_LIMITS["complete_novice"])

        # Check 1: Max open positions
        open_trades = await self._get_open_positions(user_id, db)

        if len(open_trades) >= limits["max_positions"]:
            if ctx.is_novice():
                msgs = NOVICE_MESSAGES["max_positions"]
            else:
                msgs = {
                    "reason": f"You have {len(open_trades)} open positions (class limit: {limits['max_positions']}).",
                    "suggestion": "Close an existing position before opening a new one.",
                }
            logger.info(
                f"Portfolio check REJECTED for user {user_id}: max positions reached ({len(open_trades)}/{limits['max_positions']})"
            )
            return {
                "approved": False,
                "reason": msgs["reason"],
                "suggestion": msgs["suggestion"],
            }

        # Check 2: Sector concentration
        sector = SECTOR_MAP.get(symbol, "other")

        # Calculate current sector exposure
        total_exposure = sum(
            float(t.quantity or 0) * float(t.entry_price or 0) for t in open_trades
        )
        sector_exposure = sum(
            float(t.quantity or 0) * float(t.entry_price or 0)
            for t in open_trades
            if SECTOR_MAP.get(t.symbol, "other") == sector
        )

        # Calculate post-trade sector percentage
        new_total_exposure = total_exposure + amount
        new_sector_pct = (
            ((sector_exposure + amount) / new_total_exposure * 100)
            if new_total_exposure > 0
            else 100.0
        )

        if new_sector_pct > limits["max_sector_pct"]:
            similar = [
                t.symbol
                for t in open_trades
                if SECTOR_MAP.get(t.symbol, "other") == sector
            ]
            if ctx.is_novice():
                msgs = NOVICE_MESSAGES["sector_concentration"]
            else:
                msgs = {
                    "reason": f"Adding {symbol} would put {new_sector_pct:.0f}% of your portfolio in {sector}.",
                    "suggestion": f"Already holding: {', '.join(similar)}. Consider SPY or GLD to balance.",
                }
            logger.info(
                f"Portfolio check REJECTED for user {user_id}: sector concentration too high ({new_sector_pct:.0f}% in {sector})"
            )
            return {
                "approved": False,
                "reason": msgs["reason"],
                "suggestion": msgs["suggestion"],
            }

        logger.debug(
            f"Portfolio check APPROVED for user {user_id}: {len(open_trades)}/{limits['max_positions']} positions, {new_sector_pct:.0f}% in {sector}"
        )
        return {
            "approved": True,
            "reason": "Portfolio check passed",
            "suggestion": None,
        }

    async def _get_open_positions(
        self, user_id: str, db: AsyncSession
    ) -> list:
        """Fetch all open (non-closed) trades for a user.

        Args:
            user_id: User ID
            db: AsyncSession

        Returns:
            List of Trade objects with status != "closed"
        """
        try:
            result = await db.execute(
                select(Trade).where(
                    Trade.user_id == user_id,
                    Trade.status != "closed",
                )
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to fetch open positions for user {user_id}: {e}")
            return []
