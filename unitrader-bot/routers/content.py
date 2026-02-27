"""
routers/content.py — Content marketing API endpoints for Unitrader.

Endpoints:
    GET  /api/content/blog-posts          — List published blog posts
    GET  /api/content/blog-posts/{slug}   — Get a single blog post
    POST /api/content/generate-blog       — Generate a new blog post
    GET  /api/content/topics              — List suggested blog topics
    GET  /api/content/social-calendar     — 30-day social media schedule
    POST /api/content/generate-social     — Generate social posts for a topic
    GET  /api/content/social-posts        — List all stored social posts
    POST /api/content/blog-posts/{id}/publish — Publish a draft blog post
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import BlogPost, SocialPost
from routers.auth import get_current_user
from src.agents.marketing.content_writer import (
    SUGGESTED_TOPICS,
    generate_blog_post,
)
from src.agents.marketing.social_media import (
    PLATFORMS,
    generate_social_posts,
    get_social_calendar,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/content", tags=["Content"])


# ─────────────────────────────────────────────
# Request bodies
# ─────────────────────────────────────────────

class GenerateBlogRequest(BaseModel):
    topic: str = Field(..., min_length=5, max_length=300)


class GenerateSocialRequest(BaseModel):
    topic: str = Field(..., min_length=5, max_length=300)
    count: int = Field(5, ge=1, le=20)
    platforms: list[str] | None = Field(
        None,
        description=f"Subset of: {PLATFORMS}. Defaults to all.",
    )


# ─────────────────────────────────────────────
# GET /api/content/topics
# ─────────────────────────────────────────────

@router.get("/topics")
async def list_topics(current_user=Depends(get_current_user)):
    """Return the built-in list of suggested blog post topics.

    Use any of these with POST /api/content/generate-blog, or supply your own.
    """
    return {
        "status": "success",
        "data": {
            "count": len(SUGGESTED_TOPICS),
            "topics": SUGGESTED_TOPICS,
        },
    }


# ─────────────────────────────────────────────
# GET /api/content/blog-posts
# ─────────────────────────────────────────────

@router.get("/blog-posts")
async def list_blog_posts(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    published_only: bool = Query(False, description="Only return published posts"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List all stored blog posts, newest first.

    Set published_only=true to return only posts that have been published.
    """
    query = select(BlogPost)
    if published_only:
        query = query.where(BlogPost.is_published == True)  # noqa: E712
    query = query.order_by(BlogPost.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    posts = result.scalars().all()

    return {
        "status": "success",
        "data": {
            "count": len(posts),
            "posts": [_blog_to_dict(p, include_content=False) for p in posts],
        },
    }


# ─────────────────────────────────────────────
# GET /api/content/blog-posts/{slug}
# ─────────────────────────────────────────────

@router.get("/blog-posts/{slug}")
async def get_blog_post(
    slug: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a single blog post by its URL slug, including full content."""
    result = await db.execute(
        select(BlogPost).where(BlogPost.slug == slug)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blog post '{slug}' not found",
        )
    return {"status": "success", "data": _blog_to_dict(post, include_content=True)}


# ─────────────────────────────────────────────
# POST /api/content/generate-blog
# ─────────────────────────────────────────────

@router.post("/generate-blog", status_code=status.HTTP_201_CREATED)
async def generate_blog(
    body: GenerateBlogRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new AI-written blog post on the given topic.

    The post is saved to the database as a draft (is_published=False).
    Use POST /api/content/blog-posts/{id}/publish to make it live.

    Note: generation takes ~20–40 seconds due to the Claude API call.
    """
    result = await generate_blog_post(
        topic=body.topic,
        save_to_db=True,
        db=db,
    )
    if result.get("error"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=result["error"],
        )
    return {"status": "success", "data": result}


# ─────────────────────────────────────────────
# POST /api/content/blog-posts/{id}/publish
# ─────────────────────────────────────────────

@router.post("/blog-posts/{post_id}/publish")
async def publish_blog_post(
    post_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a draft blog post as published and set its published_at timestamp."""
    result = await db.execute(
        select(BlogPost).where(BlogPost.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blog post not found",
        )
    if post.is_published:
        return {
            "status": "success",
            "data": {"message": "Post is already published", **_blog_to_dict(post)},
        }

    post.is_published = True
    post.published_at = datetime.now(timezone.utc)

    return {
        "status": "success",
        "data": {
            "message": f"'{post.title}' is now published",
            **_blog_to_dict(post),
        },
    }


# ─────────────────────────────────────────────
# GET /api/content/social-calendar
# ─────────────────────────────────────────────

@router.get("/social-calendar")
async def get_calendar(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=90, description="How many days of calendar to return"),
):
    """Return the upcoming social media posting schedule.

    Posts are grouped by date for easy calendar display.
    """
    posts = await get_social_calendar(days=days, db=db)

    # Group by date
    grouped: dict[str, list] = {}
    for post in posts:
        date_key = (post["scheduled_for"] or "")[:10]  # YYYY-MM-DD
        grouped.setdefault(date_key, []).append(post)

    return {
        "status": "success",
        "data": {
            "days": days,
            "total_posts": len(posts),
            "calendar": grouped,
        },
    }


# ─────────────────────────────────────────────
# POST /api/content/generate-social
# ─────────────────────────────────────────────

@router.post("/generate-social", status_code=status.HTTP_201_CREATED)
async def generate_social(
    body: GenerateSocialRequest,
    current_user=Depends(get_current_user),
):
    """Generate a batch of social media posts for the given topic.

    Posts are saved to the database and automatically scheduled starting tomorrow.
    """
    # Validate platform list
    if body.platforms:
        invalid = [p for p in body.platforms if p not in PLATFORMS]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid platforms: {invalid}. Valid: {PLATFORMS}",
            )

    results = await generate_social_posts(
        topic=body.topic,
        count=body.count,
        platforms=body.platforms,
        save_to_db=True,
    )

    return {
        "status": "success",
        "data": {
            "count": len(results),
            "posts": results,
        },
    }


# ─────────────────────────────────────────────
# GET /api/content/social-posts
# ─────────────────────────────────────────────

@router.get("/social-posts")
async def list_social_posts(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    platform: str | None = Query(None, description=f"Filter by platform: {PLATFORMS}"),
    post_type: str | None = Query(None),
    unposted_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all stored social media posts with optional filters."""
    query = select(SocialPost)
    if platform:
        query = query.where(SocialPost.platform == platform)
    if post_type:
        query = query.where(SocialPost.post_type == post_type)
    if unposted_only:
        query = query.where(SocialPost.is_posted == False)  # noqa: E712
    query = query.order_by(SocialPost.scheduled_for.asc().nullslast()).limit(limit).offset(offset)

    result = await db.execute(query)
    posts = result.scalars().all()

    return {
        "status": "success",
        "data": {
            "count": len(posts),
            "posts": [_social_to_dict(p) for p in posts],
        },
    }


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _blog_to_dict(post: BlogPost, include_content: bool = True) -> dict:
    d = {
        "id": post.id,
        "title": post.title,
        "slug": post.slug,
        "topic": post.topic,
        "seo_keywords": post.seo_keywords or [],
        "estimated_read_time": post.estimated_read_time,
        "word_count": post.word_count,
        "is_published": post.is_published,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "published_at": post.published_at.isoformat() if post.published_at else None,
    }
    if include_content:
        d["content"] = post.content
    return d


def _social_to_dict(post: SocialPost) -> dict:
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
