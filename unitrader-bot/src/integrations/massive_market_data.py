"""
src/integrations/massive_market_data.py — Massive.com (Polygon-compatible) market data.

Massive replaces Alpaca as the market data provider for stocks and crypto.
Alpaca remains for paper/live trade execution only.

Free-tier endpoints used:
  /v2/aggs/ticker/{ticker}/prev          — Previous-day OHLCV (stocks + crypto)
  /v2/reference/news                     — News headlines
  /v2/aggs/ticker/{ticker}/range/...     — Daily bars (crypto only on free tier)

Auth: Bearer token via Authorization header, or ?apiKey= query param.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0

# ── Simple in-memory TTL cache for quote results ─────────────────────────────
_quote_cache: dict[str, tuple[float, dict]] = {}   # symbol → (expiry_mono, data)
_QUOTE_CACHE_TTL = 15.0  # seconds — matches the WS poll interval

# ── Global 429 back-off flag ─────────────────────────────────────────────────
_massive_backoff_until: float = 0.0  # monotonic time until which we skip Massive


def _headers() -> dict[str, str]:
    key = (settings.massive_api_key or "").strip()
    if not key:
        raise ValueError(
            "MASSIVE_API_KEY not configured — set it in Railway env vars"
        )
    return {"Authorization": f"Bearer {key}"}


def _base() -> str:
    return (settings.massive_base_url or "https://api.massive.com").rstrip("/")


# ─────────────────────────────────────────────
# Stock market data (AAPL, MSFT, etc.)
# ─────────────────────────────────────────────

async def fetch_massive_stock(symbol: str) -> dict:
    """Fetch previous-day OHLCV for a US stock from Massive /v2/aggs/ticker/{}/prev.

    Returns the same dict shape as the old _fetch_alpaca_stock so it's a
    drop-in replacement.
    """
    ticker = symbol.upper().strip()
    url = f"{_base()}/v2/aggs/ticker/{ticker}/prev"

    global _massive_backoff_until
    if time.monotonic() < _massive_backoff_until:
        raise RuntimeError(f"Massive rate-limited — backing off for {ticker}")

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_headers()) as client:
        resp = await client.get(url)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("retry-after", 30))
            _massive_backoff_until = time.monotonic() + min(60.0, max(5.0, retry_after))
            raise RuntimeError(f"Massive 429 for {ticker} — backing off {retry_after}s")
        if resp.status_code == 403:
            raise PermissionError(
                f"Massive 403 for {ticker} — your plan may not cover this data. "
                f"Check https://massive.com/pricing"
            )
        resp.raise_for_status()

    data = resp.json()
    results = (data.get("results") or [{}])
    bar = results[0] if results else {}

    price = float(bar.get("c", 0) or 0)         # close
    open_price = float(bar.get("o", 0) or 0)
    high = float(bar.get("h", price) or price)
    low = float(bar.get("l", price) or price)
    volume = float(bar.get("v", 0) or 0)
    vwap = float(bar.get("vw", 0) or 0)

    pct = 0.0
    if open_price and open_price != 0:
        pct = ((price - open_price) / open_price) * 100

    return {
        "symbol": ticker,
        "price": price,
        "high_24h": high,
        "low_24h": low,
        "volume": volume,
        "price_change_pct": round(pct, 4),
        "vwap": vwap,
        "timestamp": datetime.now(timezone.utc),
        "source": "massive",
    }


# ─────────────────────────────────────────────
# Crypto market data (BTC/USD → X:BTCUSD)
# ─────────────────────────────────────────────

def _to_massive_crypto_ticker(symbol: str) -> str:
    """Convert BTC/USD, BTCUSD, BTC-USD → X:BTCUSD (Massive format)."""
    clean = symbol.upper().strip()
    clean = clean.replace("-", "").replace("/", "")
    # Already in X: format
    if clean.startswith("X:"):
        return clean
    # Strip trailing USD/USDT for normalisation
    base = clean
    for suffix in ("USDT", "USDC", "BUSD", "USD"):
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    return f"X:{base}USD"


async def fetch_massive_crypto(symbol: str) -> dict:
    """Fetch previous-day OHLCV for a crypto pair from Massive.

    Returns the same dict shape as the old _fetch_alpaca_crypto.
    """
    ticker = _to_massive_crypto_ticker(symbol)
    url = f"{_base()}/v2/aggs/ticker/{ticker}/prev"

    global _massive_backoff_until
    if time.monotonic() < _massive_backoff_until:
        raise RuntimeError(f"Massive rate-limited — backing off for {ticker}")

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_headers()) as client:
        resp = await client.get(url)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("retry-after", 30))
            _massive_backoff_until = time.monotonic() + min(60.0, max(5.0, retry_after))
            raise RuntimeError(f"Massive 429 for {ticker} — backing off {retry_after}s")
        if resp.status_code == 403:
            raise PermissionError(
                f"Massive 403 for {ticker} — check your plan"
            )
        resp.raise_for_status()

    data = resp.json()
    results = (data.get("results") or [{}])
    bar = results[0] if results else {}

    price = float(bar.get("c", 0) or 0)
    open_price = float(bar.get("o", 0) or 0)
    high = float(bar.get("h", price) or price)
    low = float(bar.get("l", price) or price)
    volume = float(bar.get("v", 0) or 0)

    pct = 0.0
    if open_price and open_price != 0:
        pct = ((price - open_price) / open_price) * 100

    return {
        "symbol": symbol,
        "price": price,
        "high_24h": high,
        "low_24h": low,
        "volume": volume,
        "price_change_pct": round(pct, 4),
        "timestamp": datetime.now(timezone.utc),
        "source": "massive",
    }


# ─────────────────────────────────────────────
# News (stocks + crypto)
# ─────────────────────────────────────────────

async def fetch_massive_news(symbol: str, limit: int = 10) -> list[dict]:
    """Fetch recent news headlines from Massive /v2/reference/news.

    Returns a list of dicts with: headline, author, published_utc, url, source.
    Compatible with what sentiment_agent expects from Alpaca news.
    """
    # Strip any slash/dash for the ticker param
    ticker = symbol.upper().strip().replace("/", "").replace("-", "")
    url = f"{_base()}/v2/reference/news"
    params = {"ticker": ticker, "limit": limit, "order": "desc", "sort": "published_utc"}

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_headers()) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()

    data = resp.json()
    articles = data.get("results", [])

    # Normalise to the same shape Alpaca news returns
    normalised = []
    for a in articles:
        normalised.append({
            "headline": a.get("title", ""),
            "author": a.get("author", ""),
            "created_at": a.get("published_utc", ""),
            "url": a.get("article_url", ""),
            "source": (a.get("publisher") or {}).get("name", ""),
            "summary": a.get("description", ""),
        })
    return normalised


# ─────────────────────────────────────────────
# Stock closing prices (for technical indicators)
# ─────────────────────────────────────────────

async def fetch_massive_stock_closes(symbol: str, limit: int = 200) -> list[float]:
    """Fetch recent daily closing prices for a stock.

    Uses /v2/aggs/ticker/{}/range/1/day/{from}/{to} with a wide date range.
    Falls back to prev-close single value if the range endpoint is 403.
    """
    from datetime import timedelta
    ticker = symbol.upper().strip()
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=limit + 10)).strftime("%Y-%m-%d")
    url = f"{_base()}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": limit}

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_headers()) as client:
        resp = await client.get(url, params=params)

    if resp.status_code == 403:
        # Free tier doesn't allow historical date ranges for stocks — return empty
        logger.debug("Massive 403 on stock daily bars for %s — free tier limitation", ticker)
        return []

    resp.raise_for_status()
    bars = resp.json().get("results", []) or []
    return [float(b["c"]) for b in bars if "c" in b]


async def fetch_massive_crypto_closes(symbol: str, limit: int = 200) -> list[float]:
    """Fetch recent daily closing prices for a crypto pair."""
    from datetime import timedelta
    ticker = _to_massive_crypto_ticker(symbol)
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=limit + 10)).strftime("%Y-%m-%d")
    url = f"{_base()}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": limit}

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_headers()) as client:
        resp = await client.get(url, params=params)

    if resp.status_code == 403:
        logger.debug("Massive 403 on crypto daily bars for %s", ticker)
        return []

    resp.raise_for_status()
    bars = resp.json().get("results", []) or []
    return [float(b["c"]) for b in bars if "c" in b]


# ─────────────────────────────────────────────
# Quote for WebSocket fallback (prev-close price)
# ─────────────────────────────────────────────

async def fetch_massive_quote(symbol: str) -> dict:
    """Fetch a price quote for any symbol (stock or crypto).

    Used by the WS router as a fallback when real-time streaming isn't available.
    Returns {symbol, price, bid, ask, timestamp}.

    Results are cached for _QUOTE_CACHE_TTL seconds to avoid 429s when
    multiple WS subscribers poll the same symbol simultaneously.
    """
    key = symbol.upper().strip()
    now = time.monotonic()

    # Return cached result if still fresh
    cached = _quote_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]

    from src.integrations.market_data import classify_asset

    asset_type = classify_asset(symbol)
    if asset_type == "crypto":
        data = await fetch_massive_crypto(symbol)
    else:
        data = await fetch_massive_stock(symbol)

    price = data["price"]
    result = {
        "symbol": key,
        "price": price,
        "bid": price,
        "ask": price,
        "bid_size": 0,
        "ask_size": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "massive",
    }

    # Cache the result
    _quote_cache[key] = (now + _QUOTE_CACHE_TTL, result)

    return result
