"""
src/integrations/market_data.py — Market data fetching and technical analysis.

All indicator calculations are implemented in pure Python (no pandas/numpy) to
keep the dependency footprint minimal. For production, replacing these with
pandas-ta or ta-lib will improve accuracy and performance.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0


# ─────────────────────────────────────────────
# Market Data Fetching
# ─────────────────────────────────────────────

async def fetch_market_data(symbol: str, exchange: str) -> dict:
    """Fetch current market snapshot for a symbol from the given exchange.

    Returns:
        {
            "symbol": "BTCUSDT",
            "price": 45000.0,
            "high_24h": 46500.0,
            "low_24h": 44000.0,
            "volume": 150_000_000.0,
            "price_change_pct": 1.5,
            "timestamp": datetime,
        }
    """
    exchange = exchange.lower()
    if exchange == "binance":
        return await _fetch_binance(symbol)
    if exchange == "alpaca":
        return await _fetch_alpaca(symbol)
    if exchange == "oanda":
        return await _fetch_oanda(symbol)
    raise ValueError(f"Unsupported exchange for market data: {exchange}")


async def _fetch_binance(symbol: str) -> dict:
    url = "https://api.binance.com/api/v3/ticker/24hr"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params={"symbol": symbol})
        resp.raise_for_status()
        d = resp.json()
    return {
        "symbol": symbol,
        "price": float(d["lastPrice"]),
        "high_24h": float(d["highPrice"]),
        "low_24h": float(d["lowPrice"]),
        "volume": float(d["quoteVolume"]),
        "price_change_pct": float(d["priceChangePercent"]),
        "timestamp": datetime.now(timezone.utc),
    }


async def _fetch_alpaca(symbol: str) -> dict:
    base = settings.alpaca_base_url.rstrip("/")
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
        quote_resp = await client.get(f"{base}/v2/stocks/{symbol}/quotes/latest")
        quote_resp.raise_for_status()
        bars_resp = await client.get(
            f"{base}/v2/stocks/{symbol}/bars",
            params={"timeframe": "1Day", "limit": 2},
        )
        bars_resp.raise_for_status()

    quote = quote_resp.json().get("quote", {})
    bars = bars_resp.json().get("bars", [])
    price = (float(quote.get("ap", 0)) + float(quote.get("bp", 0))) / 2

    high_24h = low_24h = price
    volume = 0.0
    if bars:
        high_24h = max(float(b.get("h", price)) for b in bars)
        low_24h = min(float(b.get("l", price)) for b in bars)
        volume = float(bars[-1].get("v", 0))

    return {
        "symbol": symbol,
        "price": price,
        "high_24h": high_24h,
        "low_24h": low_24h,
        "volume": volume,
        "price_change_pct": 0.0,
        "timestamp": datetime.now(timezone.utc),
    }


async def _fetch_oanda(symbol: str) -> dict:
    base = settings.oanda_base_url.rstrip("/")
    account_id = settings.oanda_account_id
    headers = {"Authorization": f"Bearer {settings.oanda_api_key}"}
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
        resp = await client.get(
            f"{base}/v3/accounts/{account_id}/pricing",
            params={"instruments": symbol},
        )
        resp.raise_for_status()

    prices = resp.json().get("prices", [])
    price = 0.0
    if prices:
        bid = float(prices[0].get("bids", [{}])[0].get("price", 0))
        ask = float(prices[0].get("asks", [{}])[0].get("price", 0))
        price = (bid + ask) / 2

    return {
        "symbol": symbol,
        "price": price,
        "high_24h": price,
        "low_24h": price,
        "volume": 0.0,
        "price_change_pct": 0.0,
        "timestamp": datetime.now(timezone.utc),
    }


async def fetch_ohlcv(symbol: str, exchange: str, limit: int = 200) -> list[float]:
    """Fetch the last `limit` closing prices for indicator calculations.

    Returns a list of floats ordered oldest → newest.
    """
    exchange = exchange.lower()
    if exchange == "binance":
        return await _fetch_binance_closes(symbol, limit)
    if exchange == "alpaca":
        return await _fetch_alpaca_closes(symbol, limit)
    logger.warning("OHLCV not implemented for %s — returning empty list", exchange)
    return []


async def _fetch_binance_closes(symbol: str, limit: int) -> list[float]:
    url = "https://api.binance.com/api/v3/klines"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params={"symbol": symbol, "interval": "5m", "limit": limit})
        resp.raise_for_status()
    return [float(candle[4]) for candle in resp.json()]  # index 4 = close


async def _fetch_alpaca_closes(symbol: str, limit: int) -> list[float]:
    base = settings.alpaca_base_url.rstrip("/")
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
        resp = await client.get(
            f"{base}/v2/stocks/{symbol}/bars",
            params={"timeframe": "5Min", "limit": limit},
        )
        resp.raise_for_status()
    return [float(b["c"]) for b in resp.json().get("bars", [])]


# ─────────────────────────────────────────────
# Technical Indicators
# ─────────────────────────────────────────────

def _ema(prices: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(prices[:period]) / period]
    for price in prices[period:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


def calculate_rsi(prices: list[float], period: int = 14) -> float:
    """Calculate RSI (0–100). Returns 50.0 if insufficient data."""
    if len(prices) < period + 1:
        return 50.0

    deltas = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calculate_macd(prices: list[float]) -> dict:
    """Calculate MACD (12, 26, 9).

    Returns:
        {"line": float, "signal": float, "histogram": float}
    """
    empty = {"line": 0.0, "signal": 0.0, "histogram": 0.0}
    if len(prices) < 35:
        return empty

    ema12 = _ema(prices, 12)
    ema26 = _ema(prices, 26)

    offset = len(ema12) - len(ema26)
    macd_line = [ema12[i + offset] - ema26[i] for i in range(len(ema26))]

    if len(macd_line) < 9:
        return empty

    signal_line = _ema(macd_line, 9)
    if not signal_line:
        return empty

    macd_val = macd_line[-1]
    signal_val = signal_line[-1]
    return {
        "line": round(macd_val, 6),
        "signal": round(signal_val, 6),
        "histogram": round(macd_val - signal_val, 6),
    }


def calculate_moving_averages(prices: list[float]) -> dict:
    """Calculate SMA-20, SMA-50, SMA-200.

    Returns:
        {"ma20": float, "ma50": float, "ma200": float}
    """

    def sma(n: int) -> float:
        if len(prices) < n:
            return prices[-1] if prices else 0.0
        return round(sum(prices[-n:]) / n, 8)

    return {"ma20": sma(20), "ma50": sma(50), "ma200": sma(200)}


def calculate_indicators(prices: list[float]) -> dict:
    """Aggregate all technical indicators into a single dict.

    Returns:
        {
            "rsi": 65.0,
            "macd": {"line": ..., "signal": ..., "histogram": ...},
            "ma20": ..., "ma50": ..., "ma200": ...,
        }
    """
    mas = calculate_moving_averages(prices)
    return {
        "rsi": calculate_rsi(prices),
        "macd": calculate_macd(prices),
        **mas,
    }


# ─────────────────────────────────────────────
# Trend Detection
# ─────────────────────────────────────────────

def detect_trend(prices: list[float]) -> str:
    """Classify market condition using short/long MA relationship + slope.

    Returns: "uptrend" | "downtrend" | "consolidating"
    """
    if len(prices) < 50:
        return "consolidating"

    ma20 = sum(prices[-20:]) / 20
    ma50 = sum(prices[-50:]) / 50

    # Recent slope: compare last 10 closes
    recent = prices[-10:]
    slope = (recent[-1] - recent[0]) / recent[0] * 100  # pct change

    if ma20 > ma50 and slope > 0.5:
        return "uptrend"
    if ma20 < ma50 and slope < -0.5:
        return "downtrend"
    return "consolidating"


# ─────────────────────────────────────────────
# Support & Resistance
# ─────────────────────────────────────────────

def calculate_support_resistance(prices: list[float]) -> dict:
    """Calculate pivot point, support, and resistance levels.

    Uses the standard floor-trader pivot formula on recent OHLC data.
    Falls back to a simple min/max approach when limited data is available.

    Returns:
        {"support": float, "resistance": float, "pivot": float}
    """
    if len(prices) < 3:
        p = prices[-1] if prices else 0.0
        return {"support": p, "resistance": p, "pivot": p}

    high = max(prices[-20:])
    low = min(prices[-20:])
    close = prices[-1]

    pivot = (high + low + close) / 3
    support = 2 * pivot - high
    resistance = 2 * pivot - low

    return {
        "support": round(support, 8),
        "resistance": round(resistance, 8),
        "pivot": round(pivot, 8),
    }


# ─────────────────────────────────────────────
# Full Market Analysis Bundle
# ─────────────────────────────────────────────

async def full_market_analysis(symbol: str, exchange: str) -> dict:
    """Fetch live data + compute all indicators in one call.

    This is the primary function called by the trading agent.

    Returns a complete market snapshot dict suitable for the Claude prompt.
    """
    snapshot = await fetch_market_data(symbol, exchange)
    closes = await fetch_ohlcv(symbol, exchange, limit=200)

    indicators: dict[str, Any] = {}
    trend = "consolidating"
    support_resistance: dict = {}

    if closes:
        indicators = calculate_indicators(closes)
        trend = detect_trend(closes)
        support_resistance = calculate_support_resistance(closes)

    return {
        **snapshot,
        "trend": trend,
        "indicators": indicators,
        "support_resistance": support_resistance,
        "closes_available": len(closes),
    }
