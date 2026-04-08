"""Create a provisional (chat-only) Unitrader User from a messaging platform.

Provisional users have:
  - A placeholder email: {platform}_{external_id}@provisional.unitrader.app
  - A random unusable password hash (can't web-login until they claim)
  - A 14-day free trial
  - A linked UserExternalAccount

They can later "claim" their account on the web, which upgrades the email
and merges all data (trades, conversations, external accounts).
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, UserExternalAccount, UserSettings

logger = logging.getLogger(__name__)

PROVISIONAL_DOMAIN = "provisional.unitrader.app"


def is_provisional(user: User) -> bool:
    """Return True if the user was created from a chat platform (no web account yet)."""
    return (user.email or "").endswith(f"@{PROVISIONAL_DOMAIN}")


async def create_provisional_user(
    db: AsyncSession,
    platform: str,
    external_id: str,
    external_username: str | None = None,
) -> User:
    """Create a User + UserSettings + UserExternalAccount for a chat-first user.

    If the external account already exists, returns the existing linked User.
    """
    # Guard: already linked?
    existing_ext = (
        await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.platform == platform,
                UserExternalAccount.external_id == external_id,
            )
        )
    ).scalar_one_or_none()

    if existing_ext:
        user = (
            await db.execute(select(User).where(User.id == existing_ext.user_id))
        ).scalar_one_or_none()
        if user:
            return user

    # Build placeholder email — unique per platform + external_id
    safe_id = external_id.lstrip("+").replace(" ", "")
    placeholder_email = f"{platform}_{safe_id}@{PROVISIONAL_DOMAIN}"

    # Edge-case: email row already exists
    dup = (
        await db.execute(select(User).where(User.email == placeholder_email))
    ).scalar_one_or_none()
    if dup:
        # Ensure external account link exists
        ext = (
            await db.execute(
                select(UserExternalAccount).where(
                    UserExternalAccount.user_id == dup.id,
                    UserExternalAccount.platform == platform,
                )
            )
        ).scalar_one_or_none()
        if not ext:
            db.add(
                UserExternalAccount(
                    user_id=dup.id,
                    platform=platform,
                    external_id=external_id,
                    external_username=external_username or external_id,
                    is_linked=True,
                    settings={"notifications": True, "trade_alerts": True},
                )
            )
            await db.commit()
        return dup

    from security import hash_password

    now = datetime.now(timezone.utc)

    user = User(
        email=placeholder_email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        ai_name="Apex",
        trial_started_at=now,
        trial_end_date=now + timedelta(days=14),
        trial_status="active",
    )
    db.add(user)
    await db.flush()

    db.add(UserSettings(user_id=user.id))
    db.add(
        UserExternalAccount(
            user_id=user.id,
            platform=platform,
            external_id=external_id,
            external_username=external_username or external_id,
            is_linked=True,
            settings={"notifications": True, "trade_alerts": True},
        )
    )
    await db.commit()
    await db.refresh(user)

    logger.info(
        "Provisional user created: %s via %s (%s)", user.id, platform, external_id
    )
    return user
