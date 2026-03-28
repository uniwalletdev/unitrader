"""Run web-parity chat (onboarding vs post-onboarding) for messaging bots."""

from __future__ import annotations

import logging

from database import AsyncSessionLocal
from src.agents.orchestrator import get_orchestrator
from src.agents.shared_memory import SharedMemory

logger = logging.getLogger(__name__)


async def orchestrator_chat_reply(user_id: str, message: str) -> str:
    """Same routing as POST /api/chat/message: onboarding_chat vs chat."""
    uid = str(user_id)
    text = (message or "").strip()
    if not text:
        return "Send a message to continue."

    try:
        async with AsyncSessionLocal() as db:
            ctx = await SharedMemory.load(uid, db)
            action = "chat" if ctx.onboarding_complete else "onboarding_chat"
            orch = get_orchestrator()
            result = await orch.route(
                user_id=uid,
                action=action,
                payload={"message": text},
                db=db,
            )
    except Exception as exc:
        logger.exception("orchestrator_chat_reply failed for user %s: %s", uid, exc)
        return "Sorry, I couldn't process that right now. Please try again shortly."

    if not isinstance(result, dict):
        return str(result)

    out = (result.get("message") or result.get("response") or "").strip()
    return out or "Sorry, I couldn't generate a reply."
