import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import AuditLog, BlogPost
from src.agents.marketing.content_writer import make_slug

logger = logging.getLogger(__name__)

LearningTopic = Literal["weekly_recap", "concept_explanation", "market_update"]


def _word_count(text: str) -> int:
    return len((text or "").split())


def _read_time_minutes(words: int) -> int:
    return max(1, round(words / 200))


def _extract_title(md: str, fallback: str) -> str:
    # Prefer first markdown heading, else first non-empty line.
    for line in (md or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()[:300] or fallback
    for line in (md or "").splitlines():
        s = line.strip()
        if s:
            return s[:300]
    return fallback[:300]


class ContentAgent:
    def __init__(self) -> None:
        self._claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate_learning_article(
        self,
        topic: str,
        related_trades: list,
    ) -> dict:
        """Generate a learning article and store it in blog_posts (published)."""
        if not settings.anthropic_api_key:
            raise RuntimeError("Anthropic API key not configured")

        from database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            concept: str | None = None

            if topic == "weekly_recap":
                since = now - timedelta(days=7)
                res = await db.execute(
                    select(AuditLog)
                    .where(AuditLog.event_type == "trade_decision", AuditLog.timestamp >= since)
                    .order_by(AuditLog.timestamp.asc())
                )
                logs = res.scalars().all()
                bullets: list[str] = []
                for l in logs[:50]:
                    d = l.event_details or {}
                    sym = d.get("symbol") or "?" 
                    side = d.get("side") or d.get("signal") or "?"
                    bullets.append(f"- {sym}: {side}")
                context = "\n".join(bullets) if bullets else "- (No recorded decisions this week)"
                prompt = (
                    "Write a 500-word educational article about how Apex traded this week.\n"
                    "Include: what signals Apex saw, what decisions it made, and what the outcomes were.\n"
                    "Write in plain English for a beginner investor. Heading: 'How Apex traded this week'.\n"
                    "Include a key lesson at the end.\n\n"
                    "Here are the recorded decisions (symbol + signal):\n"
                    f"{context}\n"
                )
                fallback_title = "How Apex traded this week"

            elif topic == "concept_explanation":
                # concept name can be passed as "concept_explanation:RSI" or via related_trades[0]
                concept = None
                if related_trades:
                    if isinstance(related_trades[0], str):
                        concept = related_trades[0]
                    elif isinstance(related_trades[0], dict):
                        concept = related_trades[0].get("concept")
                if concept is None:
                    concept = "RSI"
                concept = str(concept).strip()[:100]
                prompt = (
                    f"Write a 400-word plain-English explanation of {concept} for a complete beginner.\n"
                    "Include: what it is, why it matters, and how Apex uses it. Real-world analogy required.\n"
                )
                fallback_title = f"{concept} explained for beginners"

            else:  # market_update
                prompt = (
                    "Write a 450-word market update for a beginner investor.\n"
                    "Explain what's been happening recently, what it could mean for risk, and how Apex adapts.\n"
                    "Heading: 'Market update'. End with one practical tip.\n"
                )
                fallback_title = "Market update"

            system = (
                "You are Apex, a helpful trading tutor. "
                "Write clear, beginner-friendly educational content. "
                "Never give guarantees or financial advice. "
                "Output markdown with headings and short paragraphs."
            )

            resp = await self._claude.messages.create(
                model=settings.anthropic_model,
                max_tokens=1200,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            content = resp.content[0].text.strip()

            title = _extract_title(content, fallback_title)
            slug = make_slug(title)

            # Ensure slug uniqueness (append short suffix if needed)
            exists = await db.execute(select(BlogPost.id).where(BlogPost.slug == slug))
            if exists.scalar_one_or_none():
                suffix = re.sub(r"[^a-z0-9]", "", slug)[-6:] or "post"
                slug = f"{slug}-{suffix}-{now.strftime('%H%M%S')}"

            words = _word_count(content)
            read_mins = _read_time_minutes(words)

            post = BlogPost(
                title=title,
                slug=slug,
                topic=topic,
                category="learning",
                related_concept=concept if topic == "concept_explanation" else None,
                content=content,
                seo_keywords=None,
                estimated_read_time=read_mins,
                word_count=words,
                is_published=True,
                published_at=now,
            )
            db.add(post)
            await db.commit()

            return {
                "id": post.id,
                "title": post.title,
                "slug": post.slug,
                "content": post.content,
                "published": True,
                "category": post.category,
                "reading_time_minutes": post.estimated_read_time,
                "word_count": post.word_count,
                "related_concept": post.related_concept,
                "created_at": post.created_at.isoformat() if post.created_at else None,
            }
