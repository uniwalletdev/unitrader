"""Ephemeral pending trade confirmations for WhatsApp (TTL).

Production note: in-memory only — use Redis or DB for multi-worker deployments.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
# phone (normalized) -> {"user_id": str, "trade": dict, "deadline": monotonic}
_pending: dict[str, dict[str, Any]] = {}


def _purge_expired(now: float) -> None:
    dead = [k for k, v in _pending.items() if v.get("deadline", 0) < now]
    for k in dead:
        del _pending[k]


async def store_pending_confirmation(
    sender_phone: str,
    *,
    user_id: str,
    trade: dict,
    ttl_seconds: int = 60,
) -> None:
    """Remember a trade the user must confirm (YES/NO) within ttl_seconds."""
    phone = (sender_phone or "").strip()
    if not phone:
        return
    async with _lock:
        _purge_expired(time.monotonic())
        _pending[phone] = {
            "user_id": str(user_id),
            "trade": dict(trade),
            "deadline": time.monotonic() + max(5, int(ttl_seconds)),
        }
        logger.debug("Stored pending WhatsApp trade for %s ttl=%ss", phone, ttl_seconds)


async def get_pending_confirmation(sender_phone: str) -> dict[str, Any] | None:
    """Return pending row without removing it (for YES/NO routing)."""
    phone = (sender_phone or "").strip()
    if not phone:
        return None
    async with _lock:
        now = time.monotonic()
        _purge_expired(now)
        row = _pending.get(phone)
        if not row or row.get("deadline", 0) < now:
            return None
        return {"user_id": row["user_id"], "trade": row["trade"]}


async def pop_pending_confirmation(sender_phone: str) -> dict[str, Any] | None:
    """Pop and return {"user_id", "trade"} if a non-expired pending exists."""
    phone = (sender_phone or "").strip()
    if not phone:
        return None
    async with _lock:
        now = time.monotonic()
        _purge_expired(now)
        row = _pending.pop(phone, None)
        if not row:
            return None
        if row.get("deadline", 0) < now:
            return None
        return {"user_id": row["user_id"], "trade": row["trade"]}


async def clear_pending_confirmation(sender_phone: str) -> None:
    phone = (sender_phone or "").strip()
    if not phone:
        return
    async with _lock:
        _pending.pop(phone, None)
