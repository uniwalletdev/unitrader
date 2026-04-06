"""Run web-parity chat (onboarding vs post-onboarding) for messaging bots."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import User
from src.agents.core.conversation_agent import ConversationAgent
from src.agents.orchestrator import get_orchestrator
from src.agents.shared_memory import SharedContext, SharedMemory

logger = logging.getLogger(__name__)

_UNLINKED_COPY = (
    "Hi! I don't recognise your account. Please link WhatsApp or Telegram "
    "in the Unitrader app first."
)


def _normalize_chat_result(result: object) -> str:
    if not isinstance(result, dict):
        return str(result)
    out = (result.get("message") or result.get("response") or "").strip()
    return out or "Sorry, I couldn't generate a reply."


async def orchestrator_chat_reply(
    user_id: str,
    message: str,
    *,
    db: AsyncSession | None = None,
    shared_context: SharedContext | None = None,
) -> str:
    """Same routing as POST /api/chat/message: onboarding_chat vs chat.

    Loads SharedContext once on the request session. Post-onboarding messages call
    ``ConversationAgent.handle_message`` with that context (no second load via
    ``route("chat")``). Onboarding still uses ``Orchestrator.route``.

    When ``db`` and ``shared_context`` are both provided (e.g. Telegram/WhatsApp
    after resolving the linked user in one session), skips an extra User fetch
    and ``SharedMemory.load``.
    """
    uid = str(user_id)
    text = (message or "").strip()
    if not text:
        return "Send a message to continue."

    try:
        if db is not None and shared_context is not None:
            result = await _orchestrator_chat_reply_preloaded(uid, text, db, shared_context)
        elif db is not None:
            result = await _orchestrator_chat_reply_inner(uid, text, db)
        else:
            async with AsyncSessionLocal() as db_new:
                result = await _orchestrator_chat_reply_inner(uid, text, db_new)
    except Exception as exc:
        logger.exception("orchestrator_chat_reply failed for user %s: %s", uid, exc)
        return "Sorry, I couldn't process that right now. Please try again shortly."

    return _normalize_chat_result(result)


async def _orchestrator_chat_reply_preloaded(
    uid: str,
    text: str,
    db: AsyncSession,
    shared_context: SharedContext,
) -> dict | str:
    """Chat routing when SharedContext is already loaded on ``db``."""
    if not shared_context.onboarding_complete:
        orch = get_orchestrator()
        return await orch.route(
            user_id=uid,
            action="onboarding_chat",
            payload={"message": text},
            db=db,
        )

    agent = ConversationAgent(uid)
    return await agent.handle_message(
        message=text,
        context=shared_context,
        db=db,
    )


async def _orchestrator_chat_reply_inner(
    uid: str, text: str, db: AsyncSession
) -> dict | str:
    res = await db.execute(select(User).where(User.id == uid))
    user_row = res.scalar_one_or_none()
    if not user_row:
        return _UNLINKED_COPY

    shared_context = await SharedMemory.load(uid, db)

    if not shared_context.onboarding_complete:
        orch = get_orchestrator()
        return await orch.route(
            user_id=uid,
            action="onboarding_chat",
            payload={"message": text},
            db=db,
        )

    agent = ConversationAgent(uid)
    return await agent.handle_message(
        message=text,
        context=shared_context,
        db=db,
    )
