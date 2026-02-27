"""
src/services/learning_hub.py — Unified Learning System for Unitrader.

The LearningHub is the "brain" that connects all agents together.
Every hour it:
    1. Reads recent output from every agent (trades, posts, conversations)
    2. Sends a consolidated digest to Claude for deep cross-agent pattern analysis
    3. Saves discovered patterns + cross-agent opportunities to the DB
    4. Generates specific, data-cited instructions for each agent
    5. Each agent queries its instructions before its next work cycle

Emergent flywheel example:
  RSI 60-70 momentum trades hit 85% win rate (trading data)
  → Learning Hub spots the pattern (confidence 92/100, 150 trades)
  → Trading Agent increases position size for this setup
  → Content Writer publishes "RSI 60-70 Momentum: The Setup We Trade 85% of the Time"
  → Social Media posts the win-rate as social proof
  → Support Agent recommends this setup to struggling users
  → New sign-ups cite the blog post → more trades → pattern reinforced
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import anthropic
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import (
    AgentInstruction,
    AgentOutput,
    Conversation,
    Pattern,
    SocialPost,
    Trade,
    User,
)
from src.utils.json_parser import parse_claude_json

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-3-5-haiku-20241022"  # Use Haiku for speed; upgrade to Sonnet for deeper analysis

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT 1 — Pattern Discovery
# ─────────────────────────────────────────────────────────────────────────────

_PATTERN_SYSTEM = """\
You are the Learning Hub for Unitrader — an AI trading companion platform.

Your role is to act as the central intelligence that makes ALL agents improve together.
You receive rich data from three agent streams and your job is to find patterns that
span those streams — creating emergent insights that no single agent could discover alone.

═══════════════════════════════════════════════════════
ANALYSIS DIMENSIONS
═══════════════════════════════════════════════════════

TRADING DATA — Ask yourself:
  • Which setups win most often? (RSI range, trend, market condition, symbol)
  • Which time windows produce the highest win rates?
  • What's the best performing confidence threshold?
  • Which setups are consistently failing? Why?
  • Is there a position size that correlates with higher wins?
  • Are certain symbols outperforming — and could that be content-worthy proof?

CONTENT DATA — Ask yourself:
  • Which topics are getting high engagement?
  • What resonates with users (educational vs social proof vs motivational)?
  • Which topics have NOT been covered but trading data suggests are important?
  • Are there gaps between what performs in trading and what's being written about?
  • What trading proof points could make content more credible?

CONVERSATION DATA — Ask yourself:
  • What are users confused about? (churn risk — they need clarity)
  • What makes users excited? (retention signal — amplify this)
  • What causes churn? (negative sentiment + no trades = danger zone)
  • Are there repeated questions that suggest a content gap?
  • Is there a correlation between negative sentiment and low win rates?
  • What would an encouraging support message sound like for at-risk users?

═══════════════════════════════════════════════════════
CROSS-AGENT OPPORTUNITIES
═══════════════════════════════════════════════════════

The highest-value patterns connect multiple agents. Look for:

  TRADING → CONTENT:
    "Momentum trades at RSI 60-70 win 85% of the time (150 trades)"
    → Write a blog post with that exact stat as the headline hook
    → Post on social: "Our AI trades this setup. Here's why it works."

  TRADING → SUPPORT:
    "Users with <60% win rate haven't traded in 7 days"
    → Support agent proactively sends encouragement
    → Show them their best historical trade as proof they can do it

  CONTENT → TRADING:
    "Posts about momentum trading get 3x more engagement"
    → Trading agent surfaces more momentum examples in user summaries
    → Increases user trust in momentum setups → fewer manual overrides

  CONVERSATION → CONTENT:
    "Users keep asking 'what time is best to trade Bitcoin?'"
    → Content agent writes that blog post
    → Support agent has a ready answer to share

  CONVERSATION → TRADING:
    "Users are frustrated their AI is trading in volatile markets"
    → Trading agent adds a volatility filter
    → Reduces user-initiated cancellations (churn prevention)

═══════════════════════════════════════════════════════
PATTERN CATEGORIES
═══════════════════════════════════════════════════════

  "trading"   → Setup-specific: RSI ranges, trend types, symbols, timing
  "content"   → Topic gaps, proof points, trending angles
  "support"   → Churn signals, retention actions, user confusion
  "general"   → Cross-agent opportunity (all agents act together)

═══════════════════════════════════════════════════════
CONFIDENCE SCORING GUIDE
═══════════════════════════════════════════════════════

Base your confidence score (0-100) on data quality:
  90-100: 100+ trades or conversations, clear statistical signal
  70-89:  50-99 data points, consistent pattern across timeframes
  50-69:  20-49 data points, emerging pattern worth tracking
  40-49:  10-19 data points, early signal — flag but low priority
  <40:    Insufficient data — DO NOT include in output

═══════════════════════════════════════════════════════
RESPONSE FORMAT (strict JSON array, no markdown, no extra text)
═══════════════════════════════════════════════════════

[
  {
    "pattern_name": "Momentum RSI 60-70 — 85% Win Rate",
    "description": "Trades executed when RSI is between 60-70 in uptrend conditions win 85% of the time across 150 closed trades. This is the highest-performing setup in the dataset.",
    "confidence_score": 92,
    "sample_size": 150,
    "supporting_agents": ["trading", "content", "social_media"],
    "recommendation": "Focus momentum trades on RSI 60-70 setup and increase position size by 20%. Write blog post using 85% win rate as headline stat.",
    "category": "general",
    "agent_actions": {
      "trading": "Increase position_size_modifier to 1.2 for RSI 60-70 uptrend setups. Skip setups outside this range when uptrend confidence is low.",
      "content_writer": "Write post titled 'The Setup Our AI Trades 85% of the Time (RSI 60-70 Momentum)'. Lead with the 150-trade sample size for credibility.",
      "social_media": "Post: 'We analysed 150 trades. RSI 60-70 momentum setups win 85% of the time. Here is exactly how it works. [thread]'",
      "conversation": "When users ask about losing trades, show them the RSI 60-70 stat and ask if their AI has been trading this setup. Encourage patience."
    },
    "churn_risk_level": "low",
    "is_cross_agent": true
  },
  ...
]

RULES:
  - Maximum 6 patterns per cycle (prioritise highest confidence + highest cross-agent value)
  - Only include patterns with confidence_score >= 40
  - agent_actions must be concrete, reference actual numbers from the data
  - is_cross_agent = true when 2+ agents are involved
  - If data is completely insufficient across all dimensions, return []
  - Do NOT fabricate numbers — only use what is in the provided data
"""


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT 2 — Instruction Dispatch
# ─────────────────────────────────────────────────────────────────────────────

_INSTRUCTION_SYSTEM = """\
You are the instruction dispatcher for Unitrader's unified learning system.

Given a list of discovered patterns (with agent_actions already embedded),
generate ONE final, consolidated instruction per agent that:
  1. Synthesises across all relevant patterns for that agent
  2. Prioritises the highest-confidence pattern
  3. References actual numbers ("85% win rate", "3x engagement")
  4. Is immediately actionable — the agent can act on it THIS CYCLE

AGENTS:
  "trading"       — what setups to favour, what to avoid, position size guidance
  "content_writer" — exact topic to write about, what proof point to lead with
  "social_media"  — post angle, hook, specific stat to share
  "conversation"  — tone, churn-prevention action, what confused users need to hear
  "email"         — which user segment to email, what the email should say

RESPONSE FORMAT (strict JSON object, no markdown):
{
  "trading": "Instruction text with specific numbers, or null",
  "content_writer": "Instruction text with specific numbers, or null",
  "social_media": "Instruction text with specific numbers, or null",
  "conversation": "Instruction text with specific numbers, or null",
  "email": "Instruction text with specific numbers, or null"
}

RULES:
  - Each instruction: 2-4 sentences, specific, data-cited, immediately actionable
  - Use null only if no patterns are relevant to that agent
  - Never repeat the exact wording from a previous cycle
  - Prioritise cross-agent patterns (is_cross_agent=true) for all agents
  - The trading instruction MUST include a concrete number (position modifier, RSI range, etc.)
"""


# ─────────────────────────────────────────────────────────────────────────────
# Data Gathering — Trading
# ─────────────────────────────────────────────────────────────────────────────

async def _gather_trading_data(db: AsyncSession, hours: int = 48) -> dict:
    """Deep trade analysis: win rates by setup, RSI bucket, time-of-day, symbol, and failures."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(Trade).where(
            Trade.status == "closed",
            Trade.closed_at >= since,
        ).limit(500)
    )
    trades = result.scalars().all()

    if not trades:
        return {
            "sample_size": 0,
            "summary": f"No closed trades in the last {hours}h",
            "analysis_period_hours": hours,
        }

    wins   = [t for t in trades if (t.profit or 0) > 0]
    losses = [t for t in trades if (t.loss or 0) > 0]
    overall_win_rate = round(len(wins) / len(trades) * 100, 1)

    # ── Win rate by market condition ──────────────────────────────────────
    by_condition: dict[str, dict] = defaultdict(lambda: {"total": 0, "wins": 0, "net_pnl": 0.0})
    for t in trades:
        cond = t.market_condition or "unknown"
        by_condition[cond]["total"] += 1
        pnl = (t.profit or 0) - (t.loss or 0)
        by_condition[cond]["net_pnl"] += pnl
        if pnl > 0:
            by_condition[cond]["wins"] += 1

    condition_stats = {
        cond: {
            "win_rate": round(v["wins"] / v["total"] * 100, 1),
            "trades": v["total"],
            "net_pnl": round(v["net_pnl"], 2),
        }
        for cond, v in by_condition.items()
        if v["total"] >= 3
    }

    # ── Win rate by RSI bucket ────────────────────────────────────────────
    # RSI is stored on Trade if available (may be None on older records)
    rsi_buckets: dict[str, dict] = defaultdict(lambda: {"total": 0, "wins": 0})
    for t in trades:
        rsi = getattr(t, "entry_rsi", None)
        if rsi is None:
            continue
        if rsi < 30:
            bucket = "oversold (<30)"
        elif rsi < 40:
            bucket = "low (30-40)"
        elif rsi < 50:
            bucket = "neutral-low (40-50)"
        elif rsi < 60:
            bucket = "neutral (50-60)"
        elif rsi < 70:
            bucket = "high (60-70)"
        elif rsi < 80:
            bucket = "overbought (70-80)"
        else:
            bucket = "extreme (>80)"
        rsi_buckets[bucket]["total"] += 1
        if (t.profit or 0) > 0:
            rsi_buckets[bucket]["wins"] += 1

    rsi_win_rates = {
        bucket: {
            "win_rate": round(v["wins"] / v["total"] * 100, 1),
            "trades": v["total"],
        }
        for bucket, v in rsi_buckets.items()
        if v["total"] >= 3
    }

    # ── Win rate by hour of day (UTC) ─────────────────────────────────────
    by_hour: dict[int, dict] = defaultdict(lambda: {"total": 0, "wins": 0})
    for t in trades:
        ts = t.closed_at
        if ts is None:
            continue
        hour = ts.hour
        by_hour[hour]["total"] += 1
        if (t.profit or 0) > 0:
            by_hour[hour]["wins"] += 1

    # Group into 6-hour windows for readability
    hour_windows = {
        "00-06 UTC": {"total": 0, "wins": 0},
        "06-12 UTC": {"total": 0, "wins": 0},
        "12-18 UTC": {"total": 0, "wins": 0},
        "18-24 UTC": {"total": 0, "wins": 0},
    }
    for hour, v in by_hour.items():
        if 0 <= hour < 6:
            w = "00-06 UTC"
        elif 6 <= hour < 12:
            w = "06-12 UTC"
        elif 12 <= hour < 18:
            w = "12-18 UTC"
        else:
            w = "18-24 UTC"
        hour_windows[w]["total"] += v["total"]
        hour_windows[w]["wins"]  += v["wins"]

    time_win_rates = {
        window: {
            "win_rate": round(v["wins"] / v["total"] * 100, 1),
            "trades": v["total"],
        }
        for window, v in hour_windows.items()
        if v["total"] >= 3
    }

    # ── Symbol performance ────────────────────────────────────────────────
    by_symbol: dict[str, dict] = defaultdict(lambda: {"total": 0, "wins": 0, "net_pnl": 0.0})
    for t in trades:
        sym = t.symbol
        by_symbol[sym]["total"] += 1
        pnl = (t.profit or 0) - (t.loss or 0)
        by_symbol[sym]["net_pnl"] += pnl
        if pnl > 0:
            by_symbol[sym]["wins"] += 1

    symbol_performance = {
        sym: {
            "win_rate": round(v["wins"] / v["total"] * 100, 1),
            "net_pnl": round(v["net_pnl"], 2),
            "trades": v["total"],
        }
        for sym, v in by_symbol.items()
        if v["total"] >= 2
    }

    # ── Failing setups ────────────────────────────────────────────────────
    failing = {
        cond: stats
        for cond, stats in condition_stats.items()
        if stats["win_rate"] < 45 and stats["trades"] >= 3
    }
    failing_rsi = {
        bucket: stats
        for bucket, stats in rsi_win_rates.items()
        if stats["win_rate"] < 45 and stats["trades"] >= 3
    }

    # ── Best setups (the positive signal to amplify) ──────────────────────
    best_condition = max(
        condition_stats.items(), key=lambda x: x[1]["win_rate"], default=None
    )
    best_rsi = max(
        rsi_win_rates.items(), key=lambda x: x[1]["win_rate"], default=None
    )
    best_time = max(
        time_win_rates.items(), key=lambda x: x[1]["win_rate"], default=None
    )

    return {
        "analysis_period_hours": hours,
        "sample_size": len(trades),
        "overall_win_rate_pct": overall_win_rate,
        "total_wins": len(wins),
        "total_losses": len(losses),
        "net_pnl": round(sum((t.profit or 0) - (t.loss or 0) for t in trades), 2),
        "avg_confidence": round(
            sum(t.claude_confidence or 50 for t in trades) / len(trades), 1
        ),
        # ── Signal: what's working ────────────────────────────────────────
        "best_market_condition": {
            "name": best_condition[0],
            "win_rate": best_condition[1]["win_rate"],
            "trades": best_condition[1]["trades"],
        } if best_condition else None,
        "best_rsi_bucket": {
            "name": best_rsi[0],
            "win_rate": best_rsi[1]["win_rate"],
            "trades": best_rsi[1]["trades"],
        } if best_rsi else None,
        "best_time_window": {
            "name": best_time[0],
            "win_rate": best_time[1]["win_rate"],
            "trades": best_time[1]["trades"],
        } if best_time else None,
        # ── Full breakdowns ───────────────────────────────────────────────
        "win_rate_by_condition": condition_stats,
        "win_rate_by_rsi_bucket": rsi_win_rates,
        "win_rate_by_time_window": time_win_rates,
        "symbol_performance": symbol_performance,
        # ── Failures to avoid ────────────────────────────────────────────
        "failing_conditions": failing,
        "failing_rsi_buckets": failing_rsi,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Data Gathering — Content
# ─────────────────────────────────────────────────────────────────────────────

async def _gather_content_data(db: AsyncSession, hours: int = 168) -> dict:
    """Deep content analysis: per-topic engagement, coverage gaps, post type performance."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(SocialPost).where(SocialPost.created_at >= since).limit(100)
    )
    posts = result.scalars().all()

    if not posts:
        return {
            "sample_size": 0,
            "summary": f"No social posts in the last {hours}h",
            "analysis_period_hours": hours,
        }

    # ── Engagement by topic ───────────────────────────────────────────────
    topic_engagement: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "high": 0, "medium": 0, "low": 0}
    )
    for p in posts:
        topic = (p.topic or "general").lower().strip()
        topic_engagement[topic]["total"] += 1
        eng = p.estimated_engagement or "low"
        topic_engagement[topic][eng] = topic_engagement[topic].get(eng, 0) + 1

    topic_stats = {
        topic: {
            "total_posts": v["total"],
            "high_engagement_pct": round(v["high"] / v["total"] * 100, 1),
            "high_count": v["high"],
        }
        for topic, v in topic_engagement.items()
        if v["total"] >= 1
    }

    # ── Best and worst performing topics ─────────────────────────────────
    sorted_topics = sorted(
        topic_stats.items(),
        key=lambda x: x[1]["high_engagement_pct"],
        reverse=True,
    )
    top_topics    = [t for t, s in sorted_topics if s["high_count"] >= 1][:5]
    weak_topics   = [t for t, s in sorted_topics if s["high_engagement_pct"] == 0][:5]

    # ── Post type performance ─────────────────────────────────────────────
    type_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "high": 0})
    for p in posts:
        pt = p.post_type or "educational"
        type_stats[pt]["total"] += 1
        if p.estimated_engagement == "high":
            type_stats[pt]["high"] += 1

    type_performance = {
        pt: {
            "posts": v["total"],
            "high_engagement_pct": round(v["high"] / v["total"] * 100, 1),
        }
        for pt, v in type_stats.items()
        if v["total"] >= 1
    }

    # ── Recent topics covered (for gap detection) ─────────────────────────
    recent_topics_covered = list(set(p.topic for p in posts if p.topic))[:15]

    # ── Overall stats ─────────────────────────────────────────────────────
    high_eng   = [p for p in posts if p.estimated_engagement == "high"]
    medium_eng = [p for p in posts if p.estimated_engagement == "medium"]

    return {
        "analysis_period_hours": hours,
        "sample_size": len(posts),
        "overall_high_engagement_pct": round(len(high_eng) / len(posts) * 100, 1),
        "high_engagement_count": len(high_eng),
        "medium_engagement_count": len(medium_eng),
        "posted_count": sum(1 for p in posts if p.is_posted),
        # ── What's working ────────────────────────────────────────────────
        "top_performing_topics": top_topics,
        "weak_performing_topics": weak_topics,
        "topic_engagement_breakdown": topic_stats,
        "post_type_performance": type_performance,
        # ── Coverage map (for gap detection) ─────────────────────────────
        "topics_covered_recently": recent_topics_covered,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Data Gathering — Conversations
# ─────────────────────────────────────────────────────────────────────────────

# Keywords that signal excitement, confusion, and churn risk
_EXCITEMENT_KEYWORDS  = ["profit", "won", "winning", "amazing", "great", "love", "excited", "gains", "bull", "green"]
_CONFUSION_KEYWORDS   = ["confused", "don't understand", "why did", "what is", "how does", "not sure", "lost", "explain", "help"]
_CHURN_KEYWORDS       = ["cancel", "refund", "stop", "quit", "waste", "disappointing", "doesn't work", "not working", "useless", "angry"]
_TOPIC_KEYWORDS = {
    "rsi":        ["rsi", "relative strength"],
    "macd":       ["macd", "moving average convergence"],
    "stop_loss":  ["stop loss", "stop-loss", "stoploss"],
    "position":   ["position size", "how much", "risk management"],
    "momentum":   ["momentum", "trend", "uptrend", "downtrend"],
    "timing":     ["when to trade", "best time", "market hours"],
    "crypto":     ["bitcoin", "btc", "ethereum", "crypto"],
    "forex":      ["forex", "currency", "gbp", "eur", "usd"],
    "results":    ["win rate", "performance", "results", "returns"],
}


def _extract_signals(text: str) -> dict:
    """Scan a message for excitement, confusion, churn, and topic signals."""
    t = text.lower()
    return {
        "excited":  any(kw in t for kw in _EXCITEMENT_KEYWORDS),
        "confused": any(kw in t for kw in _CONFUSION_KEYWORDS),
        "churn_risk": any(kw in t for kw in _CHURN_KEYWORDS),
        "topics": [topic for topic, kws in _TOPIC_KEYWORDS.items() if any(kw in t for kw in kws)],
    }


async def _gather_conversation_data(db: AsyncSession, hours: int = 48) -> dict:
    """Deep conversation analysis: sentiment, confusion topics, excitement signals, churn risk."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(Conversation).where(Conversation.created_at >= since).limit(200)
    )
    convos = result.scalars().all()

    if not convos:
        return {
            "sample_size": 0,
            "summary": f"No conversations in the last {hours}h",
            "analysis_period_hours": hours,
        }

    # ── Sentiment aggregation ─────────────────────────────────────────────
    sentiment_counts: dict[str, int] = defaultdict(int)
    context_counts:   dict[str, int] = defaultdict(int)
    for c in convos:
        sentiment_counts[c.sentiment or "neutral"] += 1
        context_counts[c.context_type or "chat"] += 1

    # ── Keyword signal extraction from messages ──────────────────────────
    excitement_count   = 0
    confusion_count    = 0
    churn_risk_count   = 0
    topic_freq: dict[str, int] = defaultdict(int)
    churn_risk_users:  set[str] = set()
    confused_topics:   dict[str, int] = defaultdict(int)
    excitement_topics: dict[str, int] = defaultdict(int)

    for c in convos:
        signals = _extract_signals(c.message)
        if signals["excited"]:
            excitement_count += 1
            for t in signals["topics"]:
                excitement_topics[t] += 1
        if signals["confused"]:
            confusion_count += 1
            for t in signals["topics"]:
                confused_topics[t] += 1
        if signals["churn_risk"]:
            churn_risk_count += 1
            if c.user_id:
                churn_risk_users.add(c.user_id)
        for t in signals["topics"]:
            topic_freq[t] += 1

    # ── Helpfulness ───────────────────────────────────────────────────────
    rated = [c for c in convos if c.is_helpful is not None]
    helpful_rate = (
        round(sum(1 for c in rated if c.is_helpful is True) / len(rated) * 100, 1)
        if rated else 0.0
    )

    negative_pct = round(
        sentiment_counts.get("negative", 0) / len(convos) * 100, 1
    )

    # ── Most-asked topics (sorted by frequency) ──────────────────────────
    sorted_topics = sorted(topic_freq.items(), key=lambda x: x[1], reverse=True)

    return {
        "analysis_period_hours": hours,
        "sample_size": len(convos),
        "sentiment_breakdown": dict(sentiment_counts),
        "context_type_breakdown": dict(context_counts),
        "negative_sentiment_pct": negative_pct,
        "helpful_rate_pct": helpful_rate,
        # ── Engagement signals ────────────────────────────────────────────
        "excited_message_count": excitement_count,
        "excited_pct": round(excitement_count / len(convos) * 100, 1),
        "topics_exciting_users": dict(list(excitement_topics.items())[:5]),
        # ── Confusion signals ─────────────────────────────────────────────
        "confused_message_count": confusion_count,
        "confused_pct": round(confusion_count / len(convos) * 100, 1),
        "topics_confusing_users": dict(
            sorted(confused_topics.items(), key=lambda x: x[1], reverse=True)[:5]
        ),
        # ── Churn signals ─────────────────────────────────────────────────
        "churn_risk_message_count": churn_risk_count,
        "churn_risk_pct": round(churn_risk_count / len(convos) * 100, 1),
        "churn_risk_user_count": len(churn_risk_users),
        # ── Content gap signals ───────────────────────────────────────────
        "most_discussed_topics": dict(sorted_topics[:8]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Claude Analysis Calls
# ─────────────────────────────────────────────────────────────────────────────

async def _claude_discover_patterns(digest: dict) -> list[dict]:
    """Send the full multi-agent digest to Claude for deep pattern discovery."""
    if not settings.anthropic_api_key:
        logger.warning("LearningHub: Anthropic key not set — skipping pattern analysis")
        return []

    user_content = (
        "Below is the full aggregated data from all Unitrader agents.\n"
        "Analyse it deeply, find cross-agent patterns, and return the JSON array.\n\n"
        "DATA DIGEST:\n"
        + json.dumps(digest, indent=2, default=str)
        + "\n\n"
        "Remember: base confidence strictly on sample sizes. "
        "Cross-agent patterns (is_cross_agent=true) are the highest priority. "
        "Output ONLY the JSON array — no markdown, no preamble."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=2048,
            system=_PATTERN_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        patterns = parse_claude_json(raw, context="pattern discovery")
        if isinstance(patterns, list):
            logger.info("LearningHub: Claude returned %d raw patterns", len(patterns))
            return patterns
        logger.warning("LearningHub: Claude returned non-list for patterns")
        return []
    except Exception as exc:
        logger.error("LearningHub: Claude pattern discovery failed: %s", exc)
        return []


async def _claude_generate_instructions(patterns: list[dict]) -> dict[str, str | None]:
    """Synthesise patterns into one consolidated, data-cited instruction per agent."""
    if not settings.anthropic_api_key or not patterns:
        return {}

    # Extract agent_actions directly from patterns (fast path — no extra Claude call needed
    # if patterns already carry granular agent_actions)
    merged: dict[str, list[str]] = defaultdict(list)
    for p in patterns:
        actions = p.get("agent_actions", {})
        if isinstance(actions, dict):
            for agent, action in actions.items():
                if action:
                    merged[agent].append(f"[{p['pattern_name']} — {p['confidence_score']:.0f}% confidence]: {action}")

    # If patterns don't have agent_actions (e.g. older schema), fall back to Claude
    if not any(merged.values()):
        user_content = (
            "Here are the discovered patterns from this analysis cycle:\n\n"
            + json.dumps(patterns, indent=2)
            + "\n\nGenerate the per-agent instruction object."
        )
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=768,
                system=_INSTRUCTION_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = response.content[0].text.strip()
            result = parse_claude_json(raw, context="instruction generation")
            if isinstance(result, dict):
                return result
            return {}
        except Exception as exc:
            logger.error("LearningHub: Claude instruction generation failed: %s", exc)
            return {}

    # Build consolidated instructions from merged agent_actions
    consolidated: dict[str, str | None] = {}
    for agent, actions in merged.items():
        # Take the top 2 highest-confidence actions (already sorted by pattern order)
        top = actions[:2]
        consolidated[agent] = " | ".join(top)

    # Fill in agents that have no actions
    for agent in ("trading", "content_writer", "social_media", "conversation", "email"):
        if agent not in consolidated:
            consolidated[agent] = None

    return consolidated


# ─────────────────────────────────────────────────────────────────────────────
# DB Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _save_pattern(db: AsyncSession, p: dict) -> Pattern:
    """Persist one validated pattern dict to the DB."""
    confidence = float(p.get("confidence_score", 0))
    # Higher confidence patterns live longer
    ttl_hours = 24 + int(confidence / 10) * 6  # 40% → 48h, 90% → 78h
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    pattern = Pattern(
        pattern_name=str(p.get("pattern_name", "Unknown Pattern"))[:200],
        description=p.get("description", ""),
        confidence_score=confidence,
        supporting_agents=p.get("supporting_agents", []),
        recommendation=p.get("recommendation", ""),
        category=p.get("category", "general"),
        is_active=True,
        expires_at=expires,
    )
    db.add(pattern)
    return pattern


async def _expire_stale_patterns(db: AsyncSession) -> int:
    """Mark patterns past their expiry as inactive. Returns count expired."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Pattern).where(
            Pattern.is_active == True,      # noqa: E712
            Pattern.expires_at <= now,
        )
    )
    stale = result.scalars().all()
    for p in stale:
        p.is_active = False
    return len(stale)


async def _save_instructions(
    db: AsyncSession,
    instructions: dict[str, str | None],
    patterns: list[Pattern],
) -> int:
    """Archive stale instructions and insert fresh ones. Returns count saved."""
    agent_names = [k for k, v in instructions.items() if v]
    if not agent_names:
        return 0

    # Archive previous active instructions for these agents
    old = await db.execute(
        select(AgentInstruction).where(
            and_(
                AgentInstruction.agent_name.in_(agent_names),
                AgentInstruction.status == "active",
            )
        )
    )
    for instr in old.scalars().all():
        instr.status = "archived"

    # Map pattern category → pattern id for FK linking
    pattern_by_category = {p.category: p.id for p in patterns}
    # Prefer "general" (cross-agent) patterns for FK
    general_id = pattern_by_category.get("general")

    saved = 0
    for agent_name, text in instructions.items():
        if not text:
            continue
        source_id = general_id or pattern_by_category.get(
            "trading" if agent_name == "trading" else
            "content" if agent_name in ("content_writer", "social_media") else
            "support"
        )
        new_instr = AgentInstruction(
            agent_name=agent_name,
            instruction=text,
            source_pattern_id=source_id,
            priority=8,  # Learning hub instructions are high priority
            status="active",
        )
        db.add(new_instr)
        saved += 1

    return saved


# ─────────────────────────────────────────────────────────────────────────────
# Public API — insights for agents
# ─────────────────────────────────────────────────────────────────────────────

async def get_active_instructions(agent_name: str) -> list[dict]:
    """Return the current active instructions for an agent (highest priority first)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentInstruction).where(
                AgentInstruction.agent_name == agent_name,
                AgentInstruction.status == "active",
            ).order_by(AgentInstruction.priority.desc()).limit(3)
        )
        instrs = result.scalars().all()
        return [
            {
                "id": i.id,
                "instruction": i.instruction,
                "priority": i.priority,
                "source_pattern_id": i.source_pattern_id,
            }
            for i in instrs
        ]


async def get_trading_insights() -> dict:
    """Trading agent asks: What patterns should guide my next trade?"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Pattern).where(
                Pattern.is_active == True,       # noqa: E712
                Pattern.category.in_(["trading", "general"]),
            ).order_by(Pattern.confidence_score.desc()).limit(5)
        )
        patterns = result.scalars().all()

    if not patterns:
        return {
            "has_insights": False,
            "focus_condition": None,
            "avoid_condition": None,
            "position_size_modifier": 1.0,
            "high_confidence_setups": [],
            "avoid_setups": [],
            "summary": "No learning patterns available yet — defaulting to standard rules",
        }

    focus_condition  = None
    avoid_condition  = None
    size_modifier    = 1.0
    high_confidence: list[str] = []
    avoid:           list[str] = []

    for p in patterns:
        rec  = p.recommendation.lower()
        name = p.pattern_name.lower()
        score = p.confidence_score

        # Parse RSI range hints
        rsi_match = re.search(r"rsi\s+(\d+)[–-](\d+)", name)
        if rsi_match and score >= 70:
            high_confidence.append(p.recommendation)
            if score >= 80:
                size_modifier = min(size_modifier * 1.2, 1.5)

        # Trend/condition signals
        if ("momentum" in name or "uptrend" in name) and score >= 70:
            focus_condition = "uptrend"
            high_confidence.append(p.recommendation)
            if score >= 80:
                size_modifier = min(size_modifier * 1.2, 1.5)

        if ("downtrend" in name or "failing" in name or "avoid" in rec) and score >= 55:
            avoid_condition = "downtrend"
            avoid.append(p.recommendation)
            if "avoid" in rec or "skip" in rec:
                size_modifier = min(size_modifier, 0.80)

        if "consolidat" in name:
            avoid.append(f"Consolidating market: {p.recommendation}")
            size_modifier = min(size_modifier, 0.85)

    return {
        "has_insights": True,
        "focus_condition": focus_condition,
        "avoid_condition": avoid_condition,
        "position_size_modifier": round(size_modifier, 2),
        "high_confidence_setups": list(dict.fromkeys(high_confidence))[:3],
        "avoid_setups": list(dict.fromkeys(avoid))[:3],
        "top_patterns": [
            {
                "name": p.pattern_name,
                "confidence": p.confidence_score,
                "recommendation": p.recommendation,
                "category": p.category,
            }
            for p in patterns[:3]
        ],
        "summary": patterns[0].recommendation,
    }


async def get_content_insights() -> dict:
    """Content agent asks: What should I write about this cycle?"""
    async with AsyncSessionLocal() as db:
        content_result = await db.execute(
            select(Pattern).where(
                Pattern.is_active == True,       # noqa: E712
                Pattern.category.in_(["content", "general"]),
            ).order_by(Pattern.confidence_score.desc()).limit(5)
        )
        content_patterns = content_result.scalars().all()

        trading_result = await db.execute(
            select(Pattern).where(
                Pattern.is_active == True,       # noqa: E712
                Pattern.category == "trading",
                Pattern.confidence_score >= 60,
            ).order_by(Pattern.confidence_score.desc()).limit(3)
        )
        trading_patterns = trading_result.scalars().all()

        instr_result = await db.execute(
            select(AgentInstruction).where(
                AgentInstruction.agent_name == "content_writer",
                AgentInstruction.status == "active",
            ).order_by(AgentInstruction.priority.desc()).limit(1)
        )
        instr = instr_result.scalar_one_or_none()

    viral_topics: list[str] = []
    proof_points: list[str] = []

    for p in trading_patterns:
        if p.confidence_score >= 70:
            viral_topics.append(f"{p.pattern_name} ({p.confidence_score:.0f}% confidence)")
            proof_points.append(p.recommendation)

    for p in content_patterns:
        viral_topics.append(p.pattern_name)

    return {
        "has_insights": bool(content_patterns or trading_patterns),
        "viral_topics": list(dict.fromkeys(viral_topics))[:5],
        "trading_proof_points": proof_points[:3],
        "current_instruction": instr.instruction if instr else None,
        "suggested_angle": (
            "Lead with real performance data as proof — users trust numbers"
            if proof_points
            else "Focus on educational depth and step-by-step clarity"
        ),
    }


async def get_support_insights() -> dict:
    """Conversation agent asks: How should I handle users today?"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Pattern).where(
                Pattern.is_active == True,       # noqa: E712
                Pattern.category.in_(["support", "general"]),
            ).order_by(Pattern.confidence_score.desc()).limit(5)
        )
        patterns = result.scalars().all()

    churn_signals:     list[str] = []
    retention_actions: list[str] = []
    confusion_topics:  list[str] = []

    for p in patterns:
        rec  = p.recommendation.lower()
        name = p.pattern_name.lower()
        desc = p.description.lower()
        if "churn" in name or "negative" in desc or "cancel" in rec:
            churn_signals.append(p.pattern_name)
        if any(kw in rec for kw in ("encourage", "engage", "show", "remind", "celebrate")):
            retention_actions.append(p.recommendation)
        if "confus" in name or "confus" in desc:
            confusion_topics.append(p.pattern_name)

    return {
        "has_insights": bool(patterns),
        "churn_signals": churn_signals[:3],
        "retention_actions": retention_actions[:3],
        "confusion_topics": confusion_topics[:3],
        "top_patterns": [
            {"name": p.pattern_name, "recommendation": p.recommendation, "confidence": p.confidence_score}
            for p in patterns[:3]
        ],
    }


async def record_agent_output(
    agent_name: str,
    output_type: str,
    content: dict,
    outcome: str = "pending",
    metrics: dict | None = None,
    source_instruction_id: str | None = None,
) -> None:
    """Any agent calls this to log what it produced. Feeds the next learning cycle."""
    async with AsyncSessionLocal() as db:
        output = AgentOutput(
            agent_name=agent_name,
            output_type=output_type,
            content=content,
            metrics=metrics or {},
            outcome=outcome,
            source_instruction_id=source_instruction_id,
        )
        db.add(output)
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Main Learning Cycle
# ─────────────────────────────────────────────────────────────────────────────

class LearningHub:
    """Orchestrates the full cross-agent analysis → pattern → instruction cycle."""

    async def analyze_all_data(self) -> dict:
        """Run one complete learning cycle.

        Pipeline:
            1. Gather deep data from all three agent streams
            2. Claude discovers cross-agent patterns with confidence scores
            3. Claude generates per-agent instructions from those patterns
            4. Expire stale patterns, save new ones (confidence-weighted TTL)
            5. Save instructions (archive old, insert fresh)
            6. Log the cycle itself as an AgentOutput for meta-learning

        Returns a summary dict for the scheduler to log.
        """
        logger.info("═══ LearningHub: starting analysis cycle ═══")
        start = datetime.now(timezone.utc)

        # ── Step 1: Deep data gathering ───────────────────────────────────
        async with AsyncSessionLocal() as db:
            trading_data      = await _gather_trading_data(db)
            content_data      = await _gather_content_data(db)
            conversation_data = await _gather_conversation_data(db)

        sample_sizes = {
            "trades":        trading_data.get("sample_size", 0),
            "content_posts": content_data.get("sample_size", 0),
            "conversations": conversation_data.get("sample_size", 0),
        }
        total_samples = sum(sample_sizes.values())

        logger.info(
            "LearningHub: data gathered — trades=%d posts=%d convos=%d (total=%d)",
            sample_sizes["trades"], sample_sizes["content_posts"],
            sample_sizes["conversations"], total_samples,
        )

        digest = {
            "analysis_timestamp": start.isoformat(),
            "total_data_points": total_samples,
            "trading":       trading_data,
            "content":       content_data,
            "conversations": conversation_data,
        }

        # ── Step 2: Pattern discovery ─────────────────────────────────────
        raw_patterns = await _claude_discover_patterns(digest)
        logger.info("LearningHub: Claude discovered %d candidate patterns", len(raw_patterns))

        # Filter by minimum confidence
        valid_patterns = [
            p for p in raw_patterns
            if float(p.get("confidence_score", 0)) >= 40
        ]
        cross_agent_count = sum(1 for p in valid_patterns if p.get("is_cross_agent"))
        logger.info(
            "LearningHub: %d valid patterns (%d cross-agent)",
            len(valid_patterns), cross_agent_count,
        )

        if not valid_patterns:
            logger.info("LearningHub: no valid patterns this cycle — skipping instruction dispatch")
            return {
                "patterns_found": 0,
                "cross_agent_patterns": 0,
                "instructions_sent": 0,
                "duration_s": round((datetime.now(timezone.utc) - start).total_seconds(), 1),
                "sample_sizes": sample_sizes,
            }

        # ── Step 3: Instruction generation ───────────────────────────────
        raw_instructions = await _claude_generate_instructions(valid_patterns)
        instructions_count = sum(1 for v in raw_instructions.values() if v)
        logger.info(
            "LearningHub: generated instructions for %d agents: %s",
            instructions_count,
            [k for k, v in raw_instructions.items() if v],
        )

        # ── Step 4 + 5: Persist to DB ─────────────────────────────────────
        async with AsyncSessionLocal() as db:
            # Expire stale patterns first
            expired_count = await _expire_stale_patterns(db)
            if expired_count:
                logger.info("LearningHub: expired %d stale patterns", expired_count)

            # Save new patterns
            saved_patterns: list[Pattern] = []
            for rp in valid_patterns:
                p = await _save_pattern(db, rp)
                saved_patterns.append(p)

            await db.flush()  # generate IDs before instruction FK references

            # Save instructions
            saved_instr_count = await _save_instructions(db, raw_instructions, saved_patterns)

            # Log this cycle as an AgentOutput (meta-learning)
            cycle_output = AgentOutput(
                agent_name="learning_hub",
                output_type="pattern_analysis",
                content={
                    "digest_summary": {
                        "trades":   sample_sizes["trades"],
                        "posts":    sample_sizes["content_posts"],
                        "convos":   sample_sizes["conversations"],
                    },
                    "top_pattern": valid_patterns[0].get("pattern_name") if valid_patterns else None,
                    "top_confidence": valid_patterns[0].get("confidence_score") if valid_patterns else 0,
                },
                metrics={
                    "patterns_found":      len(saved_patterns),
                    "cross_agent_patterns": cross_agent_count,
                    "instructions_sent":   saved_instr_count,
                    "total_data_points":   total_samples,
                },
                outcome="success",
            )
            db.add(cycle_output)
            await db.commit()

        duration = round((datetime.now(timezone.utc) - start).total_seconds(), 1)

        # Detailed log of what was discovered
        for i, p in enumerate(valid_patterns[:3], 1):
            logger.info(
                "  Pattern %d: [%s] %s (confidence=%.0f)",
                i, p.get("category", "?"), p.get("pattern_name", "?"),
                float(p.get("confidence_score", 0)),
            )

        summary = {
            "patterns_found":       len(saved_patterns),
            "cross_agent_patterns": cross_agent_count,
            "instructions_sent":    saved_instr_count,
            "agents_instructed":    [k for k, v in raw_instructions.items() if v],
            "duration_s":           duration,
            "sample_sizes":         sample_sizes,
            "top_pattern":          valid_patterns[0].get("pattern_name") if valid_patterns else None,
        }

        logger.info(
            "═══ LearningHub: cycle complete — %d patterns (%d cross-agent), "
            "%d instructions sent in %.1fs ═══",
            summary["patterns_found"],
            summary["cross_agent_patterns"],
            summary["instructions_sent"],
            summary["duration_s"],
        )
        return summary


# Module-level singleton — import this everywhere
learning_hub = LearningHub()
