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
