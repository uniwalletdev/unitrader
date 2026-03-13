"""
src/integrations/market_data.py — Market data fetching and technical analysis.

Symbol routing and exchange validation prevent 404/400 errors:
- Alpaca: stocks (AAPL) + crypto (BTC/USD)
- Binance: crypto only (BTCUSDT)
- OANDA: forex only (EUR_USD)

All indicator calculations are implemented in pure Python (no pandas/numpy).
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
# STEP 1 — Asset classification constants
# ─────────────────────────────────────────────

EXCHANGE_CAPABILITIES = {
    "alpaca": {"stocks": True, "crypto": True, "forex": False},
    "binance": {"stocks": False, "crypto": True, "forex": False},
    "oanda": {"stocks": False, "crypto": False, "forex": True},
}

CRYPTO_SYMBOLS = {
    "BTC", "ETH", "SOL", "DOGE", "ADA", "XRP",
    "AVAX", "DOT", "MATIC", "LINK", "LTC", "BCH",
    "UNI", "ATOM", "ALGO", "XLM", "VET", "FIL", "BNB",
}

FOREX_PAIRS = {
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD", "EUR/GBP",
    "EUR/JPY", "GBP/JPY",
}


def classify_asset(symbol: str) -> str:
    """
    Returns "crypto", "forex", or "stock".
    Works on any symbol format: BTC, BTC/USD, BTCUSDT, EUR/USD, EUR_USD, AAPL.
    
    Prioritizes detection in order: crypto, forex, stock (default).
    """
    if not symbol:
        return "stock"  # Default to stock if empty
    
    clean = symbol.upper().strip()
    parts = clean.split("/")
    if len(parts) == 3:
        clean = f"{parts[0]}/{parts[1]}"

    base = clean.split("/")[0].split("_")[0]

    # Strip stablecoin suffixes to get the actual symbol
    for stable in ["USDT", "USDC", "BUSD", "USD"]:
        if base.endswith(stable) and len(base) > len(stable):
            base = base[: -len(stable)]
            break

    # Check if it's a known cryptocurrency
    if base in CRYPTO_SYMBOLS:
        logger.debug("Classified %s as crypto (base: %s)", symbol, base)
        return "crypto"

    # Check if it's a known forex pair
    normalized = clean.replace("_", "/")
    if normalized in FOREX_PAIRS:
        logger.debug("Classified %s as forex", symbol)
        return "forex"

    # Default to stock
    logger.debug("Classified %s as stock (base: %s)", symbol, base)
    return "stock"


def normalise_symbol(symbol: str, exchange: str) -> str:
    """
    Convert any symbol format to what the exchange API expects.
    Alpaca stocks: AAPL, TSLA. Alpaca crypto: BTC/USD.
    Binance: BTCUSDT. OANDA: EUR_USD.
    """
    clean = symbol.upper().strip()
    parts = clean.split("/")
    if len(parts) == 3:
        clean = f"{parts[0]}/{parts[1]}"

    asset_type = classify_asset(clean)
    ex = exchange.lower()

    if ex == "alpaca":
        if asset_type == "crypto":
            base = clean.split("/")[0].split("_")[0]
            for s in ["USDT", "USDC", "BUSD"]:
                if base.endswith(s):
                    base = base[: -len(s)]
            return f"{base}/USD"
        return clean.split("/")[0].split("_")[0]

    if ex == "binance":
        if asset_type != "crypto":
            raise ValueError(
                f"Binance only supports crypto — cannot trade {symbol} ({asset_type})"
            )
        base = clean.split("/")[0].split("_")[0]
        for s in ["USDT", "USDC", "BUSD", "USD"]:
            if base.endswith(s):
                base = base[: -len(s)]
        return f"{base}USDT"

    if ex == "oanda":
        if asset_type != "forex":
            raise ValueError(
                f"OANDA only supports forex — cannot trade {symbol} ({asset_type})"
            )
        return clean.replace("/", "_")

    return clean


def validate_exchange_for_symbol(symbol: str, exchange: str) -> None:
    """
    Raises ValueError if the exchange cannot trade this asset type.
    Call before making any API request.
    """
    asset_type = classify_asset(symbol)
    capabilities = EXCHANGE_CAPABILITIES.get(exchange.lower(), {})

    if asset_type == "crypto" and not capabilities.get("crypto"):
        raise ValueError(
            f"Exchange '{exchange}' does not support crypto trading. "
            f"Use Binance or Alpaca for {symbol}"
        )
    if asset_type == "stock" and not capabilities.get("stocks"):
        raise ValueError(
            f"Exchange '{exchange}' does not support stock trading. "
            f"Use Alpaca for {symbol}"
        )
    if asset_type == "forex" and not capabilities.get("forex"):
        raise ValueError(
            f"Exchange '{exchange}' does not support forex trading. "
            f"Use OANDA for {symbol}"
        )


# ─────────────────────────────────────────────
# Market Data Fetching (routed)
# ─────────────────────────────────────────────

async def fetch_market_data(symbol: str, exchange: str) -> dict:
    """
    Main entry point. Validates exchange can trade this asset,
    normalises symbol, then routes to the correct fetcher.
    
    For Alpaca, explicitly detects crypto (contains "/" or is in CRYPTO_SYMBOLS)
    to prevent routing to stock endpoint with invalid symbols like "BTC/USD".
    """
    if not symbol or not exchange:
        raise ValueError("symbol and exchange are required")
    
    clean_symbol = symbol.upper().strip()
    parts = clean_symbol.split("/")
    if len(parts) == 3:
        clean_symbol = f"{parts[0]}/{parts[1]}"

    ex = exchange.lower()
    validate_exchange_for_symbol(clean_symbol, ex)
    asset_type = classify_asset(clean_symbol)
    
    # CRITICAL: For Alpaca, explicitly route crypto symbols to crypto endpoint
    # to prevent "GET .../v2/stocks/BTC/USD/... 404 Not Found" errors
    if ex == "alpaca":
        if asset_type == "crypto":
            normalised = normalise_symbol(clean_symbol, ex)
            logger.debug("Routing Alpaca crypto: %s → %s (crypto)", clean_symbol, normalised)
            return await _fetch_alpaca_crypto(normalised)
        elif asset_type == "stock":
            normalised = normalise_symbol(clean_symbol, ex)
            logger.debug("Routing Alpaca stock: %s → %s (stock)", clean_symbol, normalised)
            return await _fetch_alpaca_stock(normalised)
        else:
            raise ValueError(f"Unsupported asset type '{asset_type}' for Alpaca: {clean_symbol}")
    
    normalised = normalise_symbol(clean_symbol, ex)
    
    if ex == "binance":
        return await _fetch_binance(normalised)
    if ex == "oanda":
        return await _fetch_oanda(normalised)
    
    raise ValueError(f"Unknown exchange: {exchange}")


async def _fetch_binance(symbol: str) -> dict:
    """Symbol already normalised to BTCUSDT format."""
    base = (settings.binance_base_url or "https://api.binance.com").rstrip("/")
    url = f"{base}/api/v3/ticker/24hr"
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


async def _fetch_alpaca_crypto(symbol: str) -> dict:
    """Symbol already normalised to BTC/USD format. Uses Alpaca crypto data API.
    
    Raises httpx.HTTPStatusError on API failures (401, 404, etc).
    Returns dict with price, high_24h, low_24h, volume, price_change_pct, timestamp.
    """
    if not symbol or "/" not in symbol:
        raise ValueError(f"Alpaca crypto symbol must be in X/USD format, got: {symbol}")
    
    base = (settings.alpaca_data_url or "https://data.alpaca.markets").rstrip("/")
    headers = {}
    if getattr(settings, "alpaca_api_key", None):
        headers["APCA-API-KEY-ID"] = settings.alpaca_api_key
    if getattr(settings, "alpaca_api_secret", None):
        headers["APCA-API-SECRET-KEY"] = settings.alpaca_api_secret
    
    if not headers:
        logger.warning("No Alpaca API credentials configured for crypto fetch of %s", symbol)
    
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers or None) as client:
            # Fetch latest quote
            quote_resp = await client.get(
                f"{base}/v1beta3/crypto/us/latest/quotes",
                params={"symbols": symbol},
            )
            quote_resp.raise_for_status()
            
            # Fetch 1-day bars for 24h metrics
            bars_resp = await client.get(
                f"{base}/v1beta3/crypto/us/bars",
                params={"symbols": symbol, "timeframe": "1Day", "limit": 2},
            )
            bars_resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.error(
                "Alpaca crypto auth failed (401) for %s - check API credentials. "
                "Key: %s, Secret configured: %s",
                symbol,
                bool(headers.get("APCA-API-KEY-ID")),
                bool(headers.get("APCA-API-SECRET-KEY")),
            )
        elif e.response.status_code == 404:
            logger.error(
                "Alpaca crypto symbol not found (404): %s - ensure it's in X/USD format",
                symbol,
            )
        raise

    quotes = quote_resp.json().get("quotes", {}).get(symbol, {})
    bars_data = bars_resp.json().get("bars", {}).get(symbol, [])
    ap = float(quotes.get("ap", 0) or 0)
    bp = float(quotes.get("bp", 0) or 0)
    price = (ap + bp) / 2 if (ap or bp) else 0.0

    high_24h = low_24h = price
    volume = 0.0
    if bars_data:
        high_24h = max(float(b.get("h", price)) for b in bars_data)
        low_24h = min(float(b.get("l", price)) for b in bars_data)
        volume = float(bars_data[-1].get("v", 0))

    return {
        "symbol": symbol,
        "price": price,
        "high_24h": high_24h,
        "low_24h": low_24h,
        "volume": volume,
        "price_change_pct": 0.0,
        "timestamp": datetime.now(timezone.utc),
    }


async def _fetch_alpaca_stock(symbol: str) -> dict:
    """Symbol already normalised to AAPL format. Uses Alpaca stock data API.
    
    Raises httpx.HTTPStatusError on API failures (401, 404, etc).
    Returns dict with price, high_24h, low_24h, volume, price_change_pct, timestamp.
    """
    if not symbol or "/" in symbol:
        raise ValueError(f"Alpaca stock symbol must NOT contain '/', got: {symbol}")
    
    base = (settings.alpaca_data_url or "https://data.alpaca.markets").rstrip("/")
    headers = {}
    if getattr(settings, "alpaca_api_key", None):
        headers["APCA-API-KEY-ID"] = settings.alpaca_api_key
    if getattr(settings, "alpaca_api_secret", None):
        headers["APCA-API-SECRET-KEY"] = settings.alpaca_api_secret
    
    if not headers:
        logger.warning("No Alpaca API credentials configured for stock fetch of %s", symbol)
    
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers or None) as client:
            quote_resp = await client.get(f"{base}/v2/stocks/{symbol}/quotes/latest")
            quote_resp.raise_for_status()
            bars_resp = await client.get(
                f"{base}/v2/stocks/{symbol}/bars",
                params={"timeframe": "1Day", "limit": 2},
            )
            bars_resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.error(
                "Alpaca stock auth failed (401) for %s - check API credentials. "
                "Key: %s, Secret configured: %s",
                symbol,
                bool(headers.get("APCA-API-KEY-ID")),
                bool(headers.get("APCA-API-SECRET-KEY")),
            )
        elif e.response.status_code == 404:
            logger.error(
                "Alpaca stock symbol not found (404): %s - check symbol validity",
                symbol,
            )
        raise

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
        "price_change_pct": float(quote.get("pc", 0) or 0),
        "timestamp": datetime.now(timezone.utc),
    }


async def _fetch_oanda(symbol: str) -> dict:
    """Symbol already normalised to EUR_USD format."""
    base = (settings.oanda_base_url or "https://api-fxpractice.oanda.com").rstrip("/")
    account_id = getattr(settings, "oanda_account_id", "") or ""
    api_key = getattr(settings, "oanda_api_key", "") or ""
    headers = {"Authorization": f"Bearer {api_key}"}
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
    """Fetch the last `limit` closing prices. Uses same routing as fetch_market_data."""
    clean_symbol = symbol.upper().strip()
    parts = clean_symbol.split("/")
    if len(parts) == 3:
        clean_symbol = f"{parts[0]}/{parts[1]}"
    ex = exchange.lower()
    try:
        validate_exchange_for_symbol(clean_symbol, ex)
        normalised = normalise_symbol(clean_symbol, ex)
    except ValueError:
        return []
    asset_type = classify_asset(clean_symbol)

    if ex == "binance":
        return await _fetch_binance_closes(normalised, limit)
    if ex == "alpaca" and asset_type == "crypto":
        return await _fetch_alpaca_crypto_closes(normalised, limit)
    if ex == "alpaca" and asset_type == "stock":
        return await _fetch_alpaca_stock_closes(normalised, limit)
    if ex == "oanda":
        return await _fetch_oanda_closes(normalised, limit)
    return []


async def _fetch_binance_closes(symbol: str, limit: int) -> list[float]:
    base = (settings.binance_base_url or "https://api.binance.com").rstrip("/")
    url = f"{base}/api/v3/klines"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params={"symbol": symbol, "interval": "5m", "limit": limit})
        resp.raise_for_status()
    return [float(candle[4]) for candle in resp.json()]  # index 4 = close


async def _fetch_alpaca_crypto_closes(symbol: str, limit: int) -> list[float]:
    base = (settings.alpaca_data_url or "https://data.alpaca.markets").rstrip("/")
    headers = {}
    if getattr(settings, "alpaca_api_key", None):
        headers["APCA-API-KEY-ID"] = settings.alpaca_api_key
    if getattr(settings, "alpaca_api_secret", None):
        headers["APCA-API-SECRET-KEY"] = settings.alpaca_api_secret
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers or None) as client:
        resp = await client.get(
            f"{base}/v1beta3/crypto/us/bars",
            params={"symbols": symbol, "timeframe": "5Min", "limit": limit},
        )
        resp.raise_for_status()
    bars = resp.json().get("bars", {}).get(symbol, [])
    return [float(b["c"]) for b in bars]


async def _fetch_alpaca_stock_closes(symbol: str, limit: int) -> list[float]:
    base = (settings.alpaca_data_url or "https://data.alpaca.markets").rstrip("/")
    headers = {}
    if getattr(settings, "alpaca_api_key", None):
        headers["APCA-API-KEY-ID"] = settings.alpaca_api_key
    if getattr(settings, "alpaca_api_secret", None):
        headers["APCA-API-SECRET-KEY"] = settings.alpaca_api_secret
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers or None) as client:
        resp = await client.get(
            f"{base}/v2/stocks/{symbol}/bars",
            params={"timeframe": "5Min", "limit": limit},
        )
        resp.raise_for_status()
    return [float(b["c"]) for b in resp.json().get("bars", [])]


async def _fetch_oanda_closes(symbol: str, limit: int) -> list[float]:
    base = (settings.oanda_base_url or "https://api-fxpractice.oanda.com").rstrip("/")
    account_id = getattr(settings, "oanda_account_id", "") or ""
    api_key = getattr(settings, "oanda_api_key", "") or ""
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
        resp = await client.get(
            f"{base}/v3/instruments/{symbol}/candles",
            params={"count": limit, "granularity": "M5"},
        )
        resp.raise_for_status()
    candles = resp.json().get("candles", [])
    result = []
    for c in candles:
        mid = c.get("mid")
        if mid and "c" in mid:
            result.append(float(mid["c"]))
    return result


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
