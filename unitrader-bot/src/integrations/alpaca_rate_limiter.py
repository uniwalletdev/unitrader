"""
Global Alpaca rate limiter.
Alpaca free tier: ~200 requests/minute = ~3.3/second.
We target 2.5/second (150/min) to stay safely under the limit.
All Alpaca HTTP calls must pass through acquire() before firing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AlpacaRateLimiter:
    """
    Token bucket rate limiter.
    Allows bursts up to `burst` tokens, refills at `rate` tokens/second.
    All callers share a single instance via module-level singleton.
    """

    def __init__(self, rate: float = 2.5, burst: int = 8):
        self.rate = rate  # tokens per second
        self.burst = burst  # max burst size
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._waiters = 0

    async def acquire(self) -> None:
        """
        Block until a token is available.
        Call this before every Alpaca HTTP request.
        """
        while True:
            wait_time = 0.0
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_time = max((1.0 - self._tokens) / self.rate, 1e-3)
                self._waiters += 1
                logger.debug(
                    "Alpaca rate limiter: waiting %.2fs (tokens=%.2f, waiters=%d)",
                    wait_time,
                    self._tokens,
                    self._waiters,
                )
            await asyncio.sleep(wait_time)
            async with self._lock:
                self._waiters = max(0, self._waiters - 1)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            float(self.burst),
            self._tokens + elapsed * self.rate,
        )
        self._last_refill = now

    @property
    def waiting(self) -> int:
        return self._waiters

    @property
    def tokens(self) -> float:
        """Approximate available tokens (for health checks; refreshed on next acquire)."""
        self._refill()
        return round(self._tokens, 4)


# Module-level singleton — import this everywhere
alpaca_limiter = AlpacaRateLimiter(rate=2.5, burst=8)

# Kraken public API: ~1 call/second — separate bucket so Alpaca limits stay independent.
kraken_limiter = AlpacaRateLimiter(rate=1.0, burst=3)


async def alpaca_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """
    Convenience wrapper: acquire rate limit token, then fire request.
    Use this instead of calling client.get() / client.request() directly.

    Example:
        response = await alpaca_request(httpx_client, "GET", url, headers=headers)
    """
    await alpaca_limiter.acquire()
    m = method.lower()
    fn = getattr(client, m, None)
    if fn is None:
        raise ValueError(f"Unsupported HTTP method: {method}")
    return await fn(url, **kwargs)
