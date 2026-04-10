"""
Alpaca Data Provider — real-time stock prices.
Uses Alpaca Data API v2 with IEX feed.
FREE with any Alpaca account (paper or live).
No extra subscription required.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, AsyncGenerator

import httpx
import websockets

from config import settings
from .base import MarketDataProvider

logger = logging.getLogger(__name__)

_RECONNECT_DELAY = 5  # seconds between reconnect attempts


class AlpacaDataProvider(MarketDataProvider):

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.ws_url = "wss://stream.data.alpaca.markets/v2/iex"
        base = (settings.alpaca_data_url or "https://data.alpaca.markets").rstrip("/")
        self.rest_url = f"{base}/v2"
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }

    async def get_historical_closes(
        self, symbol: str, days: int = 200
    ) -> list[float]:
        """
        Alpaca Bars endpoint — free, reliable, no delay.
        Backup to yfinance if yfinance is broken.
        """
        sym = symbol.upper().strip()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.rest_url}/stocks/{sym}/bars",
                    headers=self._headers,
                    params={
                        "timeframe": "1Day",
                        "limit": days,
                        "feed": "iex",
                        "sort": "asc",
                    },
                )
                resp.raise_for_status()
                bars = resp.json().get("bars", [])
                closes = [float(b["c"]) for b in bars]
                logger.info(
                    "Alpaca historical: %s closes for %s",
                    len(closes),
                    sym,
                )
                return closes
        except Exception as e:
            logger.warning("Alpaca historical failed for %s: %s", sym, e)
            return []

    async def get_latest_price(self, symbol: str) -> Optional[float]:
        """Real-time latest trade price from Alpaca IEX feed."""
        sym = symbol.upper().strip()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.rest_url}/stocks/{sym}/trades/latest",
                    headers=self._headers,
                    params={"feed": "iex"},
                )
                resp.raise_for_status()
                return float(resp.json()["trade"]["p"])
        except Exception as e:
            logger.warning("Alpaca latest price failed for %s: %s", sym, e)
            return None

    async def stream_prices(
        self, symbols: list[str]
    ) -> AsyncGenerator[dict, None]:
        """
        Persistent WebSocket stream from Alpaca.
        Auto-reconnects on any failure.
        Yields real-time trade prices as they occur.
        """
        syms = [s.upper().strip() for s in symbols]
        while True:
            try:
                logger.info(
                    "Alpaca WS: connecting for %s symbols",
                    len(syms),
                )
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    # Step 1: receive welcome message
                    welcome = json.loads(await ws.recv())
                    logger.info("Alpaca WS welcome: %s", welcome)

                    # Step 2: authenticate
                    await ws.send(json.dumps({
                        "action": "auth",
                        "key": self.api_key,
                        "secret": self.secret_key,
                    }))
                    auth_resp = json.loads(await ws.recv())
                    logger.info("Alpaca WS auth response: %s", auth_resp)

                    # Step 3: subscribe to trades
                    await ws.send(json.dumps({
                        "action": "subscribe",
                        "trades": syms,
                    }))
                    sub_resp = json.loads(await ws.recv())
                    logger.info("Alpaca WS subscribed: %s", sub_resp)

                    # Step 4: yield messages
                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        msgs = data if isinstance(data, list) else [data]
                        for msg in msgs:
                            if msg.get("T") == "t":  # trade update
                                yield {
                                    "symbol": msg["S"],
                                    "price": float(msg["p"]),
                                    "source": "alpaca_realtime",
                                    "delayed": False,
                                    "timestamp": msg.get(
                                        "t",
                                        datetime.utcnow().isoformat()
                                    ),
                                }

            except Exception as e:
                logger.error(
                    "Alpaca WS error: %s. "
                    "Reconnecting in %ss...",
                    e,
                    _RECONNECT_DELAY,
                )
                await asyncio.sleep(_RECONNECT_DELAY)
