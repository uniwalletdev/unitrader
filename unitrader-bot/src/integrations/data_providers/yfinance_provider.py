"""
YFinance provider — free historical data.
USE FOR: historical closes, technical indicator calculation,
         watchlist scoring, ai-picks analysis.
DO NOT USE FOR: live WebSocket price display or trade execution
               validation (15 minute delay).
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, AsyncGenerator

import yfinance as yf

from .base import MarketDataProvider

logger = logging.getLogger(__name__)

# Module-level cache shared across all instances
_historical_cache: dict[str, tuple[list[float], datetime]] = {}
_CACHE_TTL_HOURS = 4


class YFinanceProvider(MarketDataProvider):

    async def get_historical_closes(
        self, symbol: str, days: int = 200
    ) -> list[float]:
        # Serve from cache if fresh
        key = symbol.upper().strip()
        if key in _historical_cache:
            closes, cached_at = _historical_cache[key]
            age_hours = (datetime.utcnow() - cached_at).total_seconds() / 3600
            if age_hours < _CACHE_TTL_HOURS:
                logger.debug("yfinance cache hit for %s", key)
                return closes

        try:
            loop = asyncio.get_event_loop()
            closes = await loop.run_in_executor(
                None, self._fetch_sync, key, days
            )

            if not closes or len(closes) < 20:
                logger.warning(
                    "yfinance: insufficient data for %s "
                    "(%s candles). "
                    "Yahoo Finance may be rate-limiting or symbol invalid.",
                    key,
                    len(closes) if closes else 0,
                )
                return []

            # Sanity check — reject if more than 10% of values are zero
            valid = [c for c in closes if c and c > 0]
            if len(valid) < len(closes) * 0.9:
                logger.error(
                    "yfinance data quality check failed for %s: "
                    "%s zero/null values detected",
                    key,
                    len(closes) - len(valid),
                )
                return []

            _historical_cache[key] = (valid, datetime.utcnow())
            logger.info("yfinance: fetched %s closes for %s", len(valid), key)
            return valid

        except Exception as e:
            logger.error(
                "yfinance completely failed for %s: %s. "
                "Check if Yahoo Finance endpoint has changed.",
                symbol,
                e,
            )
            return []

    def _fetch_sync(self, symbol: str, days: int) -> list[float]:
        """Synchronous yfinance call — must be run in executor."""
        # yfinance expects e.g. BTC-USD not BTC/USD
        yf_sym = symbol.replace("/", "-")
        ticker = yf.Ticker(yf_sym)
        hist = ticker.history(
            period=f"{days + 14}d",
            interval="1d",
            auto_adjust=True,
        )
        if hist.empty:
            return []
        closes = hist["Close"].dropna().tolist()
        return closes[-days:] if len(closes) > days else closes

    async def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        15-minute delayed price from Yahoo.
        Use only as absolute last resort fallback.
        """
        try:
            loop = asyncio.get_event_loop()

            def _get_price():
                yf_sym = symbol.replace("/", "-")
                ticker = yf.Ticker(yf_sym)
                info = ticker.fast_info
                return getattr(info, "last_price", None)

            price = await loop.run_in_executor(None, _get_price)
            return float(price) if price and price > 0 else None
        except Exception as e:
            logger.warning("yfinance latest price failed for %s: %s", symbol, e)
            return None

    async def stream_prices(
        self, symbols: list[str]
    ) -> AsyncGenerator[dict, None]:
        """
        yfinance cannot stream. Poll every 60s as degraded fallback.
        This will only be used if Alpaca and Coinbase feeds both fail.
        Prices will show as delayed in the UI.
        """
        logger.warning(
            "yfinance stream_prices called — this is a degraded fallback. "
            "Prices will be 15 minutes delayed."
        )
        while True:
            for symbol in symbols:
                price = await self.get_latest_price(symbol)
                if price:
                    yield {
                        "symbol": symbol,
                        "price": price,
                        "source": "yfinance_delayed",
                        "delayed": True,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                await asyncio.sleep(0.5)  # avoid hammering
            await asyncio.sleep(60)
