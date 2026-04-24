"""
routers/etoro_offer.py — Dismissible /trade banner offering eToro to
post-onboarding users who haven't yet connected any exchange.

Endpoints:
    GET  /api/etoro/offer-card          — Should the card render? + copy
    POST /api/etoro/offer-card/dismiss  — Mark the card as interacted with

Show the card only when ALL of these hold:
  * settings.feature_etoro_enabled is True
  * user's onboarding_complete is True
  * user's class_detected_at is not None
  * user has no active ExchangeAPIKey row
  * user_settings.etoro_offer_dismissed_at is None

Copy is tailored per ``trader_class`` using the shared
``_ETORO_OFFER_CARD_COPY`` dict in ``src/agents/core/conversation_agent.py``.
Never hardcodes "Apex" — the ``{ai_name}`` placeholder is substituted with
the user's chosen AI name before returning the payload.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings as app_settings
from database import get_db
from models import ExchangeAPIKey, UserSettings
from routers.auth import get_current_user
from src.agents.core.conversation_agent import _ETORO_OFFER_CARD_COPY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/etoro", tags=["eToro Offer"])


async def _user_has_any_active_exchange(user_id: str, db: AsyncSession) -> bool:
    row = (await db.execute(
        select(ExchangeAPIKey.id).where(
            ExchangeAPIKey.user_id == user_id,
            ExchangeAPIKey.is_active == True,  # noqa: E712
        ).limit(1)
    )).first()
    return row is not None


@router.get("/offer-card")
async def get_offer_card(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return ``{show, environment, headline, body, cta}`` or
    ``{show: false}`` when any gate fails.

    Never raises on gate-failure — a declined offer is not an error.
    """
    # (1) Feature flag
    if not bool(getattr(app_settings, "feature_etoro_enabled", False)):
        return {"show": False}

    # (2) Fetch user-settings row once
    us: UserSettings | None = (await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )).scalar_one_or_none()
    if us is None:
        return {"show": False}

    # (3) Onboarding must be complete — card is POST-onboarding surface
    if not bool(getattr(us, "onboarding_complete", False)):
        return {"show": False}

    # (4) Class must have been detected
    if getattr(us, "class_detected_at", None) is None:
        return {"show": False}

    trader_class = (getattr(us, "trader_class", None) or "").strip()
    if trader_class not in _ETORO_OFFER_CARD_COPY:
        return {"show": False}

    # (5) Already accepted/dismissed once — never re-show
    if getattr(us, "etoro_offer_dismissed_at", None) is not None:
        return {"show": False}

    # (6) User already has a connected exchange — no offer needed
    if await _user_has_any_active_exchange(current_user.id, db):
        return {"show": False}

    # All gates pass — render the class-tailored card.
    entry = _ETORO_OFFER_CARD_COPY[trader_class]
    ai_name = (getattr(us, "ai_name", None) or "Apex").strip() or "Apex"
    return {
        "show": True,
        "trader_class": trader_class,
        "environment": entry["environment"],  # "demo" | "real"
        "headline": entry["headline"],
        "body": entry["body"].format(ai_name=ai_name),
        "cta": entry["cta"],
    }


@router.post("/offer-card/dismiss")
async def dismiss_offer_card(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark the eToro offer card as interacted with.

    Called by the frontend on both Accept and Dismiss paths — once set,
    the card never reappears for that user. Idempotent: re-calling when
    already dismissed is a no-op.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(UserSettings)
        .where(
            UserSettings.user_id == current_user.id,
            UserSettings.etoro_offer_dismissed_at.is_(None),
        )
        .values(etoro_offer_dismissed_at=now)
    )
    await db.commit()
    return {"ok": True, "updated": int(result.rowcount or 0)}
