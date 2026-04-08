"""Ephemeral onboarding state for WhatsApp / Telegram conversational setup.

Tracks where each external user is in the onboarding conversation:
  step 1: awaiting_ai_name   — bot asked "What should I call myself?"
  step 2: awaiting_trader_class — bot asked about trading experience
  step 3: complete            — name + class saved, ready for linking / trading

Uses the same in-memory TTL pattern as bot_pending_trade.py.
For multi-worker deployments, swap for Redis.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
# key = phone or telegram_id -> {"step": str, "data": dict, "deadline": float}
_state: dict[str, dict[str, Any]] = {}

_TTL = 30 * 60  # 30 minutes — generous for slow typers

STEP_AWAITING_AI_NAME = "awaiting_ai_name"
STEP_AWAITING_TRADER_CLASS = "awaiting_trader_class"
STEP_COMPLETE = "complete"

_TRADER_CLASS_MAP: dict[str, str] = {
    "1": "complete_novice",
    "2": "curious_saver",
    "3": "self_taught",
    "4": "experienced",
    "5": "crypto_native",
}


def _purge(now: float) -> None:
    dead = [k for k, v in _state.items() if v.get("deadline", 0) < now]
    for k in dead:
        del _state[k]


async def get_onboarding_step(sender_id: str) -> dict[str, Any] | None:
    sid = (sender_id or "").strip()
    if not sid:
        return None
    async with _lock:
        _purge(time.monotonic())
        row = _state.get(sid)
        if not row or row.get("deadline", 0) < time.monotonic():
            return None
        return {"step": row["step"], "data": row.get("data", {})}


async def set_onboarding_step(
    sender_id: str, step: str, data: dict | None = None
) -> None:
    sid = (sender_id or "").strip()
    if not sid:
        return
    async with _lock:
        _purge(time.monotonic())
        _state[sid] = {
            "step": step,
            "data": data or {},
            "deadline": time.monotonic() + _TTL,
        }


async def clear_onboarding(sender_id: str) -> None:
    sid = (sender_id or "").strip()
    if not sid:
        return
    async with _lock:
        _state.pop(sid, None)


def parse_trader_class_choice(text: str) -> str | None:
    """Parse '1'-'5' or keyword into a trader_class value."""
    t = (text or "").strip()
    if t in _TRADER_CLASS_MAP:
        return _TRADER_CLASS_MAP[t]
    low = t.lower()
    for val in _TRADER_CLASS_MAP.values():
        if val.replace("_", " ") in low or val.replace("_", "") in low:
            return val
    if "beginner" in low or "new" in low or "novice" in low:
        return "complete_novice"
    if "saver" in low or "casual" in low:
        return "curious_saver"
    if "self" in low or "taught" in low or "learn" in low:
        return "self_taught"
    if "experienced" in low or "advanced" in low or "pro" in low:
        return "experienced"
    if "crypto" in low:
        return "crypto_native"
    return None
