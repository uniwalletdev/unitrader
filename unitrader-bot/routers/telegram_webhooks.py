"""
routers/telegram_webhooks.py — Telegram bot webhook + account-linking API.

Endpoints:
    POST /webhooks/telegram              — Receive updates from Telegram
    POST /api/telegram/generate-code     — (Authenticated) Generate a 6-digit link code
    POST /api/telegram/complete-link     — (Internal) Complete a bot-initiated link
    GET  /api/telegram/link-status       — (Authenticated) Check link status
    DELETE /api/telegram/unlink          — (Authenticated) Remove a linked account
"""

import logging
import random
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update

from config import settings
from database import get_db
from models import TelegramLinkingCode, User, UserExternalAccount
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Bot singleton reference (set from main.py)
# ─────────────────────────────────────────────

_telegram_bot_service = None


def set_telegram_bot_service(service) -> None:
    global _telegram_bot_service
    _telegram_bot_service = service


def get_telegram_bot_service():
    return _telegram_bot_service


# ─────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────

webhook_router = APIRouter(prefix="/webhooks", tags=["Telegram Webhook"])
linking_router = APIRouter(prefix="/api/telegram", tags=["Telegram Linking"])


# ─────────────────────────────────────────────
# POST /webhooks/telegram
# ─────────────────────────────────────────────

@webhook_router.post("/telegram", include_in_schema=False)
async def telegram_webhook(request: Request):
    """Receive and dispatch a Telegram update (called by Telegram's servers)."""
    svc = _telegram_bot_service
    if not svc:
        # Bot not yet initialised — silently accept to avoid Telegram retries
        return {"status": "ok"}

    try:
        raw = await request.json()
        update = Update.de_json(raw, svc.app.bot)
        await svc.process_update(update)
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("Error processing Telegram webhook")
        raise HTTPException(
            status_code=400,
            detail="Invalid or malformed Telegram update",
        )


# ─────────────────────────────────────────────
# POST /api/telegram/generate-code
# ─────────────────────────────────────────────

class GenerateCodeResponse(BaseModel):
    code: str
    expires_at: str
    instructions: str


@linking_router.post(
    "/generate-code",
    response_model=GenerateCodeResponse,
    summary="Generate a 6-digit OTP to link Telegram",
)
async def generate_link_code(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a one-time 6-digit code the user can send to @unitrader_bot via /link CODE.

    Codes expire in 15 minutes and are single-use.
    """
    # Expire any old unused codes for this user
    old = await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.user_id == current_user.id,
            TelegramLinkingCode.is_used == False,  # noqa: E712
        )
    )
    for row in old.scalars().all():
        await db.delete(row)

    code    = "".join(random.choices(string.digits, k=6))
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)

    db.add(TelegramLinkingCode(
        code=code,
        user_id=current_user.id,
        expires_at=expires,
    ))
    await db.commit()

    return GenerateCodeResponse(
        code=code,
        expires_at=expires.isoformat(),
        instructions=(
            "Open Telegram, search for @unitrader_bot and send:\n"
            f"/link {code}\n\n"
            "The code expires in 15 minutes."
        ),
    )


# ─────────────────────────────────────────────
# POST /api/telegram/complete-link
# ─────────────────────────────────────────────

class CompleteLinkRequest(BaseModel):
    code: str
    user_id: str


@linking_router.post(
    "/complete-link",
    summary="Complete a bot-initiated Telegram link (called from web UI)",
)
async def complete_link(
    body: CompleteLinkRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete the bot-initiated flow: the bot stored a code + telegram_user_id;
    the web app calls this endpoint after the user authenticates and enters the code.
    """
    if current_user.id != body.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    now = datetime.now(timezone.utc)
    row = (await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.code == body.code,
            TelegramLinkingCode.is_used == False,  # noqa: E712
            TelegramLinkingCode.expires_at > now,
        )
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    if not row.telegram_user_id:
        raise HTTPException(
            status_code=400,
            detail="This code was not initiated from Telegram. Use /link CODE in the bot instead.",
        )

    # Guard: already linked?
    existing = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.user_id == current_user.id,
            UserExternalAccount.platform == "telegram",
        )
    )).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="A Telegram account is already linked. Unlink it first.",
        )

    # Create the link
    row.is_used  = True
    row.used_at  = now
    row.user_id  = current_user.id

    db.add(UserExternalAccount(
        user_id=current_user.id,
        platform="telegram",
        external_id=row.telegram_user_id,
        external_username=row.telegram_username,
        is_linked=True,
        settings={"notifications": True, "trade_alerts": True},
    ))
    await db.commit()

    return {"status": "linked", "platform": "telegram"}


# ─────────────────────────────────────────────
# GET /api/telegram/link-status
# ─────────────────────────────────────────────

@linking_router.get("/link-status", summary="Check whether Telegram is linked")
async def link_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.user_id == current_user.id,
            UserExternalAccount.platform == "telegram",
            UserExternalAccount.is_linked == True,  # noqa: E712
        )
    )).scalar_one_or_none()

    if ext:
        return {
            "linked": True,
            "telegram_username": ext.external_username,
            "linked_at": ext.linked_at.isoformat() if ext.linked_at else None,
            "last_used_at": ext.last_used_at.isoformat() if ext.last_used_at else None,
        }
    return {"linked": False}


# ─────────────────────────────────────────────
# DELETE /api/telegram/unlink
# ─────────────────────────────────────────────

@linking_router.delete("/unlink", summary="Unlink Telegram from this account")
async def unlink_telegram(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.user_id == current_user.id,
            UserExternalAccount.platform == "telegram",
        )
    )).scalar_one_or_none()

    if not ext:
        raise HTTPException(status_code=404, detail="No linked Telegram account found")

    await db.delete(ext)
    await db.commit()
    return {"status": "unlinked"}


# ─────────────────────────────────────────────
# GET /api/telegram/status  (public diagnostic)
# ─────────────────────────────────────────────

@linking_router.get("/status", include_in_schema=False)
async def telegram_status():
    """Diagnostic endpoint — shows whether the bot service is running and what webhook is registered."""
    svc = _telegram_bot_service
    if not svc or not svc.app:
        token_configured = bool(settings.telegram_bot_token)
        return {
            "bot_initialized": False,
            "token_configured": token_configured,
            "reason": "Bot started successfully but service not set" if token_configured else "TELEGRAM_BOT_TOKEN env var is not set",
            "api_base_url": settings.api_base_url,
            "expected_webhook": f"{settings.api_base_url}/webhooks/telegram",
        }

    try:
        webhook_info = await svc.app.bot.get_webhook_info()
        bot_info     = await svc.app.bot.get_me()
        return {
            "bot_initialized": True,
            "bot_username": bot_info.username,
            "bot_id": bot_info.id,
            "webhook_url": webhook_info.url,
            "webhook_pending_count": webhook_info.pending_update_count,
            "webhook_last_error": webhook_info.last_error_message,
            "api_base_url": settings.api_base_url,
        }
    except Exception as exc:
        return {"bot_initialized": True, "error": str(exc)}


# ─────────────────────────────────────────────
# POST /api/telegram/reset-webhook  (admin only)
# ─────────────────────────────────────────────

class ResetWebhookRequest(BaseModel):
    admin_key: str
    webhook_url: str | None = None  # override; defaults to settings.api_base_url


@linking_router.post("/reset-webhook", include_in_schema=False)
async def reset_webhook(body: ResetWebhookRequest):
    """Re-register the Telegram webhook. Requires admin_key. Use after changing API_BASE_URL."""
    if not settings.admin_secret_key or body.admin_key != settings.admin_secret_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    svc = _telegram_bot_service
    if not svc or not svc.app:
        raise HTTPException(status_code=503, detail="Telegram bot service is not initialised. Check TELEGRAM_BOT_TOKEN env var.")

    url = body.webhook_url or f"{settings.api_base_url}/webhooks/telegram"
    try:
        await svc.set_webhook(url)
        return {"status": "ok", "webhook_url": url}
    except Exception as exc:
        logger.exception("Telegram set_webhook failed")
        raise HTTPException(
            status_code=500,
            detail="Failed to register Telegram webhook",
        )
