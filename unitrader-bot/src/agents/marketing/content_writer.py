"""
src/agents/marketing/content_writer.py — AI blog post generation agent.

Generates long-form, SEO-optimised blog posts about trading topics.
Posts are stored in the BlogPost table and can be published or reviewed
before going live.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import BlogPost, Trade, User
from src.utils.json_parser import parse_claude_json
from src.services.learning_hub import (
    get_content_insights,
    get_active_instructions,
    record_agent_output,
)

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-3-haiku-20240307"
_MAX_TOKENS = 4096

# ─────────────────────────────────────────────
# Pre-defined topic templates
# ─────────────────────────────────────────────

SUGGESTED_TOPICS = [
    "How Momentum Trading Works (With Real Win-Rate Data)",
    "Why AI Trading Beats Manual Trading in Volatile Markets",
    "Understanding Stop-Loss: The #1 Risk Management Tool Every Trader Needs",
    "RSI, MACD, and Moving Averages: A Beginner's Complete Guide",
    "How to Size Your Positions Like a Professional Trader",
    "The Psychology of Trading Losses (And How to Recover)",
    "Crypto vs Stocks vs Forex: Which Market Is Right for You?",
    "How Automated Trading Removes Emotion from Your Decisions",
    "Building a Trading Plan That Actually Works",
    "The Power of Risk-to-Reward Ratio: Never Trade Without It",
    "5 Common Trading Mistakes Beginners Make (And How to Avoid Them)",
    "Technical Analysis vs Fundamental Analysis: A Practical Comparison",
    "How to Read Candlestick Charts Like a Pro",
    "Diversification in Trading: How Many Positions Are Too Many?",
    "Backtesting Your Strategy: Why Historical Data Matters",
]

# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

_BLOG_SYSTEM_PROMPT = """\
You are a professional financial content writer specialising in algorithmic and AI-assisted trading.

Your audience is a mix of beginners who are just discovering trading and intermediate traders who want \
to level up. Write accessibly but don't dumb things down — include genuine insights.

EVERY blog post you write MUST follow this exact structure:

1. **Title** — Compelling, benefit-driven, SEO-friendly
2. **Introduction** (150–200 words) — Hook the reader, state the problem, promise a solution
3. **Section 1** — Core concept explained simply with an analogy
4. **Section 2** — How it works in practice (step-by-step or numbered)
5. **Section 3** — Real-world example or data-backed insight
6. **Section 4** — Common mistakes and how to avoid them
7. **Conclusion** (100–150 words) — Summarise key takeaways
8. **Call to Action** — Invite the reader to try Unitrader's AI trading companion

WRITING RULES:
- Minimum 1000 words
- Use H2 (##) and H3 (###) headings for structure
- Use bullet points and numbered lists where appropriate
- Bold key terms on first use
- Include 1–2 practical examples with numbers
- Write in second person ("you", "your")
- Avoid jargon without explanation
- Never make specific profit guarantees

OUTPUT FORMAT — respond with valid JSON only, no markdown fences:
{
  "title": "...",
  "slug": "...",
  "content": "...",
  "seo_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "estimated_read_time": <integer minutes>,
  "word_count": <integer>,
  "meta_description": "...(150 chars max)"
}
"""


# ─────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────

def make_slug(title: str) -> str:
    """Convert a blog title to a URL-friendly slug.

    Example: "How MACD Works!" → "how-macd-works"
    """
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:200]


def estimate_read_time(text: str, wpm: int = 225) -> int:
    """Estimate reading time in minutes based on average words-per-minute."""
    words = len(text.split())
    minutes = max(1, round(words / wpm))
    return minutes


def count_words(text: str) -> int:
    """Return approximate word count of a string."""
    return len(text.split())


async def _get_platform_stats(db: AsyncSession) -> dict:
    """Pull aggregate platform stats to enrich blog posts with real data."""
    try:
        from sqlalchemy import func

        result = await db.execute(
            select(
                func.count(Trade.id).label("total_trades"),
                func.avg(
                    Trade.profit_percent.cast(type_=None)
                ).label("avg_profit_pct"),
            ).where(Trade.status == "closed")
        )
        row = result.first()
        return {
            "total_trades": row.total_trades or 0,
            "avg_profit_pct": round(float(row.avg_profit_pct or 0), 2),
        }
    except Exception:
        return {"total_trades": 0, "avg_profit_pct": 0.0}


# ─────────────────────────────────────────────
# Main generation function
# ─────────────────────────────────────────────

async def generate_blog_post(
    topic: str,
    save_to_db: bool = True,
    db: AsyncSession | None = None,
) -> dict:
    """Generate a complete, SEO-optimised blog post on the given topic.

    Args:
        topic: The subject or working title for the post.
        save_to_db: If True, persist the generated post to the database.
        db: Optional injected session (uses its own session if not provided).

    Returns:
        {
            "id": str | None,
            "title": str,
            "slug": str,
            "content": str,
            "seo_keywords": list[str],
            "estimated_read_time": int,
            "word_count": int,
            "meta_description": str,
            "topic": str,
            "created_at": str (ISO 8601),
        }
    """
    if not settings.anthropic_api_key:
        logger.warning("Anthropic API key not set — cannot generate blog post")
        return _placeholder_post(topic, error="Anthropic API key not configured")

    # ── Fetch learning hub insights ───────────────────────────────────────
    hub_context = ""
    instr_id: str | None = None
    try:
        insights = await get_content_insights()
        instructions = await get_active_instructions("content_writer")

        proof_points = insights.get("trading_proof_points", [])
        viral_topics = insights.get("viral_topics", [])
        current_instr = insights.get("current_instruction")

        if proof_points or viral_topics or current_instr:
            hub_parts: list[str] = []
            if proof_points:
                hub_parts.append(
                    "PROVEN TRADING DATA TO REFERENCE:\n"
                    + "\n".join(f"  - {p}" for p in proof_points[:3])
                )
            if viral_topics:
                hub_parts.append(
                    "TRENDING TOPICS (high engagement):\n"
                    + "\n".join(f"  - {t}" for t in viral_topics[:5])
                )
            if current_instr:
                hub_parts.append(f"EDITORIAL DIRECTIVE: {current_instr}")
            hub_context = (
                "\n\nLEARNING HUB GUIDANCE (incorporate where natural):\n"
                + "\n".join(hub_parts)
            )
            logger.info("ContentWriter: learning hub context injected for '%s'", topic)

        if instructions:
            instr_id = instructions[0]["id"]

    except Exception as exc:
        logger.warning("ContentWriter: could not fetch learning insights: %s", exc)

    # ── Enrich with platform stats ────────────────────────────────────────
    stats_context = ""
    try:
        async with AsyncSessionLocal() as _db:
            stats = await _get_platform_stats(_db)
        if stats["total_trades"] > 0:
            stats_context = (
                f"\n\nPLATFORM DATA (use these real numbers in the post):\n"
                f"- Total trades analysed by Unitrader AI: {stats['total_trades']:,}\n"
                f"- Average profit per winning trade: {stats['avg_profit_pct']:.1f}%\n"
            )
    except Exception:
        pass

    user_prompt = (
        f"Write a complete blog post about: **{topic}**"
        f"{hub_context}"
        f"{stats_context}\n\n"
        "Remember: output ONLY valid JSON with no markdown code fences."
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        response = await client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_BLOG_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        data = parse_claude_json(raw, context="blog post")

    except json.JSONDecodeError as exc:
        logger.error("Blog post JSON parse error: %s", exc)
        return _placeholder_post(topic, error=f"JSON parse error: {exc}")
    except Exception as exc:
        logger.error("Blog post generation failed: %s", exc)
        return _placeholder_post(topic, error=str(exc))

    base_slug = data.get("slug") or make_slug(data.get("title", topic))
    slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    content = data.get("content", "")
    word_count = data.get("word_count") or count_words(content)
    read_time = data.get("estimated_read_time") or estimate_read_time(content)

    result = {
        "id": None,
        "title": data.get("title", topic),
        "slug": slug,
        "topic": topic,
        "content": content,
        "seo_keywords": data.get("seo_keywords", []),
        "estimated_read_time": read_time,
        "word_count": word_count,
        "meta_description": data.get("meta_description", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if save_to_db:
        post_id = await _save_blog_post(result, db)
        result["id"] = post_id

    logger.info(
        "Blog post generated: '%s' (%d words, ~%d min read)",
        result["title"], word_count, read_time,
    )

    # ── Record output for learning hub ────────────────────────────────────
    await record_agent_output(
        agent_name="content_writer",
        output_type="blog_post",
        content={"title": result["title"], "topic": topic, "word_count": word_count},
        outcome="success",
        metrics={"word_count": word_count, "read_time": read_time},
        source_instruction_id=instr_id,
    )

    return result


async def _save_blog_post(data: dict, db: AsyncSession | None) -> str:
    """Persist a blog post dict to the database. Returns the new post ID."""

    async def _insert(session: AsyncSession) -> str:
        post = BlogPost(
            title=data["title"],
            slug=data["slug"],
            topic=data["topic"],
            content=data["content"],
            seo_keywords=data.get("seo_keywords", []),
            estimated_read_time=data["estimated_read_time"],
            word_count=data["word_count"],
        )
        session.add(post)
        await session.flush()
        return post.id

    if db is not None:
        return await _insert(db)

    async with AsyncSessionLocal() as session:
        post_id = await _insert(session)
        await session.commit()
        return post_id


# ─────────────────────────────────────────────
# Batch generation (for background scheduler)
# ─────────────────────────────────────────────

async def generate_weekly_posts(count: int = 2) -> list[dict]:
    """Generate `count` blog posts — prioritising hub-recommended topics.

    If the learning hub has viral topics, they are used first.
    Falls back to SUGGESTED_TOPICS rotation otherwise.
    """
    async with AsyncSessionLocal() as db:
        from sqlalchemy import func
        result = await db.execute(select(func.count()).select_from(BlogPost))
        existing_count = result.scalar() or 0

    # ── Learning hub topic override ───────────────────────────────────────
    hub_topics: list[str] = []
    try:
        insights = await get_content_insights()
        viral = insights.get("viral_topics", [])
        # Strip confidence annotations for use as topics
        hub_topics = [
            t.split(" (")[0].strip()
            for t in viral
            if t and len(t) > 5
        ][:count]
        if hub_topics:
            logger.info("ContentWriter: using %d hub-recommended topics", len(hub_topics))
    except Exception:
        pass

    results = []
    for i in range(count):
        # Prefer hub-recommended topics; fall back to rotation
        if i < len(hub_topics):
            topic = hub_topics[i]
        else:
            topic_index = (existing_count + i) % len(SUGGESTED_TOPICS)
            topic = SUGGESTED_TOPICS[topic_index]
        try:
            post = await generate_blog_post(topic, save_to_db=True)
            results.append(post)
            await asyncio.sleep(2)
        except Exception as exc:
            logger.error("Weekly blog generation failed for topic '%s': %s", topic, exc)

    logger.info("Weekly blog generation complete: %d posts created", len(results))
    return results


async def generate_monthly_guide(topic: str | None = None) -> dict:
    """Generate one comprehensive long-form guide (~2000 words).

    Called by the monthly background scheduler.
    """
    guide_topic = topic or "The Complete Beginner's Guide to AI-Powered Trading"
    logger.info("Generating monthly guide: %s", guide_topic)
    return await generate_blog_post(guide_topic, save_to_db=True)


# ─────────────────────────────────────────────
# Placeholder fallback
# ─────────────────────────────────────────────

def _placeholder_post(topic: str, error: str = "Content generation failed") -> dict:
    """Return a minimal placeholder when generation fails."""
    slug = f"{make_slug(topic)}-{uuid.uuid4().hex[:6]}"
    return {
        "id": None,
        "title": topic,
        "slug": slug,
        "topic": topic,
        "content": f"# {topic}\n\nContent generation is temporarily unavailable.",
        "seo_keywords": [],
        "estimated_read_time": 1,
        "word_count": 0,
        "meta_description": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }
