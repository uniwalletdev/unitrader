"""Token-bucket rate limiter for per-agent throttling.

Each agent has a `tokens_per_minute` budget that refills every 60 seconds.
Backed by the `agent_rate_limits` table but cached in-memory for <1ms checks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AgentRateLimit

logger = logging.getLogger(__name__)


@dataclass
class _BucketState:
    tokens_per_minute: int
    tokens_used: int = 0
    last_reset_ts: float = field(default_factory=time.monotonic)
    priority: str = "p1"


class TokenRateLimiter:
    """In-memory token-bucket with periodic DB sync.

    Buckets reset every 60 seconds. `acquire()` is fast (O(1), no DB hit
    on the hot path once warmed). `flush_to_db()` is called by the
    scheduler to persist usage counters for dashboards.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _BucketState] = {}
        self._lock = asyncio.Lock()

    async def _load_config(self, db: AsyncSession, agent_name: str) -> _BucketState:
        """Load agent rate-limit config from DB (cached afterwards)."""
        result = await db.execute(
            select(AgentRateLimit).where(AgentRateLimit.agent_name == agent_name)
        )
        row = result.scalar_one_or_none()
        if row is None:
            # Agent not seeded — use safe defaults and warn.
            logger.warning(
                "RateLimiter: agent '%s' not in agent_rate_limits — using defaults",
                agent_name,
            )
            return _BucketState(tokens_per_minute=2000, priority="p1")
        return _BucketState(
            tokens_per_minute=row.tokens_per_minute,
            priority=row.priority,
        )

    def _reset_if_elapsed(self, bucket: _BucketState) -> None:
        """Reset the bucket if >=60s since last reset."""
        now = time.monotonic()
        if now - bucket.last_reset_ts >= 60.0:
            bucket.tokens_used = 0
            bucket.last_reset_ts = now

    async def acquire(
        self,
        db: AsyncSession,
        agent_name: str,
        tokens_needed: int,
    ) -> tuple[bool, str]:
        """Attempt to reserve `tokens_needed` for `agent_name`.

        Returns:
            (allowed, reason) — `reason` is empty when allowed.
        """
        async with self._lock:
            bucket = self._buckets.get(agent_name)
            if bucket is None:
                bucket = await self._load_config(db, agent_name)
                self._buckets[agent_name] = bucket

            self._reset_if_elapsed(bucket)

            if bucket.tokens_used + tokens_needed > bucket.tokens_per_minute:
                return (
                    False,
                    f"rate_limit: {agent_name} used "
                    f"{bucket.tokens_used}/{bucket.tokens_per_minute} this minute",
                )
            bucket.tokens_used += tokens_needed
            return True, ""

    async def record_actual(self, agent_name: str, actual_tokens: int) -> None:
        """Adjust bucket using actual token counts returned by the API.

        Call this after the response arrives so the bucket reflects real usage
        rather than the pre-call estimate.
        """
        async with self._lock:
            bucket = self._buckets.get(agent_name)
            if bucket is None:
                return
            self._reset_if_elapsed(bucket)
            bucket.tokens_used = max(0, actual_tokens)

    async def reset_all_buckets(self) -> None:
        """Manually reset every in-memory bucket (called by scheduler)."""
        async with self._lock:
            now = time.monotonic()
            for bucket in self._buckets.values():
                bucket.tokens_used = 0
                bucket.last_reset_ts = now

    async def flush_to_db(self, db: AsyncSession) -> None:
        """Persist current bucket usage to agent_rate_limits for observability."""
        async with self._lock:
            snapshot = list(self._buckets.items())

        now = datetime.now(timezone.utc)
        for agent_name, bucket in snapshot:
            try:
                result = await db.execute(
                    select(AgentRateLimit).where(
                        AgentRateLimit.agent_name == agent_name
                    )
                )
                row = result.scalar_one_or_none()
                if row is None:
                    continue
                row.tokens_used_this_minute = bucket.tokens_used
                row.last_reset = now
            except Exception as exc:
                logger.warning("RateLimiter: flush failed for %s: %s", agent_name, exc)
        try:
            await db.commit()
        except Exception as exc:
            logger.warning("RateLimiter: commit failed: %s", exc)
            await db.rollback()


# Singleton instance
_rate_limiter: TokenRateLimiter | None = None


def get_rate_limiter() -> TokenRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = TokenRateLimiter()
    return _rate_limiter
