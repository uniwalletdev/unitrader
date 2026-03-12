"""
src/agents/core/conversation_agent.py — Multi-context AI conversation agent.

Automatically detects the user's intent, selects the appropriate tone,
injects short-term memory from conversation history, and responds using
the user's personalised AI name throughout.

When the user asks about a specific asset or market, the agent fetches live
price data and technical indicators and injects them into the system prompt
so responses reference real numbers.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import anthropic
from pydantic import BaseModel, Field
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

_MARKET_CONTEXTS = {TRADING_QUESTION, MARKET_ANALYSIS}


# ─────────────────────────────────────────────
# Asset extraction from free-text messages
# ─────────────────────────────────────────────

_CRYPTO_ALIASES: dict[str, str] = {
    "btc": "BTCUSDT", "bitcoin": "BTCUSDT",
    "eth": "ETHUSDT", "ethereum": "ETHUSDT",
    "sol": "SOLUSDT", "solana": "SOLUSDT",
    "bnb": "BNBUSDT",
    "xrp": "XRPUSDT", "ripple": "XRPUSDT",
    "doge": "DOGEUSDT", "dogecoin": "DOGEUSDT",
    "ada": "ADAUSDT", "cardano": "ADAUSDT",
    "dot": "DOTUSDT", "polkadot": "DOTUSDT",
    "matic": "MATICUSDT", "polygon": "MATICUSDT",
    "avax": "AVAXUSDT", "avalanche": "AVAXUSDT",
    "link": "LINKUSDT", "chainlink": "LINKUSDT",
    "ltc": "LTCUSDT", "litecoin": "LTCUSDT",
    "atom": "ATOMUSDT", "cosmos": "ATOMUSDT",
    "uni": "UNIUSDT", "uniswap": "UNIUSDT",
    "shib": "SHIBUSDT",
    "pepe": "PEPEUSDT",
}

_STOCK_TICKERS = {
    "aapl", "tsla", "googl", "goog", "amzn", "msft", "meta", "nvda",
    "amd", "nflx", "dis", "baba", "intc", "pypl", "crm", "uber",
    "shop", "sq", "snap", "coin", "pltr", "sofi", "nio", "rivn",
    "spy", "qqq", "iwm", "dia", "arkk", "voo",
}

_FOREX_RE = re.compile(
    r"\b(EUR|GBP|USD|JPY|AUD|CAD|CHF|NZD)[/_-]?"
    r"(EUR|GBP|USD|JPY|AUD|CAD|CHF|NZD)\b",
    re.IGNORECASE,
)


def _extract_assets(message: str) -> list[tuple[str, str]]:
    """Parse a user message and return ``[(symbol, exchange), ...]``.

    Handles crypto names/tickers, US stock tickers, and forex pairs.
    Returns at most 3 assets to avoid excessive API calls.
    """
    text = message.lower()
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    for alias, symbol in _CRYPTO_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            if symbol not in seen:
                found.append((symbol, "binance"))
                seen.add(symbol)

    for ticker in _STOCK_TICKERS:
        if re.search(rf"\b{re.escape(ticker)}\b", text):
            sym = ticker.upper()
            if sym not in seen:
                found.append((sym, "alpaca"))
                seen.add(sym)

    for m in _FOREX_RE.finditer(message):
        pair = f"{m.group(1).upper()}_{m.group(2).upper()}"
        if pair not in seen:
            found.append((pair, "oanda"))
            seen.add(pair)

    return found[:3]


# ─────────────────────────────────────────────
# Live market data injection
# ─────────────────────────────────────────────

async def _fetch_market_snippet(symbol: str, exchange: str) -> str | None:
    """Fetch price + indicators for one asset and format as a prompt snippet.

    Returns ``None`` on any failure so the caller can silently skip.
    """
    from src.integrations.market_data import (
        calculate_indicators,
        detect_trend,
        fetch_market_data,
        fetch_ohlcv,
    )

    try:
        snapshot = await fetch_market_data(symbol, exchange)
        price = snapshot.get("price", 0)
        change_pct = snapshot.get("price_change_pct", 0)

        closes = await fetch_ohlcv(symbol, exchange, limit=200)
        indicators: dict = {}
        trend = "unknown"
        if closes:
            indicators = calculate_indicators(closes)
            trend = detect_trend(closes)

        rsi = indicators.get("rsi", "N/A")
        macd = indicators.get("macd", {})
        macd_signal = "bullish" if macd.get("histogram", 0) > 0 else "bearish"

        return (
            f"{symbol} ({exchange}): "
            f"price ${price:,.4f}, "
            f"24h change {change_pct:+.2f}%, "
            f"RSI {rsi}, "
            f"MACD {macd_signal}, "
            f"trend {trend}"
        )
    except Exception as exc:
        logger.debug("Market data fetch failed for %s/%s: %s", symbol, exchange, exc)
        return None


async def _build_market_data_block(
    assets: list[tuple[str, str]],
) -> tuple[str, str | None]:
    """Fetch market data for all extracted assets concurrently.

    Returns:
        (prompt_block, data_freshness_iso)
        ``prompt_block`` is an empty string when no data could be fetched.
    """
    if not assets:
        return "", None

    tasks = [_fetch_market_snippet(sym, exch) for sym, exch in assets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    lines: list[str] = []
    for r in results:
        if isinstance(r, str):
            lines.append(r)

    if not lines:
        return "", None

    now = datetime.now(timezone.utc)
    block = (
        f"\n\nLIVE MARKET DATA (as of {now.strftime('%Y-%m-%d %H:%M UTC')}):\n"
        + "\n".join(f"• {line}" for line in lines)
        + "\n\nUse this data to give concrete, up-to-date answers. "
        "Cite specific numbers when relevant."
    )
    return block, now.isoformat()


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
        4. Extract asset mentions and fetch live market data.
        5. Fetch short-term memory (last N turns).
        6. Optionally inject performance data.
        7. Inject live market data into the system prompt.
        8. Build the Claude prompt and call the API.
        9. Persist the exchange to the database.
        10. Return structured response with ``data_freshness``.

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
                "data_freshness": str | None,
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

        # ── Extract assets and fetch live market data ──────────────────────
        assets = _extract_assets(user_message)
        data_freshness: str | None = None
        market_block = ""

        if assets or context in _MARKET_CONTEXTS:
            try:
                market_block, data_freshness = await _build_market_data_block(assets)
            except Exception as exc:
                logger.warning("Market data injection failed: %s", exc)

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

        # ── Inject live market data ────────────────────────────────────────
        if market_block:
            system_prompt += market_block

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
            "data_freshness": data_freshness,
        }

    class ConversationResponse(BaseModel):
        """Orchestrator-enriched conversation response."""

        message: str
        context_used: list[str] = Field(default_factory=list)
        suggested_actions: list[str] | None = None
        market_data_freshness: datetime | None = None

    async def respond_with_context(
        self,
        user_id: str,
        message: str,
        conversation_history: list,
        market_context: dict,
        portfolio_context: dict,
        agent_insights: dict,
    ) -> dict:
        """Respond to a user message using orchestrator-provided context.

        Keeps existing context detection + sentiment + persistence logic intact,
        but adds an extra injection layer before the Claude API call.

        Returns a dict compatible with the existing API contract (includes
        ``response``) and adds:
          - context_used
          - suggested_actions
          - market_data_freshness
        """
        self.user_id = user_id or self.user_id

        if not settings.anthropic_api_key:
            r = self._fallback_response(message)
            r.update(
                {
                    "context_used": [],
                    "suggested_actions": None,
                    "market_data_freshness": None,
                }
            )
            return r

        # Load user profile (AI name)
        async with AsyncSessionLocal() as _db:
            user_result = await _db.execute(select(User).where(User.id == self.user_id))
            user = user_result.scalar_one_or_none()
        if not user:
            r = self._fallback_response(message, reason="User not found")
            r.update({"context_used": [], "suggested_actions": None, "market_data_freshness": None})
            return r

        ai_name = user.ai_name or "Claude"

        # Existing context & sentiment detection
        context = detect_context(message)
        sentiment = analyze_sentiment(message)

        system_prompt = _build_system_prompt(context, ai_name, user.email)

        # Performance injection unchanged
        if context == AI_PERFORMANCE:
            async with AsyncSessionLocal() as _db2:
                perf = await _get_performance_summary(self.user_id, _db2)
            system_prompt += f"\n\nCURRENT PERFORMANCE DATA:\n{perf}"

        context_used: list[str] = ["conversation_history"]

        # Inject orchestrator context layers
        if market_context:
            context_used.append("market_context")
            system_prompt += (
                "\n\nLIVE MARKET CONTEXT (from orchestrator):\n"
                + "\n".join(f"- {k}: {v}" for k, v in list(market_context.items())[:20])
            )

        if portfolio_context:
            context_used.append("portfolio_context")
            system_prompt += (
                "\n\nPORTFOLIO CONTEXT (from DB):\n"
                + "\n".join(f"- {k}: {v}" for k, v in list(portfolio_context.items())[:20])
            )

        if agent_insights:
            context_used.append("agent_insights")
            system_prompt += (
                "\n\nAGENT INSIGHTS (shared intelligence from other agents):\n"
                + "\n".join(f"- {k}: {v}" for k, v in list(agent_insights.items())[:30])
            )

        # Build Claude messages
        history = conversation_history or []
        messages = [*history, {"role": "user", "content": message}]

        # Call Claude
        try:
            claude_response = await self._claude.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system_prompt,
                messages=messages,
            )
            response_text = claude_response.content[0].text.strip()
        except Exception as exc:
            logger.error("Claude API error in respond_with_context: %s", exc)
            r = self._fallback_response(message, reason=str(exc))
            r.update({"context_used": context_used, "suggested_actions": None, "market_data_freshness": None})
            return r

        # Persist conversation (same as respond)
        conv = await save_conversation(
            user_id=self.user_id,
            message=message,
            response=response_text,
            context=context,
            sentiment=sentiment,
            db=None,  # persist via internal session management
        )

        from src.services.context_detection import get_context_label

        # Market data freshness extraction (best-effort)
        freshness: datetime | None = None
        ts = market_context.get("timestamp") if isinstance(market_context, dict) else None
        if isinstance(ts, datetime):
            freshness = ts
        elif isinstance(ts, str):
            try:
                freshness = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                freshness = None

        return {
            "response": response_text,
            "context": context,
            "context_label": get_context_label(context),
            "sentiment": sentiment,
            "user_ai_name": ai_name,
            "conversation_id": getattr(conv, "id", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # existing field (kept)
            "data_freshness": market_context.get("timestamp") if isinstance(market_context, dict) else None,
            # new fields
            "message": message,
            "context_used": context_used,
            "suggested_actions": None,
            "market_data_freshness": freshness,
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
            "data_freshness": None,
            "error": reason,
        }
