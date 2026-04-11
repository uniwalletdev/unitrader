"""
Maintains persistent upstream WebSocket connections.
Feeds the price store continuously in the background.
Started once at app startup — never stopped.
"""

import asyncio
import logging

from src.integrations.data_providers.factory import (
    get_realtime_stock_provider,
    get_realtime_crypto_provider,
)
from src.services.price_store import price_store

logger = logging.getLogger(__name__)

STOCK_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN",
    "GOOGL", "META", "AMD", "NFLX", "JPM",
    "V", "MA", "BAC", "GS", "CRM",
    "ADBE", "INTC", "WMT", "JNJ", "UNH",
]

CRYPTO_SYMBOLS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD",
    "AVAX-USD", "DOGE-USD", "LINK-USD",
    "MATIC-USD", "DOT-USD", "UNI-USD",
]


async def run_stock_feed():
    """
    Persistent Alpaca stock price feed.
    Writes every trade update to price_store.
    Auto-reconnects on failure (handled inside provider).
    """
    provider = get_realtime_stock_provider()
    logger.info("Stock feed starting: %s symbols via Alpaca", len(STOCK_SYMBOLS))

    async for update in provider.stream_prices(STOCK_SYMBOLS):
        await price_store.update(
            symbol=update["symbol"],
            price=update["price"],
            source=update["source"],
            delayed=update.get("delayed", False),
        )


async def run_crypto_feed():
    """
    Persistent Coinbase crypto price feed.
    Writes every ticker update to price_store.
    Auto-reconnects on failure (handled inside provider).
    """
    provider = get_realtime_crypto_provider()
    logger.info(
        "Crypto feed starting: %s symbols via Coinbase",
        len(CRYPTO_SYMBOLS),
    )

    async for update in provider.stream_prices(CRYPTO_SYMBOLS):
        await price_store.update(
            symbol=update["symbol"],
            price=update["price"],
            source=update["source"],
            delayed=update.get("delayed", False),
        )


async def get_direct_price(
    symbol: str,
    *,
    is_crypto: bool,
    alpaca_key: str,
    alpaca_secret: str,
) -> dict | None:
    """
    One-shot Alpaca Data API latest quote (fallback after price_store / providers).
    Returns ``{"bid", "ask", "q"}`` where ``q`` is the raw quote object for timestamps/sizes.
    """
    import httpx

    from src.integrations.alpaca_circuit_breaker import alpaca_breaker
    from src.integrations.alpaca_rate_limiter import alpaca_limiter

    if not alpaca_key or not alpaca_secret:
        return None

    headers = {
        "APCA-API-KEY-ID": alpaca_key,
        "APCA-API-SECRET-KEY": alpaca_secret,
    }
    sym = symbol.upper().strip()

    async def _get_json(url: str, params: dict | None = None) -> dict:
        backoff_s = 1.0
        last_exc: Exception | None = None
        for _ in range(3):
            try:
                async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
                    await alpaca_limiter.acquire()
                    resp = await client.get(url, params=params)
                if resp.status_code == 401:
                    alpaca_breaker.record_auth_failure(f"get_direct_price 401 on {url}")
                    resp.raise_for_status()
                if resp.status_code == 429:
                    retry_after = resp.headers.get("retry-after")
                    try:
                        wait_s = float(retry_after) if retry_after else backoff_s
                    except Exception:
                        wait_s = backoff_s
                    await asyncio.sleep(min(10.0, max(0.5, wait_s)))
                    backoff_s = min(10.0, backoff_s * 2)
                    continue
                resp.raise_for_status()
                alpaca_breaker.record_success()
                return resp.json()
            except Exception as exc:
                last_exc = exc
                await asyncio.sleep(min(10.0, backoff_s))
                backoff_s = min(10.0, backoff_s * 2)
        raise last_exc or RuntimeError("Alpaca request failed")

    try:
        if is_crypto:
            url = "https://data.alpaca.markets/v1beta3/crypto/us/latest/quotes"
            payload = await _get_json(url, params={"symbols": sym})
            quotes = payload.get("quotes", {}) or {}
            q = quotes.get(sym, {}) or {}
        else:
            url = f"https://data.alpaca.markets/v2/stocks/{sym}/quotes/latest"
            payload = await _get_json(url)
            q = payload.get("quote", {}) or {}
        bid = float(q.get("bp", 0) or 0)
        ask = float(q.get("ap", 0) or 0)
        return {"bid": bid, "ask": ask, "q": q}
    except Exception:
        return None


def start_price_feeds() -> None:
    """
    Schedule both feeds as background tasks (run concurrently).
    One failing does not kill the other; each provider reconnects internally.
    """
    from config import settings

    logger.info("Starting price feeds (Alpaca stocks + Coinbase crypto)")
    if (settings.alpaca_paper_api_key or "").strip() and (
        settings.alpaca_paper_api_secret or ""
    ).strip():
        asyncio.create_task(run_stock_feed())
    else:
        logger.warning(
            "Alpaca data API credentials missing — stock price feed not started "
            "(set ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET)",
        )
    asyncio.create_task(run_crypto_feed())
