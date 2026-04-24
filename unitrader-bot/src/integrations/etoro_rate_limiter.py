"""
Global eToro rate limiter — dual-bucket (read / write).

eToro's public API documents separate ceilings for read-heavy market-data
endpoints and write-heavy order endpoints:

    • Read bucket  — 60 req/sec sustained, burst of 10
    • Write bucket — ~20 req/sec sustained, burst of 3

Every eToro HTTP call must ``await get_etoro_limiter().acquire(is_write=...)``
before firing. Mirrors the token-bucket pattern in ``alpaca_rate_limiter.py``
so behaviour is consistent across venues.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class _Bucket:
    """Single token bucket. Shared implementation for read + write lanes."""

    def __init__(self, rate: float, burst: int, name: str):
        self.rate = float(rate)
        self.burst = int(burst)
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._waiters = 0
        self._name = name

    async def acquire(self) -> None:
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
                    "eToro[%s] rate limiter: waiting %.2fs (tokens=%.2f, waiters=%d)",
                    self._name,
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
    def tokens(self) -> float:
        self._refill()
        return round(self._tokens, 4)

    @property
    def waiting(self) -> int:
        return self._waiters


class EtoroRateLimiter:
    """Dual-bucket limiter — separate read and write lanes."""

    def __init__(
        self,
        read_rate: float = 60.0,
        read_burst: int = 10,
        write_rate: float = 20.0,
        write_burst: int = 3,
    ):
        self.read_bucket = _Bucket(read_rate, read_burst, "read")
        self.write_bucket = _Bucket(write_rate, write_burst, "write")

    async def acquire(self, is_write: bool = False) -> None:
        """Block until a token from the appropriate bucket is available.

        Call this before every eToro HTTP request. Pass ``is_write=True``
        for order-placing / order-cancelling / account-mutating endpoints.
        """
        bucket = self.write_bucket if is_write else self.read_bucket
        await bucket.acquire()

    @property
    def read_tokens(self) -> float:
        return self.read_bucket.tokens

    @property
    def write_tokens(self) -> float:
        return self.write_bucket.tokens


# Module-level singleton — import-once, shared everywhere.
_etoro_limiter = EtoroRateLimiter()


def get_etoro_limiter() -> EtoroRateLimiter:
    """Return the process-wide eToro rate-limiter singleton."""
    return _etoro_limiter
