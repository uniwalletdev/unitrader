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
import uuid
from datetime import datetime, timezone
from typing import Any
from typing import Literal
from typing import Optional

import anthropic
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import Trade, User, OnboardingMessage, UserSettings
from src.agents.core.unitrader_chat_prompt import build_system_prompt
from src.agents.shared_memory import SharedContext, SharedMemory
from src.services.context_detection import (
    AI_PERFORMANCE,
    GENERAL,
    MARKET_ANALYSIS,
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

# ─────────────────────────────────────────────────────────────────────────────
# Channel-aware formatting
# ─────────────────────────────────────────────────────────────────────────────

Channel = Literal["web", "whatsapp", "telegram"]


def _normalize_channel(channel: str | None) -> Channel:
    """Map various channel names to the canonical set."""
    c = (channel or "").strip().lower()
    if c in ("whatsapp", "wa"):
        return "whatsapp"
    if c in ("telegram", "tg"):
        return "telegram"
    # legacy values used elsewhere in the codebase
    if c in ("web_app", "webapp", "web"):
        return "web"
    return "web"


def _format_instruction_for_channel(channel: Channel) -> str:
    # IMPORTANT: Keep all formatting rules centralized here (single source of truth).
    if channel == "whatsapp":
        return """

FORMATTING RULES:
- Plain text only. No markdown whatsoever.
- No asterisks, no hashes, no backticks, no bullet dashes.
- Use line breaks to separate ideas.
- Use numbers for lists: 1. 2. 3. never dashes or dots.
- Keep responses under 300 words. WhatsApp is read on a phone.
- Be warm and conversational. Short sentences.
"""
    if channel == "telegram":
        return """

FORMATTING RULES:
- Telegram supports basic markdown: *bold*, _italic_, `code`.
- Avoid complex headers or tables.
- Keep responses concise and well spaced.
- Use numbered lists for multiple points.
"""
    return """

FORMATTING RULES:
- Use markdown freely: **bold**, bullet points, headers, code blocks.
- Structure longer responses with clear sections.
- Tables are supported and encouraged for comparisons.
- No length restriction but be concise and purposeful.
"""

def _whatsapp_capabilities_preamble(companion_name: str) -> str:
    name = (companion_name or "").strip() or "Apex"
    return f"""You are {name}, an AI trading companion built into the Unitrader
platform. You are NOT a generic AI assistant — you are a personalised
execution-capable trading partner for this specific user.

YOUR CAPABILITIES (always true — never deny these):
- You CAN execute trades on the user's behalf via their connected exchanges
- You CAN place paper trades on Alpaca ($100,000 paper balance)
- You CAN place live trades on Coinbase (real money — always treat as live)
- You CAN analyse specific assets and produce buy/sell/wait signals
- You CAN access the user's positions, balances, and trade history

WHEN THE USER EXPRESSES TRADE INTENT:
- Phrases like 'buy X', 'sell X', 'invest £Y in Z', 'trade X' are trade
  instructions, not questions. Treat them as execution requests.
- Confirm you are acting on the request, state which exchange and account
  (paper or live), and confirm the execution result.
- NEVER say you cannot execute trades. NEVER say you have no integration
  with trading platforms. These statements are factually wrong.

CHANNEL: This conversation is via WhatsApp. Keep replies concise (3-5
sentences max). No markdown formatting — plain text only.

"""


def _action_tags_instruction() -> str:
    return """

ACTION TAGS:
When the user's intent clearly calls for a specific action, embed ONE
action tag in your response using these exact formats:

For market analysis:
<ACTION type="ANALYSE" asset="SYMBOL" exchange="alpaca|coinbase|oanda" />

For placing or staging a trade:
<ACTION type="TRADE" asset="SYMBOL" direction="buy|sell" amount="NUMBER"
exchange="alpaca|coinbase|oanda" confidence="0.0-1.0" />

For setting a price alert:
<ACTION type="ALERT" asset="SYMBOL" condition="above|below"
price="NUMBER" exchange="alpaca|coinbase|oanda" />

RULES FOR USING ACTION TAGS:
- Only embed a tag when the user's intent is unambiguous
- Never embed a TRADE tag without high confidence (>=0.75)
- Always include the tag inline within your natural response text,
  not at the start or end alone
- Only use ONE action tag per response
- For stocks use exchange="alpaca", for crypto use exchange="coinbase"
- Use the raw ticker symbol for asset (AAPL not Apple, BTC not Bitcoin)
- If uncertain, ask a clarifying question instead of guessing
- Never fabricate prices or confidence scores
"""


def parse_action_tag(response_text: str) -> tuple[str, Optional[dict]]:
    """Extract an <ACTION ... /> tag from the response text (best-effort)."""
    try:
        pattern = r'<ACTION\s+(.*?)/>'
        match = re.search(pattern, response_text, re.DOTALL)
        if not match:
            return response_text, None

        attr_pattern = r'(\w+)="([^"]*)"'
        attrs = dict(re.findall(attr_pattern, match.group(1)))

        clean_text = re.sub(pattern, "", response_text, flags=re.DOTALL).strip()
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text).strip()

        action = {
            "type": attrs.get("type"),
            "asset": attrs.get("asset"),
            "exchange": attrs.get("exchange"),
            "direction": attrs.get("direction"),
            "amount": attrs.get("amount"),
            "confidence": float(attrs.get("confidence", 0) or 0),
            "condition": attrs.get("condition"),
            "price": attrs.get("price"),
        }
        return clean_text, action
    except Exception:
        return response_text, None


async def dispatch_action(
    *,
    action: dict,
    user_id: str,
    shared_context: SharedContext,
    db: AsyncSession | None,
    channel: Channel,
) -> Optional[str]:
    """Dispatch a parsed action tag (best-effort, never blocks the response)."""
    try:
        action_type = (action.get("type") or "").upper()
        asset = action.get("asset")
        exchange = action.get("exchange")

        if action_type == "ANALYSE":
            from src.agents.core.trading_agent import TradingAgent

            ta = TradingAgent(user_id=user_id)
            analysis = await ta.analyze(symbol=asset, exchange=exchange, context=shared_context)
            # Best-effort stringify (TradeAnalysis is a pydantic model in this codebase)
            try:
                return analysis.model_dump_json(indent=2)  # type: ignore[attr-defined]
            except Exception:
                return str(analysis)

        if action_type == "TRADE":
            conf = float(action.get("confidence") or 0)
            direction = action.get("direction")
            amount = action.get("amount")

            if conf < 0.75:
                return (
                    f"My confidence on this trade is only {int(conf * 100)}% — not enough to proceed. "
                    "I’ll keep watching and let you know if conditions improve."
                )

            trust_stage = int(getattr(shared_context, "trust_ladder_stage", 1) or 1)
            if trust_stage < 2:
                return (
                    f"You're currently on Trust Ladder Stage {trust_stage}. "
                    "Complete paper trading milestones first to unlock live trade execution."
                )

            # This repo does not expose a safe 'stage_trade' API on TradingAgent.
            # Return a safe, user-facing next step instead of attempting execution here.
            amt = f" {amount}" if amount else ""
            return (
                f"Trade noted: {str(direction).upper()} {asset}{amt} on {exchange}. "
                "To place it, go to the AI Trader tab (or tell me your exact notional and account)."
            )

        if action_type == "ALERT":
            condition = action.get("condition")
            price = action.get("price")
            if not (asset and exchange and condition and price):
                return "I couldn't set that alert — I’m missing a price/condition. Tell me: above/below what price?"

            if db is not None:
                await db.execute(
                    text(
                        """
                        INSERT INTO price_alerts (user_id, asset, exchange, condition, target_price, active)
                        VALUES (:user_id, :asset, :exchange, :condition, :target_price, true)
                        """
                    ),
                    {
                        "user_id": user_id,
                        "asset": asset,
                        "exchange": exchange,
                        "condition": condition,
                        "target_price": float(price),
                    },
                )
                await db.commit()

            direction_word = "rises above" if condition == "above" else "falls below"
            return f"Alert set. I'll notify you when {asset} {direction_word} {price}."

    except Exception as exc:
        logger.warning("dispatch_action failed: %s", exc)
        return "I tried to run that action but hit an error. Please try again."

    return None

async def _save_onboarding_messages(
    *,
    user_id: str,
    user_message: str,
    assistant_message: str,
    db: AsyncSession | None,
) -> None:
    """Persist user+assistant messages into onboarding_messages for chat history injection."""
    async def _save(session: AsyncSession) -> None:
        session.add_all(
            [
                OnboardingMessage(
                    id=uuid.uuid4(), user_id=user_id, role="user", content=user_message
                ),
                OnboardingMessage(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    role="assistant",
                    content=assistant_message,
                ),
            ]
        )
        # Do not flush() here. Flush triggers INSERT..RETURNING id for each row and can
        # trip asyncpg/SQLAlchemy "sentinel values" mismatches when UUIDs are returned
        # as native UUID types but were passed as strings. We don't need RETURNING ids.

    try:
        if db is not None:
            await _save(db)
            return
        async with AsyncSessionLocal() as session:
            await _save(session)
            await session.commit()
    except Exception as exc:
        logger.warning("Failed to persist onboarding_messages history: %s", exc)

# ─────────────────────────────────────────────────────────────────────────────
# Trader Class Detection
# ─────────────────────────────────────────────────────────────────────────────

TRADER_CLASS_SIGNALS = {
    "crypto_native": [
        "defi",
        "nft",
        "wallet",
        "metamask",
        "altcoin",
        "bitcoin since",
        "crypto since",
    ],
    "semi_institutional": [
        "bloomberg",
        "hedge fund",
        "prop desk",
        "algo",
        "systematic",
    ],
    "experienced": [
        "years trading",
        "my strategy",
        "technical analysis",
        "broker",
        "covered calls",
    ],
    "self_taught": [
        "robinhood",
        "trading212",
        "coinbase app",
        "rsi",
        "macd",
        "chart",
        "reddit",
        "youtube",
    ],
    "curious_saver": [
        "isa",
        "index fund",
        "vanguard",
        "pension",
        "etf",
        "passive",
    ],
}


def detect_trader_class(messages: list) -> str:
    """Detect trader proficiency level from onboarding conversation messages.

    Analyzes user messages for keywords suggesting experience level.
    Returns most specific match, or "complete_novice" if no signals found.

    Args:
        messages: List of dicts with "role" and "content" keys from onboarding chat

    Returns:
        Trader class string: "crypto_native", "semi_institutional", "experienced",
        "self_taught", "curious_saver", or "complete_novice"
    """
    full_text = " ".join([m.get("content", "").lower() for m in messages if m.get("role") == "user"])

    # Check in order of specificity (most specific first)
    for cls, signals in TRADER_CLASS_SIGNALS.items():
        if any(s in full_text for s in signals):
            return cls

    return "complete_novice"



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
# Chat → Orchestrator (analysis & execution intents)
# ─────────────────────────────────────────────

_CONFIRM_TRADE_CMD_RE = re.compile(
    r"^\s*CONFIRM\s+(BUY|SELL)\s+([A-Za-z0-9./\-_]+)\s+(\d+(?:\.\d+)?)\s*$",
    re.I,
)
_PROPOSE_TRADE_CMD_RE = re.compile(
    r"^\s*(BUY|SELL)\s+([A-Za-z0-9./\-_]+)(?:\s+(\d+(?:\.\d+)?))?\s*$",
    re.I,
)


def _wants_broad_market_summary(message: str) -> bool:
    low = (message or "").lower()
    return bool(
        re.search(
            r"\b(what'?s the market|how\s*(?:'s| is) the market|markets?\s+doing|"
            r"market\s+today|overall\s+market|indices?\s+doing|how\s+are\s+stocks)\b",
            low,
        )
    )


def _infer_exchange_for_position(symbol: str, stored: str | None) -> str:
    if stored:
        return stored.lower()
    s = (symbol or "").upper()
    if "USDT" in s or "USDC" in s:
        return "binance"
    if "_" in s:
        parts = s.split("_")
        if len(parts) == 2 and all(len(p) == 3 for p in parts):
            return "oanda"
    return "alpaca"


def _primary_exchange_hint(ctx: SharedContext) -> str:
    if getattr(ctx, "market_context", None) is not None:
        return ctx.market_context.exchange.value  # type: ignore[union-attr]
    accounts = ctx.trading_accounts or []
    if accounts:
        return str(accounts[0].get("exchange") or "alpaca").lower()
    return str(ctx.exchange or "alpaca").lower()


def _resolve_symbol_for_trade_cmd(token: str) -> tuple[str | None, str | None]:
    """Map user token to (symbol, default_exchange)."""
    raw = token.strip()
    low = raw.lower()
    if low in _CRYPTO_ALIASES:
        return _CRYPTO_ALIASES[low], "binance"
    for alias, sym in _CRYPTO_ALIASES.items():
        if low == sym.lower():
            return sym, "binance"
    u = raw.upper().replace("/", "")
    if low in _STOCK_TICKERS:
        return low.upper(), "alpaca"
    m = _FOREX_RE.match(raw.upper())
    if m:
        return f"{m.group(1)}_{m.group(2)}", "oanda"
    if re.match(r"^[A-Z0-9]{2,20}$", u):
        return u, "binance"
    return None, None


def _wants_trading_agent_analysis(message: str, conv_context: str) -> bool:
    low = message.lower()
    if re.search(r"\b(analyze|analyse|analysis|outlook|deep dive|breakdown)\b", low):
        return True
    if re.search(
        r"\b(should i (buy|sell)|would you (buy|sell)|worth (buying|selling)|"
        r"opinion on|thoughts on|what do you think)\b",
        low,
    ):
        return True
    if conv_context == MARKET_ANALYSIS:
        return True
    return False


def _http_detail_str(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message", detail))
    return str(detail)


def _format_analyze_result_for_chat(result: dict, ctx: SharedContext) -> str:
    decision = result.get("decision") or "WAIT"
    if ctx.is_novice() or ctx.is_crypto_native():
        body = (result.get("simple") or result.get("expert") or "").strip()
    elif ctx.is_pro() or ctx.is_intermediate():
        body = (result.get("expert") or result.get("simple") or "").strip()
    else:
        body = (result.get("simple") or result.get("expert") or "").strip()
    parts = [f"**Signal: {decision}**"]
    if body:
        parts.append(body[:3500])
    ep = result.get("entry_price")
    if ep:
        parts.append(f"Reference price: ~${float(ep):,.4f}")
    return "\n\n".join(parts)


def _format_execute_result_for_chat(result: dict) -> str:
    if result.get("success") is False:
        return f"I couldn't place that order: {result.get('reason', 'Unknown reason')}"
    if result.get("status") == "rejected":
        return f"Order not placed: {result.get('reason', 'Unknown')}"
    if result.get("status") == "executed":
        msg = result.get("message")
        if msg:
            return str(msg)
        return (
            f"Executed {result.get('side', '')} {result.get('symbol', '')} "
            f"(trade id: {result.get('trade_id', 'n/a')})."
        )
    return str(result.get("message") or result.get("reason") or "Trade request completed.")


async def _orchestrator_route(user_id: str, action: str, payload: dict) -> dict:
    """Run one orchestrator action on a fresh DB session (avoids poisoning caller txn)."""
    from src.agents.orchestrator import get_orchestrator

    async with AsyncSessionLocal() as route_db:
        return await get_orchestrator().route(user_id, action, payload, route_db)


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


async def _build_open_positions_marks_block(
    positions: list[dict],
    *,
    max_positions: int = 10,
) -> str:
    """Mark-to-market lines for open positions (approx unrealized P&L from last price)."""
    if not positions:
        return ""
    from src.integrations.market_data import fetch_market_data

    lines: list[str] = []
    for p in positions[:max_positions]:
        sym = (p.get("symbol") or "").strip()
        if not sym:
            continue
        ex = _infer_exchange_for_position(sym, p.get("exchange"))
        entry = float(p.get("entry_price") or 0)
        qty = float(p.get("qty") or 0)
        side = str(p.get("side") or "BUY").upper()
        try:
            snap = await fetch_market_data(sym, ex)
            mark = float(snap.get("price") or 0)
        except Exception as exc:
            logger.debug("mark fetch failed for %s/%s: %s", sym, ex, exc)
            mark = 0.0
        if mark and entry and qty:
            if side == "SELL":
                upnl = (entry - mark) * qty
            else:
                upnl = (mark - entry) * qty
            upnl_s = f"${upnl:+,.2f}"
        else:
            upnl_s = "n/a"
        mark_s = f"${mark:,.4f}" if mark else "n/a"
        try:
            qty_disp = f"{qty:g}"
        except (TypeError, ValueError):
            qty_disp = str(qty)
        lines.append(
            f"- {sym} ({ex}) {side} qty {qty_disp} entry ${entry:,.4f} "
            f"last ~{mark_s} unrealized ~{upnl_s}"
        )

    if not lines:
        return ""

    now = datetime.now(timezone.utc)
    return (
        f"\n\nOPEN POSITIONS — MARK / UNREALIZED (approx., {now.strftime('%Y-%m-%d %H:%M UTC')}):\n"
        + "\n".join(lines)
        + "\n(Unrealized P&L is indicative; use exchange statements for official figures.)"
    )


# ─────────────────────────────────────────────
# System prompts — one per context
# ─────────────────────────────────────────────

_ONBOARDING_SYSTEM_PROMPT = (
    "You are Unitrader, a warm and friendly AI trading companion helping a new user set up their "
    "profile through natural conversation. Your personality: encouraging, calm, never uses jargon.\n\n"
    "Your goal is to naturally discover 4 things through conversation:\n"
    "1. Their main financial goal (map to: grow_savings / generate_income / learn_trading / crypto_focus)\n"
    "2. Their risk comfort level (map to: conservative / balanced / aggressive)\n"
    "3. Their starting budget per trade in GBP (map to a number: 25 / 50 / 100 / 250 / 500 / 1000)\n"
    "4. Which exchange to use (map to: alpaca / coinbase / oanda based on what they want to trade)\n\n"
    "Rules:\n"
    "- Ask one thing at a time. Have a real conversation. Do not list all questions at once.\n"
    "- When you've discovered a value, call extract_profile_field immediately.\n"
    "- When all 4 fields are confirmed, call complete_onboarding immediately.\n"
    "- Be warm and reassuring about risk questions. Acknowledge their feelings.\n"
    "- Never use terms like RSI, MACD, margin, or leverage.\n"
    "- Keep responses under 3 sentences."
)


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

    async def _maybe_route_trading_via_orchestrator(
        self,
        user_message: str,
        shared_ctx: SharedContext,
        conv_context: str,
    ) -> str | None:
        """Detect trade analyse / propose / confirm intents and route through MasterOrchestrator.

        Uses a dedicated DB session per orchestrator call. Returns assistant text or None
        to continue with the normal Claude path.
        """
        text = (user_message or "").strip()
        if not text:
            return None

        if shared_ctx.trading_paused:
            return None

        # ── Confirmed execution: CONFIRM BUY BTCUSDT 25 ─────────────────────
        m = _CONFIRM_TRADE_CMD_RE.match(text)
        if m:
            side = m.group(1).upper()
            raw_sym = m.group(2)
            try:
                amount = float(m.group(3))
            except ValueError:
                return None
            sym, _ex = _resolve_symbol_for_trade_cmd(raw_sym)
            if not sym:
                return f"I couldn't understand the symbol `{raw_sym}`. Try e.g. BTCUSDT or AAPL."
            if not shared_ctx.subscription_active:
                return "A subscription is required to execute trades from chat."
            try:
                result = await _orchestrator_route(
                    self.user_id,
                    "trade_execute",
                    {"symbol": sym, "side": side, "amount": amount},
                )
                return _format_execute_result_for_chat(result)
            except HTTPException as e:
                return _http_detail_str(e.detail)
            except Exception as exc:
                logger.exception("trade_execute from chat failed: %s", exc)
                return (
                    "I couldn't complete that trade right now. "
                    "Use the Trade screen in the app or try again shortly."
                )

        # ── Proposal: BUY BTCUSDT 25 (requires CONFIRM on next turn) ─────────
        m = _PROPOSE_TRADE_CMD_RE.match(text)
        if m:
            side = m.group(1).upper()
            raw_sym = m.group(2)
            amt_raw = m.group(3)
            sym, default_ex = _resolve_symbol_for_trade_cmd(raw_sym)
            if not sym:
                return f"I couldn't understand the symbol `{raw_sym}`. Try e.g. BTCUSDT or AAPL."
            if not amt_raw:
                return (
                    f"To place a **{side}** on **{sym}**, add a notional size in USD, e.g. "
                    f"`{side} {sym} 25` — then confirm with `CONFIRM {side} {sym} 25`."
                )
            try:
                amount = float(amt_raw)
            except ValueError:
                return None
            if amount <= 0:
                return "Use a positive USD amount for the trade size."

            brief = ""
            if shared_ctx.subscription_active:
                try:
                    ar = await _orchestrator_route(
                        self.user_id,
                        "trade_analyze",
                        {"symbol": sym, "exchange": default_ex},
                    )
                    brief = _format_analyze_result_for_chat(ar, shared_ctx)
                except HTTPException as e:
                    brief = f"(Analysis unavailable: {_http_detail_str(e.detail)})"
                except Exception as exc:
                    logger.warning("trade_analyze for proposal failed: %s", exc)

            lines = [
                f"You asked to **{side}** **{sym}** with **${amount:,.2f}** notional.",
                "",
                "⚠️ Trades carry risk. Review the summary below, then place the order only if you intend to.",
            ]
            if brief:
                lines.extend(["", "**Trading engine read:**", brief])
            lines.extend(
                [
                    "",
                    "To **execute**, reply on a single line exactly:",
                    f"`CONFIRM {side} {sym} {amount:g}`",
                ]
            )
            return "\n".join(lines)

        # Analyse / deep outlook: injected into the system prompt in respond() so Claude
        # can blend engine output with conversational tone (not a standalone canned reply).

        return None

    async def _build_trading_engine_context_block(
        self,
        user_message: str,
        shared_ctx: SharedContext,
        conv_context: str,
    ) -> str:
        """Run trade_analyze and format for system prompt (sentiment + trading agent)."""
        if shared_ctx.trading_paused or not shared_ctx.subscription_active:
            return ""
        assets = _extract_assets(user_message)
        if not assets or not _wants_trading_agent_analysis(user_message, conv_context):
            return ""
        symbol, exch = assets[0]
        try:
            result = await _orchestrator_route(
                self.user_id,
                "trade_analyze",
                {"symbol": symbol, "exchange": exch},
            )
        except HTTPException as e:
            return (
                "\n\nTRADING ENGINE: analysis unavailable ("
                f"{_http_detail_str(e.detail)})."
            )
        except Exception as exc:
            logger.warning("trade_analyze injection failed: %s", exc)
            return ""
        parts = [
            "\n\nTRADING ENGINE (full analysis; align your answer and cite this signal when relevant):",
            _format_analyze_result_for_chat(result, shared_ctx),
        ]
        sctx = result.get("sentiment_context")
        if sctx:
            parts.append(f"Sentiment (engine): {str(sctx)[:1200]}")
        return "\n".join(parts)

    async def respond(
        self,
        user_message: str,
        db: AsyncSession | None = None,
        shared_context: SharedContext | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        channel: Channel | str = "web",
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
            shared_context: If provided (e.g. from Orchestrator.route), used for the system
                prompt instead of loading SharedMemory again on a new session.
            channel: ``web_app`` | ``whatsapp`` | ``telegram`` — shapes prompt and output length.

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

        if shared_context is not None:
            shared_ctx = shared_context
        else:
            async with AsyncSessionLocal() as _ctx_db:
                shared_ctx = await SharedMemory.load(self.user_id, _ctx_db)

        ai_name = (
            (shared_ctx.ai_name or shared_ctx.apex_name or user.ai_name or "Apex").strip()
            or "Apex"
        )

        # ── Detect context & sentiment ─────────────────────────────────────
        context = detect_context(user_message)
        sentiment = analyze_sentiment(user_message)

        routed_reply = await self._maybe_route_trading_via_orchestrator(
            user_message, shared_ctx, context
        )
        if routed_reply is not None:
            conv = await save_conversation(
                user_id=self.user_id,
                message=user_message,
                response=routed_reply,
                context=context,
                sentiment=sentiment,
                db=db,
            )
            from src.services.context_detection import get_context_label

            return {
                "response": routed_reply,
                "context": context,
                "context_label": get_context_label(context),
                "sentiment": sentiment,
                "user_ai_name": ai_name,
                "conversation_id": conv.id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data_freshness": "orchestrator",
            }

        # ── Extract assets and fetch live market data ──────────────────────
        assets = _extract_assets(user_message)
        if not assets and _wants_broad_market_summary(user_message):
            assets = [("SPY", "alpaca"), ("BTCUSDT", "binance")]

        data_freshness: str | None = None
        market_block = ""

        if assets:
            try:
                market_block, data_freshness = await _build_market_data_block(assets)
            except Exception as exc:
                logger.warning("Market data injection failed: %s", exc)

        marks_block = ""
        if shared_ctx.open_positions:
            try:
                marks_block = await _build_open_positions_marks_block(
                    shared_ctx.open_positions
                )
            except Exception as exc:
                logger.warning("Open position marks injection failed: %s", exc)

        trading_engine_block = ""
        try:
            trading_engine_block = await self._build_trading_engine_context_block(
                user_message, shared_ctx, context
            )
        except Exception as exc:
            logger.warning("Trading engine context injection failed: %s", exc)

        # ── Build message history for Claude ──────────────────────────────
        # If the router provides an explicit history list, prefer it (and cap to 10 turns / 20 msgs).
        history: list[dict[str, str]]
        if conversation_history is not None:
            history = conversation_history
            if len(history) > 20:
                history = history[-20:]
        else:
            history = await get_recent_messages_for_claude(
                self.user_id, limit=_HISTORY_TURNS, db=db
            )

        # ── Shared context (accounts / positions) — production persona prompt ──
        ch = _normalize_channel(str(channel))
        companion_name = (getattr(shared_ctx, "ai_name", None) or getattr(shared_ctx, "apex_name", None) or getattr(user, "ai_name", None) or "Apex").strip() or "Apex"
        system_prompt = build_system_prompt(shared_ctx, ch)
        if ch == "whatsapp":
            system_prompt = _whatsapp_capabilities_preamble(companion_name) + system_prompt
        # Append channel-specific formatting instructions (never replace base prompt).
        system_prompt = system_prompt + _format_instruction_for_channel(ch)
        # Append action-tag instruction AFTER formatting block.
        system_prompt = system_prompt + _action_tags_instruction()

        if context == AI_PERFORMANCE:
            async with AsyncSessionLocal() as _db2:
                perf = await _get_performance_summary(self.user_id, _db2)
            system_prompt += f"\n\nCURRENT PERFORMANCE DATA:\n{perf}"

        if marks_block:
            system_prompt += marks_block
        if trading_engine_block:
            system_prompt += trading_engine_block
        if market_block:
            system_prompt += market_block

        # ── Build Claude messages ──────────────────────────────────────────
        messages = [*history, {"role": "user", "content": user_message}]

        # ── Call Claude ────────────────────────────────────────────────────
        max_out = 600 if ch in ("whatsapp", "telegram") else _MAX_TOKENS
        try:
            claude_response = await self._claude.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_out,
                system=system_prompt,
                messages=messages,
            )
            response_text = claude_response.content[0].text.strip()
        except Exception as exc:
            logger.error("Claude API error in ConversationAgent: %s", exc)
            return self._fallback_response(user_message, reason=str(exc))

        # ── Guardrail: suppress “I can’t access …” user-visible replies ─────
        # Strong prompts can still be violated occasionally. If Claude claims it
        # cannot access account data (despite us injecting it), retry once with a
        # short corrective system suffix.
        lower = response_text.lower()
        disallowed = (
            ("as an ai" in lower)
            or ("i cannot access" in lower)
            or ("i can't access" in lower)
            or ("i do not have access" in lower)
            or ("i don't have access" in lower)
            or ("no direct integration" in lower)
        )
        if disallowed:
            try:
                retry_system = (
                    system_prompt
                    + "\n\n---\n\n"
                    "IMPORTANT: You DO have the user's account snapshot in this system prompt. "
                    "Answer using CONNECTED EXCHANGES / OPEN POSITIONS / PERFORMANCE / RECENT TRADES. "
                    "Do not mention access limitations or integrations."
                )
                claude_retry = await self._claude.messages.create(
                    model=settings.anthropic_model,
                    max_tokens=max_out,
                    system=retry_system,
                    messages=messages,
                )
                retry_text = claude_retry.content[0].text.strip()
                if retry_text:
                    response_text = retry_text
            except Exception as exc:
                logger.debug("Guardrail retry failed: %s", exc)

        # ── ACTION TAGS: parse + dispatch (never show raw tags) ─────────────
        clean_response, action = parse_action_tag(response_text)
        supplementary = None
        if action and action.get("type"):
            supplementary = await dispatch_action(
                action=action,
                user_id=self.user_id,
                shared_context=shared_ctx,
                db=db,
                channel=ch,
            )
        response_text = (
            f"{clean_response}\n\n{supplementary}".strip()
            if supplementary
            else clean_response
        )

        # ── Persist ────────────────────────────────────────────────────────
        conv = await save_conversation(
            user_id=self.user_id,
            message=user_message,
            response=response_text,
            context=context,
            sentiment=sentiment,
            db=db,
        )
        # Also persist to onboarding_messages so router can inject last 10 turns.
        await _save_onboarding_messages(
            user_id=self.user_id,
            user_message=user_message,
            assistant_message=response_text,
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

    async def generate_response_stream(
        self,
        user_message: str,
        shared_context: SharedContext,
        conversation_history: list[dict[str, str]],
        channel: Channel = "web",
        db: AsyncSession | None = None,
    ):
        """Stream the assistant response token-by-token for web chat.

        Additive to the existing non-streaming flow. Uses the same system prompt
        construction (base prompt + channel formatting instructions) and the same
        conversation history injection semantics (max 20 messages).
        """
        if not settings.anthropic_api_key:
            # Yield once so the caller can render something.
            yield self._fallback_response(user_message).get("response", "")
            return

        shared_ctx = shared_context
        ch = _normalize_channel(channel)
        # Resolve companion name from user_settings / shared context with Apex fallback.
        companion_name = (
            (getattr(shared_ctx, "ai_name", None) or getattr(shared_ctx, "apex_name", None) or "Apex").strip()
            or "Apex"
        )

        # Detect context & sentiment (kept consistent with respond())
        context = detect_context(user_message)
        sentiment = analyze_sentiment(user_message)

        # Live data injections (best-effort, matching respond())
        assets = _extract_assets(user_message)
        if not assets and _wants_broad_market_summary(user_message):
            assets = [("SPY", "alpaca"), ("BTCUSDT", "binance")]

        data_freshness: str | None = None
        market_block = ""
        if assets:
            try:
                market_block, data_freshness = await _build_market_data_block(assets)
            except Exception as exc:
                logger.warning("Market data injection failed: %s", exc)

        marks_block = ""
        if shared_ctx.open_positions:
            try:
                marks_block = await _build_open_positions_marks_block(shared_ctx.open_positions)
            except Exception as exc:
                logger.warning("Open position marks injection failed: %s", exc)

        trading_engine_block = ""
        try:
            trading_engine_block = await self._build_trading_engine_context_block(
                user_message, shared_ctx, context
            )
        except Exception as exc:
            logger.warning("Trading engine context injection failed: %s", exc)

        system_prompt = build_system_prompt(shared_ctx, ch)
        if ch == "whatsapp":
            system_prompt = _whatsapp_capabilities_preamble(companion_name) + system_prompt
        system_prompt = system_prompt + _format_instruction_for_channel(ch)
        system_prompt = system_prompt + _action_tags_instruction()

        if context == AI_PERFORMANCE:
            async with AsyncSessionLocal() as _db2:
                perf = await _get_performance_summary(self.user_id, _db2)
            system_prompt += f"\n\nCURRENT PERFORMANCE DATA:\n{perf}"

        if marks_block:
            system_prompt += marks_block
        if trading_engine_block:
            system_prompt += trading_engine_block
        if market_block:
            system_prompt += market_block

        history = list(conversation_history or [])
        if len(history) > 20:
            history = history[-20:]

        messages = [*history, {"role": "user", "content": user_message}]

        full_response = ""
        # Prevent raw <ACTION .../> tags from ever being streamed to the user.
        in_action_tag = False
        action_buf = ""
        max_out = _MAX_TOKENS

        try:
            async with self._claude.messages.stream(
                model=settings.anthropic_model or _CLAUDE_MODEL,
                max_tokens=max_out,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    if not text:
                        continue
                    full_response += text

                    chunk = text
                    while chunk:
                        if in_action_tag:
                            action_buf += chunk
                            end_idx = action_buf.find("/>")
                            if end_idx != -1:
                                # Discard the full tag content.
                                remainder = action_buf[end_idx + 2 :]
                                action_buf = ""
                                in_action_tag = False
                                chunk = remainder
                                continue
                            break

                        start_idx = chunk.find("<ACTION")
                        if start_idx == -1:
                            yield chunk
                            break

                        # Yield text before the tag, then enter tag mode.
                        if start_idx > 0:
                            yield chunk[:start_idx]
                        in_action_tag = True
                        action_buf = chunk[start_idx:]
                        chunk = ""
        except Exception as exc:
            logger.error("Claude streaming error in ConversationAgent: %s", exc)
            # Let the caller show partial output; append a short notice.
            if not full_response:
                yield "Response interrupted. Please try again."
            return

        # ACTION TAGS: parse + dispatch after stream completes (append supplementary).
        clean_response, action = parse_action_tag(full_response)
        supplementary = None
        if action and action.get("type"):
            supplementary = await dispatch_action(
                action=action,
                user_id=self.user_id,
                shared_context=shared_context,
                db=db,
                channel=ch,
            )
        final_response = (
            f"{clean_response}\n\n{supplementary}".strip()
            if supplementary
            else clean_response
        )

        # Persist after successful stream completion
        try:
            await save_conversation(
                user_id=self.user_id,
                message=user_message,
                response=final_response,
                context=context,
                sentiment=sentiment,
                db=db,
            )
            await _save_onboarding_messages(
                user_id=self.user_id,
                user_message=user_message,
                assistant_message=final_response,
                db=db,
            )
        except Exception as exc:
            logger.warning("Failed to persist streamed conversation: %s", exc)

    async def handle_message(
        self,
        *,
        message: str,
        context: SharedContext,
        db: AsyncSession | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        channel: Channel | str = "web",
    ) -> dict:
        """Preferred entry when SharedContext is already loaded (e.g. Orchestrator.route).

        Forwards to ``respond`` with ``shared_context`` so the system prompt matches the
        orchestrator snapshot (including ``market_context`` when scoped by trading account).
        """
        return await self.respond(
            message,
            db=db,
            shared_context=context,
            conversation_history=conversation_history,
            channel=channel,
        )

    async def generate_first_message(self, context: SharedContext) -> str:
        """First assistant line after the user names their AI during onboarding."""
        name = (context.ai_name or context.apex_name or "Apex").strip() or "Apex"
        user = (context.user_name or "there").strip() or "there"
        return (
            f"Hey {user}. I'm {name}.\n\n"
            f"I'll watch the markets, flag the right moments, "
            f"and when you're ready — execute trades on your behalf. "
            f"Every decision I make, I'll explain in plain English. "
            f"No jargon unless you want it.\n\n"
            f"I'm already connected to your account and monitoring. "
            f"What do you want to do first?"
        )

    # ─────────────────────────────────────────
    # ONBOARDING CHAT
    # ─────────────────────────────────────────

    async def chat(
        self,
        user_message: str,
        mode: str = "trading",
        db: AsyncSession | None = None,
    ) -> dict:
        """Main chat method with support for different modes.

        Args:
            user_message: The user's message text
            mode: "trading" (default) or "onboarding"
            db: Optional AsyncSession

        Returns:
            {
                "message": str,  # Assistant's response text
                "completed": bool,  # True only if onboarding completed
                "profile": {...}  # User's profile if onboarding completed
            }
        """
        if mode == "onboarding":
            return await self._handle_onboarding_chat(user_message, db)
        else:
            # Standard trading mode
            result = await self.respond(user_message, db)
            return {
                "message": result.get("response", ""),
                "completed": False,
                "profile": None,
            }

    async def _handle_onboarding_chat(
        self,
        user_message: str,
        db: AsyncSession | None = None,
    ) -> dict:
        """Handle onboarding conversation flow with Claude tools.

        Returns:
            {
                "message": str,
                "completed": bool,
                "profile": {...} or None
            }
        """
        if not settings.anthropic_api_key:
            return {
                "message": "AI is not configured. Please try again later.",
                "completed": False,
                "profile": None,
            }

        # Load user profile
        async with AsyncSessionLocal() as _db:
            user_result = await _db.execute(
                select(User).where(User.id == self.user_id)
            )
            user = user_result.scalar_one_or_none()

        if not user:
            return {
                "message": "User not found.",
                "completed": False,
                "profile": None,
            }

        # Load onboarding history
        async with AsyncSessionLocal() as _db:
            history_result = await _db.execute(
                select(OnboardingMessage).where(
                    OnboardingMessage.user_id == self.user_id
                ).order_by(OnboardingMessage.created_at)
            )
            history_rows = history_result.scalars().all()

        # Convert history to Claude format
        messages: list[dict] = []
        extracted_fields = {}
        for row in history_rows:
            if row.role == "system" and row.content.startswith("extracted:"):
                # Parse extracted:field=value
                _, rest = row.content.split("extracted:", 1)
                field, value = rest.split("=", 1)
                extracted_fields[field] = value
            elif row.role in ("user", "ai", "assistant"):
                # DB CHECK allows user | assistant | system; accept legacy 'ai' rows if any
                claude_role = "assistant" if row.role in ("ai", "assistant") else "user"
                messages.append({
                    "role": claude_role,
                    "content": row.content,
                })

        # Persist the user message so history is complete for future turns
        try:
            async with AsyncSessionLocal() as _db:
                user_om = OnboardingMessage(
                    user_id=self.user_id,
                    role="user",
                    content=user_message,
                )
                _db.add(user_om)
                await _db.commit()
        except Exception as _save_err:
            logger.warning("onboarding_chat: could not save user message: %s", _save_err)

        # Add the current user message to the Claude context
        messages.append({"role": "user", "content": user_message})

        # Define the onboarding tools
        tools = [
            {
                "name": "extract_profile_field",
                "description": "Called when a profile field has been discovered from the user's response",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": ["goal", "risk_level", "budget", "exchange"],
                            "description": "The profile field that was discovered"
                        },
                        "value": {
                            "type": "string",
                            "description": "The value for this field"
                        }
                    },
                    "required": ["field", "value"]
                }
            },
            {
                "name": "complete_onboarding",
                "description": "Called when all 4 profile fields have been collected and confirmed",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "enum": ["grow_savings", "generate_income", "learn_trading", "crypto_focus"],
                            "description": "User's main financial goal"
                        },
                        "risk_level": {
                            "type": "string",
                            "enum": ["conservative", "balanced", "aggressive"],
                            "description": "User's risk comfort level"
                        },
                        "budget": {
                            "type": "number",
                            "description": "Starting budget per trade in GBP"
                        },
                        "exchange": {
                            "type": "string",
                            "enum": ["alpaca", "coinbase", "oanda"],
                            "description": "Preferred exchange"
                        }
                    },
                    "required": ["goal", "risk_level", "budget", "exchange"]
                }
            }
        ]

        # Call Claude with tools
        try:
            claude_response = await self._claude.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=_MAX_TOKENS,
                system=_ONBOARDING_SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )
        except Exception as exc:
            logger.error("Claude API error in onboarding: %s", exc)
            return {
                "message": "I'm having trouble right now. Please try again.",
                "completed": False,
                "profile": None,
            }

        # Process Claude's response
        assistant_message = ""
        tool_calls = []

        for block in claude_response.content:
            if hasattr(block, "text"):
                assistant_message = block.text.strip()
            elif block.type == "tool_use":
                tool_calls.append(block)

        # Save the assistant's message — wrapped so a DB constraint mismatch never
        # crashes the chat response.  Run `ALTER TABLE onboarding_messages DROP
        # CONSTRAINT onboarding_messages_role_check; ALTER TABLE onboarding_messages
        # ADD CONSTRAINT onboarding_messages_role_check CHECK (role IN ('user',
        # 'assistant', 'system'));` in Supabase SQL editor if saves keep failing.
        try:
            async with AsyncSessionLocal() as _db:
                om = OnboardingMessage(
                    user_id=self.user_id,
                    role="assistant",
                    content=assistant_message,
                )
                _db.add(om)
                await _db.commit()
        except Exception as _save_err:
            logger.warning(
                "onboarding_chat: could not save assistant message (constraint?): %s",
                _save_err,
            )

        # Handle tool calls
        profile_data = None
        for tool_call in tool_calls:
            if tool_call.name == "extract_profile_field":
                field = tool_call.input.get("field")
                value = tool_call.input.get("value")
                await self._save_extracted_field(field, value, db)
                extracted_fields[field] = value

            elif tool_call.name == "complete_onboarding":
                # Assemble profile from the tool inputs
                profile_data = {
                    "goal": tool_call.input.get("goal"),
                    "risk_level": tool_call.input.get("risk_level"),
                    "budget": tool_call.input.get("budget"),
                    "exchange": tool_call.input.get("exchange"),
                }
                # Pass all onboarding messages for trader class detection
                await self._complete_onboarding_internal(profile_data, messages, db)

        return {
            "message": assistant_message,
            "completed": profile_data is not None,
            "profile": profile_data,
        }

    async def _save_extracted_field(
        self,
        field: str,
        value: str,
        db: AsyncSession | None = None,
    ) -> None:
        """Save an extracted profile field to onboarding_messages and shared_memory."""
        try:
            async with AsyncSessionLocal() as _db:
                om = OnboardingMessage(
                    user_id=self.user_id,
                    role="system",
                    content=f"extracted:{field}={value}",
                )
                _db.add(om)
                await _db.commit()
        except Exception as _save_err:
            logger.warning("onboarding_chat: could not save extracted field: %s", _save_err)

        # Update shared_memory cache
        try:
            ctx = await SharedMemory.load(self.user_id, db)
            # Map field names to context attributes
            field_map = {
                "goal": "financial_goal",
                "risk_level": "risk_level",
                "budget": "max_trade_amount",
                "exchange": "primary_exchange",
            }
            attr_name = field_map.get(field)
            if attr_name:
                setattr(ctx, attr_name, value)
            # Update cache (simplified - may need full cache update)
            SharedMemory._cache[self.user_id] = (ctx, datetime.utcnow())
        except Exception as e:
            logger.warning(f"Failed to update shared_memory for field {field}: {e}")

    async def _complete_onboarding_internal(
        self,
        profile_data: dict,
        messages: list[dict] | None = None,
        db: AsyncSession | None = None,
    ) -> None:
        """Save the completed onboarding profile directly to UserSettings and detect trader class.

        Args:
            profile_data: Dict with goal, risk_level, budget, exchange
            messages: List of onboarding conversation messages for trader class detection
            db: Optional database session for direct updates
        """
        try:
            # Detect trader class from conversation messages
            detected_class = "complete_novice"
            if messages:
                detected_class = detect_trader_class(messages)

            goal = profile_data.get("goal")
            risk_level = profile_data.get("risk_level")
            budget = profile_data.get("budget")

            # Map risk_level to max_trade_amount if budget not provided
            budget_amount = float(budget) if budget else None

            # Save all profile data + trader class + onboarding_complete to UserSettings
            async with AsyncSessionLocal() as _db:
                update_vals: dict = {
                    "onboarding_complete": True,
                    "trader_class": detected_class,
                    "class_detected_at": datetime.utcnow(),
                    "class_detection_method": "onboarding_chat",
                }
                if goal:
                    update_vals["financial_goal"] = goal
                if risk_level:
                    update_vals["risk_level_setting"] = risk_level
                if budget_amount is not None:
                    update_vals["max_trade_amount"] = budget_amount

                await _db.execute(
                    update(UserSettings).where(
                        UserSettings.user_id == self.user_id
                    ).values(**update_vals)
                )
                await _db.commit()
                logger.info(
                    "Onboarding complete for user %s: class=%s goal=%s risk=%s budget=%s",
                    self.user_id,
                    detected_class,
                    goal,
                    risk_level,
                    budget_amount,
                )

            # Invalidate SharedMemory cache so new settings are loaded on next request
            SharedMemory.invalidate(self.user_id)

        except Exception as e:
            logger.error("Failed to complete onboarding for user %s: %s", self.user_id, e)
            raise

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
        channel: Channel | str = "web",
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

        async with AsyncSessionLocal() as _ctx_db:
            shared_ctx = await SharedMemory.load(self.user_id, _ctx_db)

        ai_name = (
            (shared_ctx.ai_name or shared_ctx.apex_name or user.ai_name or "Apex").strip()
            or "Apex"
        )

        # Existing context & sentiment detection
        context = detect_context(message)
        sentiment = analyze_sentiment(message)

        ch = _normalize_channel(str(channel))
        companion_name = (
            (getattr(shared_ctx, "ai_name", None) or getattr(shared_ctx, "apex_name", None) or "Apex").strip()
            or "Apex"
        )
        system_prompt = build_system_prompt(shared_ctx, ch)
        if ch == "whatsapp":
            system_prompt = _whatsapp_capabilities_preamble(companion_name) + system_prompt
        system_prompt = system_prompt + _format_instruction_for_channel(ch)
        system_prompt = system_prompt + _action_tags_instruction()

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

        max_out = 600 if ch in ("whatsapp", "telegram") else _MAX_TOKENS
        # Call Claude
        try:
            claude_response = await self._claude.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_out,
                system=system_prompt,
                messages=messages,
            )
            response_text = claude_response.content[0].text.strip()
        except Exception as exc:
            logger.error("Claude API error in respond_with_context: %s", exc)
            r = self._fallback_response(message, reason=str(exc))
            r.update({"context_used": context_used, "suggested_actions": None, "market_data_freshness": None})
            return r

        # ACTION TAGS: parse + dispatch (never show raw tags)
        clean_response, action = parse_action_tag(response_text)
        supplementary = None
        if action and action.get("type"):
            supplementary = await dispatch_action(
                action=action,
                user_id=self.user_id,
                shared_context=shared_ctx,
                db=None,
                channel=ch,
            )
        response_text = (
            f"{clean_response}\n\n{supplementary}".strip()
            if supplementary
            else clean_response
        )

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
            "user_ai_name": "Apex",
            "conversation_id": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_freshness": None,
            "error": reason,
        }
