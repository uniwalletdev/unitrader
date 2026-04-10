"""
Central in-memory price store.

All frontend WebSocket connections read from here.
All upstream data feeds write to here.

This means zero upstream API calls on WebSocket connect —
the price is served instantly from memory.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class PriceUpdate:
    symbol: str
    price: float
    source: str
    delayed: bool
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "type": "price",
            "symbol": self.symbol,
            "price": self.price,
            "source": self.source,
            "delayed": self.delayed,
            "timestamp": self.timestamp.isoformat(),
        }


class PriceStore:

    def __init__(self):
        self._prices: dict[str, PriceUpdate] = {}
        self._subscribers: dict[str, list[Callable]] = {}
        self._lock = asyncio.Lock()

    async def update(
        self,
        symbol: str,
        price: float,
        source: str,
        delayed: bool = False,
    ):
        """Write a new price. Notifies all subscribers for this symbol."""
        update = PriceUpdate(
            symbol=symbol,
            price=price,
            source=source,
            delayed=delayed,
        )
        async with self._lock:
            self._prices[symbol] = update
            callbacks = list(self._subscribers.get(symbol, []))

        for cb in callbacks:
            try:
                await cb(update)
            except Exception as e:
                logger.debug("Subscriber callback error for %s: %s", symbol, e)

    def get(self, symbol: str) -> Optional[PriceUpdate]:
        """Get last known price. Returns None if never received."""
        return self._prices.get(symbol)

    def get_all(self) -> dict[str, PriceUpdate]:
        return dict(self._prices)

    async def subscribe(self, symbol: str, callback: Callable):
        """Register a callback to be called on every price update."""
        async with self._lock:
            if symbol not in self._subscribers:
                self._subscribers[symbol] = []
            self._subscribers[symbol].append(callback)

    async def unsubscribe(self, symbol: str, callback: Callable):
        """Remove a callback. Called when WebSocket disconnects."""
        async with self._lock:
            if symbol in self._subscribers:
                self._subscribers[symbol] = [
                    cb for cb in self._subscribers[symbol]
                    if cb != callback
                ]


# Module-level singleton — import this everywhere
price_store = PriceStore()
