from abc import ABC, abstractmethod
from typing import Optional, AsyncGenerator


class MarketDataProvider(ABC):
    """
    Abstract base class for all market data providers.
    All providers implement this interface so they are
    interchangeable with a single config change.
    """

    @abstractmethod
    async def get_historical_closes(
        self, symbol: str, days: int = 200
    ) -> list[float]:
        """
        Returns list of daily closing prices, oldest first.
        Used for technical indicator calculation (RSI, MACD, etc).
        Minimum 20 candles required for indicators to be valid.
        """
        ...

    @abstractmethod
    async def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Returns the most recent available price.
        May be delayed depending on provider.
        """
        ...

    @abstractmethod
    async def stream_prices(
        self, symbols: list[str]
    ) -> AsyncGenerator[dict, None]:
        """
        Yields price update dicts as they arrive:
        {
            "symbol": str,
            "price": float,
            "source": str,
            "delayed": bool,
            "timestamp": str (ISO format)
        }
        Must auto-reconnect on failure without raising.
        """
        ...
