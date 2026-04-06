"""Run web-parity chat (onboarding vs post-onboarding) for messaging bots."""

from __future__ import annotations

import logging
import re
from typing import Any

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


def whatsapp_plain_chat_text(text: str) -> str:
    """Strip **bold** (and simple *italic*) for WhatsApp plain text."""
    if not text:
        return ""
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", text, flags=re.DOTALL)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", t)
    return t


def _normalize_chat_result(result: object) -> str:
    if not isinstance(result, dict):
        return str(result)
    out = (result.get("message") or result.get("response") or "").strip()
    return out or "Sorry, I couldn't generate a reply."


async def _merge_process_chat_response(
    result: dict,
    uid: str,
    user_message: str,
    db: AsyncSession,
    shared_context: SharedContext,
) -> dict:
    """Apply same [ACTION:...] parsing as POST /api/chat/message."""
    if not shared_context.onboarding_complete:
        return result
    raw = (result.get("response") or result.get("message") or "").strip()
    if not raw:
        return result
    from routers.chat import process_chat_response

    parsed = await process_chat_response(raw, shared_context, user_message, db)
    result["response"] = parsed["response"]
    result["message"] = parsed["response"]
    result["action_taken"] = parsed.get("action_taken")
    if "requires_confirmation" in parsed:
        result["requires_confirmation"] = parsed["requires_confirmation"]
    if "pending_trade" in parsed:
        result["pending_trade"] = parsed["pending_trade"]
    return result


async def orchestrator_chat_with_actions(
    user_id: str,
    message: str,
    *,
    db: AsyncSession | None = None,
    shared_context: SharedContext | None = None,
    channel: str = "web_app",
) -> dict[str, Any]:
    """Web-parity chat plus ``process_chat_response`` (action tags).

    Returns:
        {
          "text": str,
          "action_taken": str | None,
          "requires_confirmation": bool | None,
          "pending_trade": dict | None,
          "raw": dict (full agent payload),
        }
    """
    uid = str(user_id)
    text = (message or "").strip()
    if not text:
        return {
            "text": "Send a message to continue.",
            "action_taken": None,
            "requires_confirmation": None,
            "pending_trade": None,
            "raw": {},
        }

    merge_db: AsyncSession | None = None
    sc_merge: SharedContext | None = None

    try:
        if db is not None and shared_context is not None:
            raw = await _orchestrator_chat_reply_preloaded(uid, text, db, shared_context)
            merge_db, sc_merge = db, shared_context
        elif db is not None:
            raw = await _orchestrator_chat_reply_inner(uid, text, db, channel=channel)
            merge_db = db
            sc_merge = None
        else:
            async with AsyncSessionLocal() as db_new:
                raw = await _orchestrator_chat_reply_inner(
                    uid, text, db_new, channel=channel
                )
                merge_db = db_new
                sc_merge = None
                if not isinstance(raw, dict):
                    out = str(raw)
                    return {
                        "text": out,
                        "action_taken": None,
                        "requires_confirmation": None,
                        "pending_trade": None,
                        "raw": {"_non_dict": out},
                    }
                merged = dict(raw)
                if sc_merge is None:
                    sc_merge = await SharedMemory.load(uid, merge_db)
                merged = await _merge_process_chat_response(
                    merged, uid, text, merge_db, sc_merge
                )
                reply = (merged.get("response") or merged.get("message") or "").strip()
                if not reply:
                    reply = "Sorry, I couldn't generate a reply."
                return {
                    "text": reply,
                    "action_taken": merged.get("action_taken"),
                    "requires_confirmation": merged.get("requires_confirmation"),
                    "pending_trade": merged.get("pending_trade"),
                    "raw": merged,
                }
    except Exception as exc:
        logger.exception("orchestrator_chat_with_actions failed for user %s: %s", uid, exc)
        return {
            "text": "Sorry, I couldn't process that right now. Please try again shortly.",
            "action_taken": None,
            "requires_confirmation": None,
            "pending_trade": None,
            "raw": {},
        }

    if not isinstance(raw, dict):
        out = str(raw)
        return {
            "text": out,
            "action_taken": None,
            "requires_confirmation": None,
            "pending_trade": None,
            "raw": {"_non_dict": out},
        }

    merged = dict(raw)
    if merge_db is not None:
        if sc_merge is None:
            sc_merge = await SharedMemory.load(uid, merge_db)
        merged = await _merge_process_chat_response(
            merged, uid, text, merge_db, sc_merge
        )

    reply = (merged.get("response") or merged.get("message") or "").strip()
    if not reply:
        reply = "Sorry, I couldn't generate a reply."

    return {
        "text": reply,
        "action_taken": merged.get("action_taken"),
        "requires_confirmation": merged.get("requires_confirmation"),
        "pending_trade": merged.get("pending_trade"),
        "raw": merged,
    }


async def orchestrator_chat_reply(
    user_id: str,
    message: str,
    *,
    db: AsyncSession | None = None,
    shared_context: SharedContext | None = None,
    channel: str = "web_app",
) -> str:
    """Same routing as POST /api/chat/message: onboarding_chat vs chat (text only)."""
    data = await orchestrator_chat_with_actions(
        user_id, message, db=db, shared_context=shared_context, channel=channel
    )
    return data["text"]


async def _orchestrator_chat_reply_preloaded(
    uid: str,
    text: str,
    db: AsyncSession,
    shared_context: SharedContext,
    *,
    channel: str = "web_app",
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
        channel=channel,
    )


async def _orchestrator_chat_reply_inner(
    uid: str, text: str, db: AsyncSession, *, channel: str = "web_app"
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
        channel=channel,
    )
