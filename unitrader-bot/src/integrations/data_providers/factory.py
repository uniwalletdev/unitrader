"""
Factory for market data providers.
Switch historical provider via DATA_PROVIDER env (yfinance default, alpaca optional).
"""

import logging
from functools import lru_cache

from config import settings

from .base import MarketDataProvider
from .yfinance_provider import YFinanceProvider
from .alpaca_provider import AlpacaDataProvider
from .coinbase_provider import CoinbaseProvider

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_stock_history_provider() -> MarketDataProvider:
    """
    Provider used for historical closes and indicator calculation.
    Default: yfinance (free). Optional: alpaca via DATA_PROVIDER=alpaca.
    """
    provider_name = (settings.data_provider or "yfinance").strip().lower()

    if provider_name == "alpaca":
        logger.info("Historical provider: Alpaca Data API")
        return AlpacaDataProvider(
            api_key=settings.alpaca_paper_api_key or "",
            secret_key=settings.alpaca_paper_api_secret or "",
        )
    logger.info("Historical provider: yfinance (free)")
    return YFinanceProvider()


@lru_cache(maxsize=1)
def get_realtime_stock_provider() -> MarketDataProvider:
    """
    Provider used for real-time stock quotes and streaming.
    Uses Alpaca data API credentials.
    """
    logger.info("Real-time stock provider: Alpaca Data API (IEX)")
    return AlpacaDataProvider(
        api_key=settings.alpaca_paper_api_key or "",
        secret_key=settings.alpaca_paper_api_secret or "",
    )


@lru_cache(maxsize=1)
def get_realtime_crypto_provider() -> MarketDataProvider:
    """
    Provider used for real-time crypto quotes and streaming.
    Coinbase public feed — no auth needed.
    """
    logger.info("Real-time crypto provider: Coinbase public feed")
    return CoinbaseProvider()
