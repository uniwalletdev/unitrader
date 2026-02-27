"""
src/agents/marketing/social_media.py — AI social media post generation agent.

Generates platform-optimised social media posts in four content types:
  educational | social_proof | call_to_action | inspirational

Posts are stored in the SocialPost table and can be scheduled across
a 30-day content calendar.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import SocialPost, Trade
from src.utils.json_parser import parse_claude_json

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-3-haiku-20240307"
_MAX_TOKENS = 2048

Platform = Literal["twitter", "linkedin", "instagram", "facebook"]
PostType = Literal["educational", "social_proof", "call_to_action", "inspirational"]

PLATFORMS: list[Platform] = ["twitter", "linkedin", "instagram", "facebook"]

# Character limits per platform
CHAR_LIMITS: dict[str, int] = {
    "twitter": 280,
    "linkedin": 3000,
    "instagram": 2200,
    "facebook": 63206,
}

# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

_SOCIAL_SYSTEM_PROMPT = """\
You are a social media marketing expert specialising in fintech and AI trading platforms.

You write posts that feel authentic, valuable, and shareable — never generic or spammy.

POST TYPE GUIDELINES:
- **educational**: Teach one concrete thing. Lead with the insight. End with a question.
- **social_proof**: Share a real-feeling data point or user success story. Keep it credible.
- **call_to_action**: Invite action naturally. Solve a problem they recognise. One clear CTA.
- **inspirational**: Motivational but grounded. Tie inspiration back to trading discipline.

PLATFORM RULES:
- twitter: ≤280 characters. Punchy. 2–4 hashtags. Emoji sparingly but strategically.
- linkedin: 150–300 words. Professional tone. Insight-first. 3–5 hashtags at the end.
- instagram: Visual-first caption feel. Story-like. 5–8 hashtags. Emoji-friendly.
- facebook: Conversational. Medium length. 1–3 hashtags or none. Ask a question.

OUTPUT FORMAT — respond with valid JSON array only, no markdown fences:
[
  {
    "platform": "twitter" | "linkedin" | "instagram" | "facebook",
    "post_type": "educational" | "social_proof" | "call_to_action" | "inspirational",
    "content": "...",
    "hashtags": ["hashtag1", "hashtag2"],
    "estimated_engagement": "high" | "medium" | "low",
    "best_posting_time": "morning" | "afternoon" | "evening"
  }
]

Estimated engagement guidance:
- high: timely topic, strong hook, emotional resonance
- medium: useful but not urgent
- low: informational, lower shareability
"""


# ─────────────────────────────────────────────
# Platform stat injection
# ─────────────────────────────────────────────

async def _get_social_proof_stats() -> dict:
    """Fetch aggregate stats to use in social proof posts."""
    try:
        from sqlalchemy import func
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(
                    func.count(Trade.id).label("total"),
                    func.count(Trade.id).filter(Trade.profit.isnot(None)).label("wins"),
                ).where(Trade.status == "closed")
            )
            row = result.first()
            total = row.total or 1
            wins = row.wins or 0
            win_rate = round(wins / total * 100, 1) if total else 0
            return {"total_trades": total, "win_rate": win_rate}
    except Exception:
        return {"total_trades": 0, "win_rate": 0.0}


# ─────────────────────────────────────────────
# Main generation function
# ─────────────────────────────────────────────

async def generate_social_posts(
    topic: str,
    count: int = 5,
    platforms: list[Platform] | None = None,
    save_to_db: bool = True,
    scheduled_start: datetime | None = None,
) -> list[dict]:
    """Generate a varied set of social media posts for a given topic.

    Automatically distributes across four content types:
      1–2 educational, 1 social_proof, 1 call_to_action, 1 inspirational.

    Args:
        topic: Subject/angle for all posts in this batch.
        count: Number of posts to generate (default 5).
        platforms: Which platforms to target (default: all four).
        save_to_db: Persist posts to the database.
        scheduled_start: First scheduling slot (defaults to tomorrow 9 AM UTC).

    Returns:
        List of post dicts ready for the API response or background job.
    """
    if not settings.anthropic_api_key:
        logger.warning("Anthropic API key not set — cannot generate social posts")
        return _placeholder_posts(topic, count)

    target_platforms = platforms or PLATFORMS
    stats = await _get_social_proof_stats()

    # Distribute content types across the batch
    type_distribution = _get_type_distribution(count)

    stats_context = ""
    if stats["total_trades"] > 0:
        stats_context = (
            f"\n\nPLATFORM STATS (use where natural, don't force it):\n"
            f"- Trades analysed by Unitrader: {stats['total_trades']:,}\n"
            f"- Platform average win rate: {stats['win_rate']:.1f}%\n"
        )

    user_prompt = (
        f"Generate exactly {count} social media posts about: **{topic}**\n\n"
        f"Distribute across these content types: {', '.join(type_distribution)}\n"
        f"Target platforms: {', '.join(target_platforms)}\n"
        f"Assign one platform per post (rotate through them).\n"
        f"{stats_context}\n"
        "Output valid JSON array only. No markdown fences."
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        response = await client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SOCIAL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        posts_data = parse_claude_json(raw, context="social posts")
        if not isinstance(posts_data, list):
            raise ValueError(f"Expected JSON array, got {type(posts_data).__name__}")

    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Social posts JSON parse error: %s", exc)
        return _placeholder_posts(topic, count)
    except Exception as exc:
        logger.error("Social post generation failed: %s", exc)
        return _placeholder_posts(topic, count)

    # Validate char limits and enrich
    schedule_slots = _build_schedule_slots(
        count=len(posts_data),
        start=scheduled_start or _next_morning(),
    )

    results = []
    for i, post in enumerate(posts_data):
        platform = post.get("platform", "twitter")
        content = post.get("content", "")
        limit = CHAR_LIMITS.get(platform, 280)

        # Truncate if over platform limit (shouldn't happen but safety net)
        if platform == "twitter" and len(content) > limit:
            content = content[:limit - 3] + "..."

        enriched = {
            "id": None,
            "platform": platform,
            "post_type": post.get("post_type", "educational"),
            "content": content,
            "hashtags": post.get("hashtags", []),
            "estimated_engagement": post.get("estimated_engagement", "medium"),
            "best_posting_time": post.get("best_posting_time", "morning"),
            "topic": topic,
            "scheduled_for": schedule_slots[i].isoformat() if i < len(schedule_slots) else None,
            "char_count": len(content),
            "char_limit": limit,
        }
        results.append(enriched)

    if save_to_db:
        ids = await _save_social_posts(results)
        for i, post_id in enumerate(ids):
            if i < len(results):
                results[i]["id"] = post_id

    logger.info("Generated %d social posts for topic: %s", len(results), topic)
    return results


# ─────────────────────────────────────────────
# Daily batch (for scheduler)
# ─────────────────────────────────────────────

async def generate_daily_posts(count: int = 5) -> list[dict]:
    """Generate the day's social media batch.

    Rotates across a curated list of evergreen topics so the calendar
    stays varied even without manual intervention.
    """
    daily_topics = [
        "The power of automated risk management in trading",
        "How AI analyses 100+ indicators in seconds",
        "Why discipline beats intelligence in trading",
        "Understanding market volatility and how to profit from it",
        "The compound effect of small, consistent trading gains",
        "How to read market momentum signals",
        "Why most traders fail (and how to avoid those mistakes)",
    ]

    async with AsyncSessionLocal() as db:
        from sqlalchemy import func
        result = await db.execute(select(func.count()).select_from(SocialPost))
        count_existing = result.scalar() or 0

    topic = daily_topics[count_existing % len(daily_topics)]
    return await generate_social_posts(topic, count=count, save_to_db=True)


# ─────────────────────────────────────────────
# 30-day calendar builder
# ─────────────────────────────────────────────

async def get_social_calendar(
    days: int = 30,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Return all scheduled social posts for the next `days` days.

    If fewer than expected posts exist, generates enough to fill the calendar.
    """
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    async def _fetch(session: AsyncSession) -> list[SocialPost]:
        result = await session.execute(
            select(SocialPost)
            .where(
                SocialPost.scheduled_for >= now,
                SocialPost.scheduled_for <= end,
            )
            .order_by(SocialPost.scheduled_for.asc())
        )
        return result.scalars().all()

    if db is not None:
        posts = await _fetch(db)
    else:
        async with AsyncSessionLocal() as session:
            posts = await _fetch(session)

    return [_social_post_to_dict(p) for p in posts]


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _get_type_distribution(count: int) -> list[str]:
    """Return a balanced list of post types for `count` posts."""
    base = ["educational", "social_proof", "call_to_action", "inspirational"]
    result = []
    for i in range(count):
        # Extra posts default to educational
        result.append(base[i] if i < len(base) else "educational")
    return result


def _next_morning() -> datetime:
    """Return tomorrow at 09:00 UTC."""
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return tomorrow


def _build_schedule_slots(count: int, start: datetime) -> list[datetime]:
    """Spread `count` posts across days starting at `start`, one per day."""
    return [start + timedelta(days=i) for i in range(count)]


async def _save_social_posts(posts: list[dict]) -> list[str]:
    """Persist a batch of social post dicts to the database."""
    ids = []
    async with AsyncSessionLocal() as session:
        for post in posts:
            scheduled = None
            if post.get("scheduled_for"):
                try:
                    scheduled = datetime.fromisoformat(post["scheduled_for"])
                except (ValueError, TypeError):
                    pass

            row = SocialPost(
                platform=post["platform"],
                content=post["content"],
                hashtags=post.get("hashtags", []),
                post_type=post["post_type"],
                topic=post.get("topic"),
                estimated_engagement=post.get("estimated_engagement"),
                scheduled_for=scheduled,
            )
            session.add(row)
            await session.flush()
            ids.append(row.id)
        await session.commit()
    return ids


def _social_post_to_dict(post: SocialPost) -> dict:
    return {
        "id": post.id,
        "platform": post.platform,
        "post_type": post.post_type,
        "content": post.content,
        "hashtags": post.hashtags or [],
        "topic": post.topic,
        "estimated_engagement": post.estimated_engagement,
        "scheduled_for": post.scheduled_for.isoformat() if post.scheduled_for else None,
        "is_posted": post.is_posted,
        "created_at": post.created_at.isoformat() if post.created_at else None,
    }


def _placeholder_posts(topic: str, count: int) -> list[dict]:
    """Return minimal placeholder posts when Claude is unavailable."""
    types = _get_type_distribution(count)
    slots = _build_schedule_slots(count, _next_morning())
    return [
        {
            "id": None,
            "platform": PLATFORMS[i % len(PLATFORMS)],
            "post_type": types[i],
            "content": f"[{types[i].replace('_', ' ').title()}] {topic} — content unavailable (configure ANTHROPIC_API_KEY)",
            "hashtags": ["#trading", "#AI"],
            "estimated_engagement": "low",
            "best_posting_time": "morning",
            "topic": topic,
            "scheduled_for": slots[i].isoformat(),
            "char_count": 0,
            "char_limit": CHAR_LIMITS[PLATFORMS[i % len(PLATFORMS)]],
            "error": "Anthropic API key not configured",
        }
        for i in range(count)
    ]
