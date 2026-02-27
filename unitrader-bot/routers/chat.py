"""
routers/chat.py — Chat API endpoints for Unitrader.

Endpoints:
    POST /api/chat/message      — Send a message and get an AI response
    GET  /api/chat/history      — Retrieve conversation history
    GET  /api/chat/sentiment    — Analyse message sentiment
    POST /api/chat/rate         — Rate a conversation as helpful/not helpful
    DELETE /api/chat/history    — Clear conversation history
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Conversation
from routers.auth import get_current_user
from src.agents.core.conversation_agent import ConversationAgent
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


# ─────────────────────────────────────────────
# Request / Response bodies
# ─────────────────────────────────────────────

class ChatMessageRequest(BaseModel):
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
    agent = ConversationAgent(current_user.id)
    result = await agent.respond(body.message, db=db)
    return {"status": "success", "data": result}


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
