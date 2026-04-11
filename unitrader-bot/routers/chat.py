"""
routers/chat.py — Chat API endpoints for Unitrader.

Endpoints:
    POST /api/chat/message      — Send a message and get an AI response
    GET  /api/chat/bootstrap    — Lightweight bootstrap for chat UI (connection state, ai_name)
    GET  /api/chat/history      — Retrieve conversation history
    GET  /api/chat/sentiment    — Analyse message sentiment
    POST /api/chat/rate         — Rate a conversation as helpful/not helpful
    DELETE /api/chat/history    — Clear conversation history
"""

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Conversation, OnboardingMessage
from routers.auth import get_current_user
from src.agents.core.conversation_agent import (
    ConversationAgent,
    _format_analyze_result_for_chat,
    _http_detail_str,
    _orchestrator_route,
    _resolve_symbol_for_trade_cmd,
)
from src.agents.orchestrator import get_orchestrator
from src.agents.shared_memory import SharedContext
from src.services.context_detection import (
    ALL_CONTEXTS,
    detect_context,
    detect_context_with_scores,
    get_context_label,
)
from src.services.conversation_memory import (
    analyze_sentiment,
    get_conversation_history,
    rate_conversation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Chat"])

_ACTION_ANALYSE_RE = re.compile(r"\[ACTION:ANALYSE:([A-Z0-9\-/.]+)\]", re.I)
_ACTION_TRADE_RE = re.compile(
    r"\[ACTION:TRADE:(BUY|SELL):([A-Z0-9\-/.]+)\]",
    re.I,
)


def _normalize_action_symbol(tag: str) -> tuple[str, str]:
    """Map an action-tag token (e.g. BTC-USD, AAPL) to (symbol, exchange) for trade_analyze."""
    raw = (tag or "").strip()
    if not raw:
        return "UNKNOWN", "alpaca"
    u = raw.upper()
    if "-" in u and "_" not in u:
        left, right = u.split("-", 1)
        if right in ("USD", "USDT", "EUR", "GBP"):
            if right == "USDT":
                return f"{left}USDT", "binance"
            return f"{left}/{right}", "alpaca"
    sym, ex = _resolve_symbol_for_trade_cmd(raw)
    if sym and ex:
        return sym, ex
    compact = u.replace("-", "").replace("/", "")
    if re.match(r"^[A-Z0-9]{2,20}$", compact):
        return compact, "binance"
    return u.replace("-", "/") if "-" in u else u, "alpaca"


# ─────────────────────────────────────────────
# GET /api/chat/bootstrap
# ─────────────────────────────────────────────

@router.get("/bootstrap")
async def chat_bootstrap(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return lightweight chat UI bootstrap (no messages).

    Used by the web chat to render the correct welcome + suggestions based on:
    - whether at least one exchange key is connected (balances/positions available)
    - the user's personalised AI name
    """
    from src.agents.shared_memory import SharedMemory

    ctx = await SharedMemory.load(current_user.id, db)
    ai_name = (ctx.ai_name or ctx.apex_name or "Apex").strip() or "Apex"
    accounts = ctx.trading_accounts or []
    has_exchange_connected = len(accounts) > 0
    exchanges = []
    for a in accounts[:5]:
        ex = str(a.get("exchange") or "unknown").lower()
        exchanges.append(ex)

    return {
        "status": "success",
        "data": {
            "ai_name": ai_name,
            "has_exchange_connected": has_exchange_connected,
            "connected_exchanges": exchanges,
            "onboarding_complete": bool(getattr(ctx, "onboarding_complete", False)),
        },
    }


async def process_chat_response(
    raw_response: str,
    context: SharedContext,
    user_message: str,
    db: AsyncSession,
) -> dict:
    """Parse Apex action tags and route to sub-agents.

    ``db`` is reserved for future persistence hooks; analysis uses a fresh session
    via ``_orchestrator_route`` to avoid conflicting with the request transaction.
    """
    del db
    del user_message

    if "[ACTION:ANALYSE:" in raw_response.upper():
        match = _ACTION_ANALYSE_RE.search(raw_response)
        if match:
            raw_sym = match.group(1)
            clean_response = raw_response.replace(match.group(0), "").strip()
            symbol, exchange = _normalize_action_symbol(raw_sym)
            try:
                analysis = await _orchestrator_route(
                    context.user_id,
                    "trade_analyze",
                    {"symbol": symbol, "exchange": exchange},
                )
                clean_response += "\n\n" + _format_analyze_result_for_chat(
                    analysis, context
                )
            except HTTPException as e:
                logger.warning(
                    "Analysis action failed for %s: %s", symbol, e.detail
                )
                clean_response += (
                    f"\n\nI tried to pull a live analysis for {raw_sym} but couldn't "
                    f"complete it ({_http_detail_str(e.detail)}). "
                    "Try the Trade / AI Trader screen for the full signal."
                )
            except Exception as e:
                logger.warning("Analysis action failed for %s: %s", raw_sym, e)
                clean_response += (
                    f"\n\nI tried to pull a live analysis for {raw_sym} but hit a "
                    "data issue. Try the AI Trader tab for the full signal."
                )
            return {"response": clean_response, "action_taken": f"analyse:{symbol}"}

    if "[ACTION:TRADE:" in raw_response.upper():
        match = _ACTION_TRADE_RE.search(raw_response)
        if match:
            side = match.group(1).lower()
            raw_sym = match.group(2)
            symbol, _ex = _normalize_action_symbol(raw_sym)
            clean_response = raw_response.replace(match.group(0), "").strip()
            return {
                "response": clean_response,
                "action_taken": f"trade_pending:{side}:{symbol}",
                "requires_confirmation": True,
                "pending_trade": {"side": side, "symbol": symbol},
            }

    return {"response": raw_response, "action_taken": None}


# ─────────────────────────────────────────────
# Request / Response bodies
# ─────────────────────────────────────────────

class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ChatStreamRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class RateConversationRequest(BaseModel):
    conversation_id: str
    is_helpful: bool


# ─────────────────────────────────────────────
# POST /api/chat/message
# ─────────────────────────────────────────────

@router.post("/message")
async def send_message(
    body: ChatMessageRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message to your AI companion and receive a context-aware response.

    The agent automatically:
    - Detects the conversation context (friendly chat, trading question, etc.)
    - Selects the appropriate tone and system prompt
    - Includes recent conversation history for continuity
    - Refers to itself by your custom AI name
    - Saves the exchange to the database
    """
    # Route to the correct agent based on whether onboarding is complete.
    # Onboarding-incomplete users get the tool-based profile-collection flow.
    # Everyone else gets the full trading conversation agent.
    from src.agents.shared_memory import SharedMemory

    ctx = await SharedMemory.load(current_user.id, db)
    if ctx.onboarding_complete:
        # Inject last 10 turns (max 20 messages) of history for continuity.
        history_rows = (
            await db.execute(
                select(OnboardingMessage)
                .where(OnboardingMessage.user_id == current_user.id)
                .order_by(OnboardingMessage.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
        history_rows = list(reversed(list(history_rows)))  # oldest -> newest
        conversation_history: list[dict[str, str]] = [
            {"role": str(row.role), "content": str(row.content)} for row in history_rows
        ]
        # Cap at 10 turns (20 messages) and trim from the oldest end if needed
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]

        agent = ConversationAgent(user_id=current_user.id)
        result = await agent.handle_message(
            message=body.message,
            context=ctx,
            db=db,
            conversation_history=conversation_history,
            channel="web",
        )
    else:
        orchestrator = get_orchestrator()
        result = await orchestrator.route(
            user_id=current_user.id,
            action="onboarding_chat",
            payload={"message": body.message, "channel": "web_app"},
            db=db,
        )

    if ctx.onboarding_complete:
        raw = (result.get("response") or result.get("message") or "").strip()
        parsed = await process_chat_response(raw, ctx, body.message, db)
        result["response"] = parsed["response"]
        result["message"] = parsed["response"]
        result["action_taken"] = parsed.get("action_taken")
        if "requires_confirmation" in parsed:
            result["requires_confirmation"] = parsed["requires_confirmation"]
        if "pending_trade" in parsed:
            result["pending_trade"] = parsed["pending_trade"]

    # Keep the existing API contract: return the conversation payload directly.
    return {"status": "success", "data": result}


# ─────────────────────────────────────────────
# POST /api/chat/stream
# ─────────────────────────────────────────────

@router.post("/stream")
async def chat_stream(
    body: ChatStreamRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream the assistant response token-by-token (web only).

    Additive endpoint; does not change /api/chat/message.
    """
    from src.agents.shared_memory import SharedMemory

    ctx = await SharedMemory.load(current_user.id, db)

    # Build conversation_history from onboarding_messages (max 20), oldest -> newest
    history_rows = (
        await db.execute(
            select(OnboardingMessage)
            .where(OnboardingMessage.user_id == current_user.id)
            .order_by(OnboardingMessage.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    history_rows = list(reversed(list(history_rows)))
    conversation_history: list[dict[str, str]] = [
        {"role": str(row.role), "content": str(row.content)} for row in history_rows
    ]
    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    agent = ConversationAgent(user_id=current_user.id)

    async def token_generator():
        partial = ""
        try:
            if not ctx.onboarding_complete:
                # Fallback: use existing onboarding chat route and yield once.
                orchestrator = get_orchestrator()
                res = await orchestrator.route(
                    user_id=current_user.id,
                    action="onboarding_chat",
                    payload={"message": body.message, "channel": "web"},
                    db=db,
                )
                text = (res.get("message") or res.get("response") or "").strip()
                yield text
                return

            async for token in agent.generate_response_stream(
                user_message=body.message,
                shared_context=ctx,
                conversation_history=conversation_history,
                channel="web",
                db=db,
            ):
                partial += token
                yield token
        except Exception as e:
            logger.error(f"Chat stream error: {e}", exc_info=True)
            if partial:
                yield "\n\nResponse interrupted. Please try again."
            else:
                yield "Response interrupted. Please try again."

    return StreamingResponse(token_generator(), media_type="text/plain")


# ─────────────────────────────────────────────
# GET /api/chat/history
# ─────────────────────────────────────────────

@router.get("/history")
async def get_history(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    context: str | None = Query(
        None,
        description=f"Filter by context. One of: {', '.join(ALL_CONTEXTS)}",
    ),
):
    """Return conversation history for the authenticated user.

    Ordered oldest → newest. Optionally filter by context type.
    """
    if context and context not in ALL_CONTEXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid context. Valid options: {ALL_CONTEXTS}",
        )

    conversations = await get_conversation_history(
        user_id=current_user.id,
        limit=limit,
        context_filter=context,
        db=db,
    )

    return {
        "status": "success",
        "data": {
            "count": len(conversations),
            "conversations": [_conv_to_dict(c) for c in conversations],
        },
    }


# ─────────────────────────────────────────────
# GET /api/chat/sentiment
# ─────────────────────────────────────────────

@router.get("/sentiment")
async def get_sentiment(
    message: str = Query(..., min_length=1, max_length=4000),
    current_user=Depends(get_current_user),
):
    """Analyse the sentiment of a given message.

    Returns sentiment classification along with the detected context,
    useful for debugging the context detection engine.
    """
    sentiment = analyze_sentiment(message)
    context = detect_context(message)
    scores = detect_context_with_scores(message)

    # Only show non-zero scores
    top_scores = {k: v for k, v in sorted(scores.items(), key=lambda x: -x[1]) if v > 0}

    return {
        "status": "success",
        "data": {
            "message": message,
            "sentiment": sentiment,
            "detected_context": context,
            "context_label": get_context_label(context),
            "context_scores": top_scores,
        },
    }


# ─────────────────────────────────────────────
# POST /api/chat/rate
# ─────────────────────────────────────────────

@router.post("/rate")
async def rate_message(
    body: RateConversationRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rate an AI response as helpful or not helpful.

    Ratings are stored and will be used to improve future responses.
    """
    recorded = await rate_conversation(
        user_id=current_user.id,
        conversation_id=body.conversation_id,
        is_helpful=body.is_helpful,
        db=db,
    )
    if not recorded:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    return {
        "status": "success",
        "data": {
            "message": "Thank you for your feedback!",
            "conversation_id": body.conversation_id,
            "is_helpful": body.is_helpful,
        },
    }


# ─────────────────────────────────────────────
# DELETE /api/chat/history
# ─────────────────────────────────────────────

@router.delete("/history")
async def clear_history(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete all conversation history for the authenticated user.

    This action cannot be undone.
    """
    result = await db.execute(
        select(Conversation).where(Conversation.user_id == current_user.id)
    )
    conversations = result.scalars().all()
    count = len(conversations)

    for conv in conversations:
        await db.delete(conv)

    logger.info("Cleared %d conversations for user %s", count, current_user.id)

    return {
        "status": "success",
        "data": {"message": f"Deleted {count} conversations", "count": count},
    }


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def _conv_to_dict(conv: Conversation) -> dict:
    return {
        "id": conv.id,
        "message": conv.message,
        "response": conv.response,
        "context": conv.context_type,
        "context_label": get_context_label(conv.context_type),
        "sentiment": conv.sentiment,
        "is_helpful": conv.is_helpful,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
    }
