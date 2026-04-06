"""Resolve the user's personalised AI companion name for notifications and UI."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, UserSettings


async def get_user_ai_name(user_id: str, db: AsyncSession) -> str:
    """Return settings.ai_name, else users.ai_name, else 'Apex'."""
    r = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = r.scalar_one_or_none()
    if settings is not None:
        raw = getattr(settings, "ai_name", None)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    ur = await db.execute(select(User.ai_name).where(User.id == user_id))
    row = ur.first()
    if row and row[0] and str(row[0]).strip():
        return str(row[0]).strip()
    return "Apex"
