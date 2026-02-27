"""
src/services/trade_execution.py — Pure calculation functions for trade sizing and risk.

No I/O, no database access — these are deterministic helpers used by the trading agent
and can be unit-tested in isolation.
"""

import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Position Sizing
# ─────────────────────────────────────────────

def calculate_position_size(confidence: float, account_balance: float) -> dict:
    """Map Claude's confidence score to a position size.

    Confidence tiers:
        < 50    → 0 % (no trade)
        50–65   → 0.5 %
        65–75   → 1.0 %
        75–85   → 1.5 %
        ≥ 85    → 2.0 % (max)

    Args:
        confidence: Claude confidence score 0–100.
        account_balance: Current account balance in USD.

    Returns:
        {"size_percent": 1.5, "size_amount": 150.0, "tradeable": True}
    """
    if confidence < 50:
        return {"size_percent": 0.0, "size_amount": 0.0, "tradeable": False}

    if confidence < 65:
        pct = 0.5
    elif confidence < 75:
        pct = 1.0
    elif confidence < 85:
        pct = 1.5
    else:
        pct = 2.0

    amount = round(account_balance * (pct / 100), 2)
    return {"size_percent": pct, "size_amount": amount, "tradeable": True}


# ─────────────────────────────────────────────
# Stop Loss
# ─────────────────────────────────────────────

def calculate_stop_loss(
    entry_price: float,
    side: str,
    stop_pct: float = 2.0,
    position_size_usd: float = 0.0,
) -> dict:
    """Calculate stop-loss price and maximum dollar loss.

    BUY  → stop = entry × (1 − stop_pct/100)
    SELL → stop = entry × (1 + stop_pct/100)

    Args:
        entry_price: Trade entry price.
        side: "BUY" or "SELL".
        stop_pct: Distance from entry in percent (default 2 %).
        position_size_usd: Position value in USD (used to calculate max loss).

    Returns:
        {"stop_loss": 44100.0, "max_loss_usd": 135.0, "stop_pct": 2.0}
    """
    if side.upper() == "BUY":
        stop = entry_price * (1 - stop_pct / 100)
    else:
        stop = entry_price * (1 + stop_pct / 100)

    max_loss = round(position_size_usd * (stop_pct / 100), 2) if position_size_usd else 0.0

    return {
        "stop_loss": round(stop, 8),
        "max_loss_usd": max_loss,
        "stop_pct": stop_pct,
    }


# ─────────────────────────────────────────────
# Take Profit
# ─────────────────────────────────────────────

def calculate_take_profit(
    entry_price: float,
    side: str,
    target_pct: float = 6.0,
    position_size_usd: float = 0.0,
) -> dict:
    """Calculate take-profit price and maximum dollar gain.

    BUY  → target = entry × (1 + target_pct/100)
    SELL → target = entry × (1 − target_pct/100)

    Args:
        entry_price: Trade entry price.
        side: "BUY" or "SELL".
        target_pct: Distance from entry in percent (default 6 %).
        position_size_usd: Position value in USD.

    Returns:
        {"take_profit": 46800.0, "max_gain_usd": 270.0, "target_pct": 6.0}
    """
    if side.upper() == "BUY":
        target = entry_price * (1 + target_pct / 100)
    else:
        target = entry_price * (1 - target_pct / 100)

    max_gain = round(position_size_usd * (target_pct / 100), 2) if position_size_usd else 0.0

    return {
        "take_profit": round(target, 8),
        "max_gain_usd": max_gain,
        "target_pct": target_pct,
    }


# ─────────────────────────────────────────────
# Risk / Reward
# ─────────────────────────────────────────────

def calculate_risk_reward(entry: float, stop: float, target: float) -> float:
    """Return the risk-to-reward ratio.

    A ratio of 2.0 means the trade wins $2 for every $1 risked.
    Returns 0.0 if risk is zero (invalid setup).
    """
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk == 0:
        return 0.0
    return round(reward / risk, 2)


# ─────────────────────────────────────────────
# Trade Quantity
# ─────────────────────────────────────────────

def calculate_quantity(position_size_usd: float, price: float) -> float:
    """Convert a USD position size to asset quantity.

    Args:
        position_size_usd: Dollar amount to invest.
        price: Current asset price.

    Returns:
        Quantity rounded to 8 decimal places.
    """
    if price <= 0:
        return 0.0
    return round(position_size_usd / price, 8)


# ─────────────────────────────────────────────
# Full Trade Parameters
# ─────────────────────────────────────────────

def build_trade_parameters(
    confidence: float,
    entry_price: float,
    side: str,
    account_balance: float,
    stop_pct: float = 2.0,
    target_pct: float = 6.0,
) -> dict:
    """Compute all trade parameters in one call.

    Returns a complete dict ready for the trading agent to use:
    {
        "tradeable": bool,
        "size_percent": 1.5,
        "size_amount": 150.0,
        "quantity": 0.00333,
        "stop_loss": 44100.0,
        "take_profit": 46800.0,
        "risk_reward": 3.0,
        "max_loss_usd": 3.0,
        "max_gain_usd": 9.0,
    }
    """
    sizing = calculate_position_size(confidence, account_balance)
    if not sizing["tradeable"]:
        return {
            "tradeable": False,
            "reason": f"Confidence {confidence:.0f} < 50 — no trade",
        }

    sl = calculate_stop_loss(entry_price, side, stop_pct, sizing["size_amount"])
    tp = calculate_take_profit(entry_price, side, target_pct, sizing["size_amount"])
    rr = calculate_risk_reward(entry_price, sl["stop_loss"], tp["take_profit"])
    qty = calculate_quantity(sizing["size_amount"], entry_price)

    return {
        "tradeable": True,
        "size_percent": sizing["size_percent"],
        "size_amount": sizing["size_amount"],
        "quantity": qty,
        "stop_loss": sl["stop_loss"],
        "take_profit": tp["take_profit"],
        "risk_reward": rr,
        "max_loss_usd": sl["max_loss_usd"],
        "max_gain_usd": tp["max_gain_usd"],
    }
