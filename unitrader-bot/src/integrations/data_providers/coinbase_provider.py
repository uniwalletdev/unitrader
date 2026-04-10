"""
Coinbase Provider — real-time crypto prices.
Uses Coinbase Exchange public REST + Advanced Trade public WebSocket.
Zero authentication required for public endpoints.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, AsyncGenerator

import httpx
import websockets

from .base import MarketDataProvider

logger = logging.getLogger(__name__)

_RECONNECT_DELAY = 5


class CoinbaseProvider(MarketDataProvider):

    WS_URL = "wss://advanced-trade-ws.coinbase.com"
    # Public Exchange API (candles) — stable product feed
    EXCHANGE_REST = "https://api.exchange.coinbase.com"
    # Spot price (no auth)
    V2_SPOT = "https://api.coinbase.com/v2/prices"

    def _normalise(self, symbol: str) -> str:
        """
        Normalise symbol to Coinbase product id format.
        BTC-USD → BTC-USD (unchanged)
        BTCUSD → BTC-USD
        BTC/USD → BTC-USD
        """
        symbol = symbol.upper().replace("/", "-")
        if "-" not in symbol and len(symbol) >= 6:
            return f"{symbol[:-3]}-{symbol[-3:]}"
        return symbol

    async def get_historical_closes(
        self, symbol: str, days: int = 200
    ) -> list[float]:
        """Daily closes from Coinbase Exchange candles (public, no auth)."""
        cb_symbol = self._normalise(symbol)
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=min(days + 5, 400))
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.EXCHANGE_REST}/products/{cb_symbol}/candles",
                    params={
                        "granularity": 86400,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                    },
                )
                resp.raise_for_status()
                candles = resp.json()
                if not isinstance(candles, list):
                    return []
                # Each row: [time, low, high, open, close, volume]
                rows = sorted(candles, key=lambda x: x[0])
                closes = [float(r[4]) for r in rows if len(r) > 4]
                if len(closes) > days:
                    closes = closes[-days:]
                logger.info(
                    "Coinbase historical: %s closes for %s",
                    len(closes),
                    symbol,
                )
                return closes
        except Exception as e:
            logger.warning("Coinbase historical failed for %s: %s", symbol, e)
            return []

    async def get_latest_price(self, symbol: str) -> Optional[float]:
        """Current spot price from Coinbase public v2 endpoint."""
        cb_symbol = self._normalise(symbol)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.V2_SPOT}/{cb_symbol}/spot",
                )
                resp.raise_for_status()
                price = resp.json().get("data", {}).get("amount")
                return float(price) if price else None
        except Exception as e:
            logger.warning("Coinbase latest price failed for %s: %s", symbol, e)
            return None

    async def stream_prices(
        self, symbols: list[str]
    ) -> AsyncGenerator[dict, None]:
        """
        Coinbase Advanced Trade public WebSocket ticker feed.
        No authentication required.
        Auto-reconnects on failure.
        """
        cb_symbols = [self._normalise(s) for s in symbols]

        while True:
            try:
                logger.info(
                    "Coinbase WS: connecting for %s symbols",
                    len(cb_symbols),
                )
                async with websockets.connect(
                    self.WS_URL,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    await ws.send(json.dumps({
                        "type": "subscribe",
                        "product_ids": cb_symbols,
                        "channel": "ticker",
                    }))

                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if data.get("channel") == "ticker":
                            for event in data.get("events", []):
                                for ticker in event.get("tickers", []):
                                    price = ticker.get("price")
                                    if price:
                                        yield {
                                            "symbol": ticker["product_id"],
                                            "price": float(price),
                                            "source": "coinbase_realtime",
                                            "delayed": False,
                                            "timestamp": data.get(
                                                "timestamp",
                                                datetime.utcnow().isoformat()
                                            ),
                                        }

            except Exception as e:
                logger.error(
                    "Coinbase WS error: %s. "
                    "Reconnecting in %ss...",
                    e,
                    _RECONNECT_DELAY,
                )
                await asyncio.sleep(_RECONNECT_DELAY)
