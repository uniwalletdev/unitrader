"""
src/services/conversation_memory.py — Conversation persistence and sentiment analysis.

Handles saving/loading conversation history from the database and provides a
lightweight rule-based sentiment classifier that requires no external dependencies.
"""

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import Conversation

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Sentiment Analysis
# ─────────────────────────────────────────────

_POSITIVE_PATTERNS = [
    r"\bgreat\b", r"\bawesome\b", r"\bgood\b", r"\bexcellent\b",
    r"\bfantastic\b", r"\bperfect\b", r"\blove\b", r"\bhappy\b",
    r"\bprofit\b", r"\bwin\b", r"\bwon\b", r"\bgain\b", r"\bup\b",
    r"\bthank", r"\bthanks\b", r"\bappreciat", r"\bcongrat",
    r"🎉|🚀|🙌|🥳|💪|😍|🔥|✅|⬆️",
]

_NEGATIVE_PATTERNS = [
    r"\bbad\b", r"\bterrible\b", r"\bawful\b", r"\bworst\b",
    r"\bloss\b", r"\blose\b", r"\blost\b", r"\bdown\b",
    r"\bfail", r"\bwrong\b", r"\berror\b", r"\bbroken\b",
    r"\bfrustrat", r"\bupset\b", r"\bworri", r"\bscared\b",
    r"\banxi", r"\bstress", r"\bdisappoint",
    r"😞|😢|😭|😟|😔|😰|🙁|❌|⬇️",
]

_INTENSIFIERS = [r"\bvery\b", r"\breally\b", r"\bso\b", r"\bextremely\b", r"\bsuper\b"]


def analyze_sentiment(message: str) -> str:
    """Classify message sentiment as 'positive', 'negative', or 'neutral'.

    Uses weighted keyword scoring with intensifier detection.
    Each positive/negative keyword scores 1 point; intensifiers multiply
    the nearest keyword score by 1.5.

    Args:
        message: User message text.

    Returns:
        'positive' | 'negative' | 'neutral'
    """
    text = message.lower()
    positive_score = 0
    negative_score = 0

    # Check for intensifiers (boost multiplier)
    intensified = any(re.search(p, text) for p in _INTENSIFIERS)
    multiplier = 1.5 if intensified else 1.0

    for pattern in _POSITIVE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.UNICODE):
            positive_score += 1

    for pattern in _NEGATIVE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.UNICODE):
            negative_score += 1

    positive_score *= multiplier
    negative_score *= multiplier

    if positive_score > negative_score and positive_score >= 1:
        return "positive"
    if negative_score > positive_score and negative_score >= 1:
        return "negative"
    return "neutral"


# ─────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────

async def save_conversation(
    user_id: str,
    message: str,
    response: str,
    context: str,
    sentiment: str | None = None,
    db: AsyncSession | None = None,
) -> Conversation:
    """Persist a single message/response exchange to the database.

    Args:
        user_id: The authenticated user's UUID.
        message: The user's original message.
        response: The AI's response text.
        context: Detected context string (e.g. 'friendly_chat').
        sentiment: Pre-computed sentiment; if None it is computed here.
        db: Optional injected session; a new session is created if not provided.

    Returns:
        The saved Conversation ORM instance.
    """
    if sentiment is None:
        sentiment = analyze_sentiment(message)

    async def _save(session: AsyncSession) -> Conversation:
        conv = Conversation(
            user_id=user_id,
            message=message,
            response=response,
            context_type=context,
            sentiment=sentiment,
        )
        session.add(conv)
        await session.flush()
        await session.refresh(conv)
        return conv

    if db is not None:
        return await _save(db)

    async with AsyncSessionLocal() as session:
        conv = await _save(session)
        await session.commit()
        return conv


async def get_conversation_history(
    user_id: str,
    limit: int = 50,
    context_filter: str | None = None,
    db: AsyncSession | None = None,
) -> list[Conversation]:
    """Return the most recent conversations for a user, newest-last.

    Args:
        user_id: The user's UUID.
        limit: Maximum number of conversations to return (default 50).
        context_filter: If provided, only return conversations of this context type.
        db: Optional injected session.

    Returns:
        List of Conversation ORM objects, ordered oldest → newest.
    """
    async def _fetch(session: AsyncSession) -> list[Conversation]:
        query = select(Conversation).where(Conversation.user_id == user_id)
        if context_filter:
            query = query.where(Conversation.context_type == context_filter)
        query = query.order_by(Conversation.created_at.desc()).limit(limit)
        result = await session.execute(query)
        rows = result.scalars().all()
        # Reverse so that history is presented oldest → newest for the LLM
        return list(reversed(rows))

    if db is not None:
        return await _fetch(db)

    async with AsyncSessionLocal() as session:
        return await _fetch(session)


async def get_recent_messages_for_claude(
    user_id: str,
    limit: int = 10,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Return the last N conversations formatted as Claude message dicts.

    The output is ready to be prepended to the Claude messages list so Claude
    has short-term memory of the current session.

    Returns:
        [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."},
            ...
        ]
    """
    history = await get_conversation_history(user_id, limit=limit, db=db)
    messages: list[dict] = []
    for conv in history:
        messages.append({"role": "user", "content": conv.message})
        messages.append({"role": "assistant", "content": conv.response})
    return messages


async def rate_conversation(
    user_id: str,
    conversation_id: str,
    is_helpful: bool,
    db: AsyncSession,
) -> bool:
    """Record the user's helpfulness rating for a specific conversation.

    Args:
        user_id: Must match the conversation owner.
        conversation_id: UUID of the Conversation row.
        is_helpful: True = helpful, False = not helpful.
        db: Injected database session.

    Returns:
        True if the rating was recorded, False if conversation not found.
    """
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return False

    conv.is_helpful = is_helpful
    return True
