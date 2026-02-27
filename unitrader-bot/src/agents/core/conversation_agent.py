"""
src/agents/core/conversation_agent.py — Multi-context AI conversation agent.

Automatically detects the user's intent, selects the appropriate tone,
injects short-term memory from conversation history, and responds using
the user's personalised AI name throughout.
"""

import asyncio
import logging
from datetime import datetime, timezone

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import Trade, User
from src.services.context_detection import (
    AI_PERFORMANCE,
    EDUCATIONAL,
    EMOTIONAL_SUPPORT,
    FRIENDLY_CHAT,
    GENERAL,
    MARKET_ANALYSIS,
    TECHNICAL_HELP,
    TRADING_QUESTION,
    detect_context,
)
from src.services.conversation_memory import (
    analyze_sentiment,
    get_recent_messages_for_claude,
    save_conversation,
)

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-3-haiku-20240307"
_MAX_TOKENS = 1024
_HISTORY_TURNS = 10  # number of past exchanges to include


# ─────────────────────────────────────────────
# System prompts — one per context
# ─────────────────────────────────────────────

def _build_system_prompt(context: str, ai_name: str, user_email: str) -> str:
    """Return the system prompt for a given context, personalised with the AI name."""

    base = (
        f"You are {ai_name}, a personal AI trading companion for {user_email}. "
        f"Always refer to yourself as {ai_name}. "
        f"Never refer to yourself as 'the bot', 'the AI', or 'Claude'. "
    )

    context_prompts = {

        FRIENDLY_CHAT: (
            f"{base}"
            "The user is excited, celebrating, or just being friendly. "
            "Match their energy — be warm, enthusiastic, and conversational. "
            "Use emojis generously. Celebrate their wins. "
            "Keep responses short (2–4 sentences), engaging, and fun. "
            "Reference their trading achievements when relevant."
        ),

        TRADING_QUESTION: (
            f"{base}"
            "The user is asking for trading advice or a recommendation. "
            "Be analytical and data-driven. Always include: "
            "(1) a clear recommendation with a confidence level (0–100%), "
            "(2) the key reasoning behind it, "
            "(3) a brief risk assessment with stop-loss suggestion. "
            "Never guarantee profits. Always remind them that all trading carries risk. "
            "Format: Recommendation → Reasoning → Risk."
        ),

        TECHNICAL_HELP: (
            f"{base}"
            "The user has a technical problem or needs help with a feature. "
            "Be patient, clear, and methodical. "
            "Give numbered step-by-step instructions. "
            "Explain technical concepts in plain language — no jargon without explanation. "
            "If the first solution might not work, offer an alternative. "
            "End with an invitation to ask follow-up questions."
        ),

        MARKET_ANALYSIS: (
            f"{base}"
            "The user wants a professional market analysis. "
            "Be objective and thorough. Cover: "
            "(1) current price action and trend, "
            "(2) key support and resistance levels, "
            "(3) relevant technical indicators (RSI, MACD, MAs), "
            "(4) macro factors or sentiment if relevant, "
            "(5) your balanced outlook. "
            "Never make absolute price predictions. "
            "Present multiple scenarios (bullish / bearish / neutral)."
        ),

        AI_PERFORMANCE: (
            f"{base}"
            "The user is asking about trading results or performance metrics. "
            "Be honest, transparent, and supportive. "
            "Highlight wins clearly with specific figures. "
            "For losses, explain what happened objectively without making excuses. "
            "Identify patterns in the data. "
            "Suggest concrete improvements for future trades. "
            "End on an encouraging note that focuses on long-term growth."
        ),

        EDUCATIONAL: (
            f"{base}"
            "The user wants to learn about trading or a related concept. "
            "Be a patient, encouraging educator. "
            "Start from the basics and build up. "
            "Use real-world analogies and simple examples. "
            "Break complex topics into digestible steps. "
            "Anticipate follow-up questions and briefly address them. "
            "End with a 'What to explore next' suggestion."
        ),

        EMOTIONAL_SUPPORT: (
            f"{base}"
            "The user is frustrated, worried, or emotionally stressed about trading. "
            "Be empathetic and human first — acknowledge their feelings before anything else. "
            "Normalise their emotions (losses happen to everyone, even professionals). "
            "Gently put things in perspective with concrete context. "
            "Reference any past wins to remind them of their progress. "
            "Encourage long-term thinking over short-term results. "
            "Never dismiss their concerns or lecture them. "
            "Keep the tone calm, warm, and reassuring."
        ),

        GENERAL: (
            f"{base}"
            "The user has a general question or message. "
            "Be helpful, friendly, and professional. "
            "Adapt your tone naturally to match theirs. "
            "Be concise — don't over-explain. "
            "If trading-related, bring in your expertise. "
            "If off-topic, be helpful and gently steer back to how you can assist them."
        ),
    }

    return context_prompts.get(context, context_prompts[GENERAL])


# ─────────────────────────────────────────────
# Performance context injection
# ─────────────────────────────────────────────

async def _get_performance_summary(user_id: str, db: AsyncSession) -> str:
    """Build a compact performance summary to inject when context is AI_PERFORMANCE."""
    result = await db.execute(
        select(Trade)
        .where(Trade.user_id == user_id, Trade.status == "closed")
        .order_by(Trade.closed_at.desc())
        .limit(20)
    )
    trades = result.scalars().all()

    if not trades:
        return "No closed trades yet."

    wins = [t for t in trades if (t.profit or 0) > 0]
    losses = [t for t in trades if (t.loss or 0) > 0]
    win_rate = len(wins) / len(trades) * 100

    total_profit = sum(t.profit or 0 for t in wins)
    total_loss = sum(t.loss or 0 for t in losses)
    net = total_profit - total_loss

    return (
        f"Recent performance (last {len(trades)} trades): "
        f"Win rate {win_rate:.0f}%, "
        f"Net P&L ${net:+.2f}, "
        f"Total profit ${total_profit:.2f}, "
        f"Total loss ${total_loss:.2f}."
    )


# ─────────────────────────────────────────────
# Conversation Agent
# ─────────────────────────────────────────────

class ConversationAgent:
    """Multi-context AI conversation agent personalised per user.

    Usage:
        agent = ConversationAgent(user_id="...")
        result = await agent.respond("Should I buy BTC now?")
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def respond(
        self,
        user_message: str,
        db: AsyncSession | None = None,
    ) -> dict:
        """Process a user message and return an AI response.

        Steps:
        1. Load user profile (AI name, subscription).
        2. Detect conversation context.
        3. Analyse sentiment.
        4. Fetch short-term memory (last N turns).
        5. Optionally inject performance data.
        6. Build the Claude prompt and call the API.
        7. Persist the exchange to the database.
        8. Return structured response.

        Args:
            user_message: The raw text from the user.
            db: Optional injected AsyncSession (for request-scoped sessions).

        Returns:
            {
                "response": str,
                "context": str,
                "context_label": str,
                "sentiment": str,
                "user_ai_name": str,
                "conversation_id": str,
                "timestamp": str,
            }
        """
        if not settings.anthropic_api_key:
            return self._fallback_response(user_message)

        # ── Load user profile ──────────────────────────────────────────────
        async with AsyncSessionLocal() as _db:
            user_result = await _db.execute(
                select(User).where(User.id == self.user_id)
            )
            user = user_result.scalar_one_or_none()

        if not user:
            return self._fallback_response(user_message, reason="User not found")

        ai_name = user.ai_name or "Claude"

        # ── Detect context & sentiment ─────────────────────────────────────
        context = detect_context(user_message)
        sentiment = analyze_sentiment(user_message)

        # ── Build message history for Claude ──────────────────────────────
        history = await get_recent_messages_for_claude(
            self.user_id, limit=_HISTORY_TURNS, db=db
        )

        # ── Inject performance summary if relevant ─────────────────────────
        system_prompt = _build_system_prompt(context, ai_name, user.email)

        if context == AI_PERFORMANCE:
            async with AsyncSessionLocal() as _db2:
                perf = await _get_performance_summary(self.user_id, _db2)
            system_prompt += f"\n\nCURRENT PERFORMANCE DATA:\n{perf}"

        # ── Build Claude messages ──────────────────────────────────────────
        messages = [*history, {"role": "user", "content": user_message}]

        # ── Call Claude ────────────────────────────────────────────────────
        try:
            claude_response = await self._claude.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system_prompt,
                messages=messages,
            )
            response_text = claude_response.content[0].text.strip()
        except Exception as exc:
            logger.error("Claude API error in ConversationAgent: %s", exc)
            return self._fallback_response(user_message, reason=str(exc))

        # ── Persist ────────────────────────────────────────────────────────
        conv = await save_conversation(
            user_id=self.user_id,
            message=user_message,
            response=response_text,
            context=context,
            sentiment=sentiment,
            db=db,
        )

        from src.services.context_detection import get_context_label

        return {
            "response": response_text,
            "context": context,
            "context_label": get_context_label(context),
            "sentiment": sentiment,
            "user_ai_name": ai_name,
            "conversation_id": conv.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ─────────────────────────────────────────
    # Fallback
    # ─────────────────────────────────────────

    def _fallback_response(
        self, user_message: str, reason: str = "AI not configured"
    ) -> dict:
        """Return a graceful fallback when the Claude API is unavailable."""
        from src.services.context_detection import GENERAL, get_context_label

        return {
            "response": (
                "I'm having trouble connecting right now. Please check that your "
                "Anthropic API key is configured and try again."
            ),
            "context": GENERAL,
            "context_label": get_context_label(GENERAL),
            "sentiment": analyze_sentiment(user_message),
            "user_ai_name": "Claude",
            "conversation_id": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": reason,
        }
