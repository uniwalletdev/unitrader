"""
routers/whatsapp_webhooks.py — Twilio WhatsApp webhook + account-linking API.

Endpoints:
    POST /webhooks/whatsapp                    — Receive updates from Twilio
    POST /api/whatsapp/generate-code           — (Authenticated) Generate a 6-digit link code
    POST /api/whatsapp/complete-link           — (Authenticated) Complete a bot-initiated link
    GET  /api/whatsapp/link-status             — (Authenticated) Check link status
    DELETE /api/whatsapp/unlink                — (Authenticated) Remove a linked account

Twilio request validation:
  In production, every inbound webhook is verified using the X-Twilio-Signature
  HMAC header.  Validation is skipped in development (ENVIRONMENT != production)
  so you can test with curl / ngrok without needing a real signature.
"""

import logging
import random
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import TelegramLinkingCode, User, UserExternalAccount
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

_PLATFORM = "whatsapp"

# ─────────────────────────────────────────────
# Bot singleton reference (set from main.py)
# ─────────────────────────────────────────────

_whatsapp_bot_service = None


def set_whatsapp_bot_service(service) -> None:
    global _whatsapp_bot_service
    _whatsapp_bot_service = service


def get_whatsapp_bot_service():
    return _whatsapp_bot_service


# ─────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────

webhook_router = APIRouter(prefix="/webhooks", tags=["WhatsApp Webhook"])
linking_router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp Linking"])


# ─────────────────────────────────────────────
# POST /webhooks/whatsapp
# ─────────────────────────────────────────────

@webhook_router.post("/whatsapp", include_in_schema=False)
async def whatsapp_webhook(
    request: Request,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
):
    """Receive and dispatch a Twilio WhatsApp update.

    Signature validation is enforced in production; skipped in development.
    """
    svc = _whatsapp_bot_service
    if not svc:
        # Bot not initialised — still return 200 to prevent Twilio retries
        return {"status": "ok"}

    # ── Parse Twilio form-data payload ────────────────────────────────────────
    form = await request.form()

    # ── Signature validation (production only) ────────────────────────────────
    if settings.is_production:
        try:
            from twilio.request_validator import RequestValidator
            validator    = RequestValidator(settings.twilio_auth_token)
            webhook_url  = f"{settings.api_base_url}/webhooks/whatsapp"
            form_dict    = dict(form)
            if not validator.validate(webhook_url, form_dict, x_twilio_signature or ""):
                logger.warning("Invalid Twilio signature on WhatsApp webhook")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Twilio signature",
                )
        except ImportError:
            logger.warning("twilio package not available — skipping signature validation")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Twilio signature validation error: %s", exc)

    from_field   = form.get("From", "")
    message_body = form.get("Body", "").strip()

    if not from_field:
        return {"status": "ok"}   # empty update — ignore

    try:
        await svc.handle_incoming_message(from_field, message_body)
    except Exception as exc:
        logger.error("Error handling WhatsApp message from %s: %s", from_field, exc)
        # Don't re-raise — a 500 would cause Twilio to retry indefinitely

    return {"status": "ok"}


# ─────────────────────────────────────────────
# POST /api/whatsapp/generate-code
# ─────────────────────────────────────────────

class GenerateCodeResponse(BaseModel):
    code: str
    expires_at: str
    instructions: str


@linking_router.post(
    "/generate-code",
    response_model=GenerateCodeResponse,
    summary="Generate a 6-digit OTP to link WhatsApp",
)
async def generate_link_code(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a one-time code the user can send via WhatsApp as: LINK 123456.

    Old unused codes for this user are removed immediately.
    New code expires in 15 minutes and is single-use.
    """
    # Clean up stale codes
    old = await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.user_id  == current_user.id,
            TelegramLinkingCode.is_used  == False,  # noqa: E712
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
            "Open WhatsApp and message your Unitrader bot number:\n"
            f"LINK {code}\n\n"
            "The code expires in 15 minutes."
        ),
    )


# ─────────────────────────────────────────────
# POST /api/whatsapp/complete-link
# ─────────────────────────────────────────────

class CompleteLinkRequest(BaseModel):
    code: str
    user_id: str


@linking_router.post(
    "/complete-link",
    summary="Complete a bot-initiated WhatsApp link (called from web UI)",
)
async def complete_link(
    body: CompleteLinkRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete the bot-initiated flow: the bot stored code + phone number;
    the web app calls this after the user authenticates and enters the code.
    """
    if current_user.id != body.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    now = datetime.now(timezone.utc)
    row = (await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.code     == body.code,
            TelegramLinkingCode.is_used  == False,  # noqa: E712
            TelegramLinkingCode.expires_at > now,
        )
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    # The phone number was stored by the bot in telegram_user_id
    phone = row.telegram_user_id
    if not phone:
        raise HTTPException(
            status_code=400,
            detail=(
                "This code was not initiated from WhatsApp. "
                "Send 'LINK CODE' from WhatsApp instead."
            ),
        )

    # Guard: already linked?
    existing = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.user_id  == current_user.id,
            UserExternalAccount.platform == _PLATFORM,
        )
    )).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A WhatsApp number is already linked. Unlink it first.",
        )

    row.is_used  = True
    row.used_at  = now
    row.user_id  = current_user.id

    db.add(UserExternalAccount(
        user_id=current_user.id,
        platform=_PLATFORM,
        external_id=phone,
        external_username=phone,
        is_linked=True,
        settings={"notifications": True, "trade_alerts": True},
    ))
    await db.commit()

    return {"status": "linked", "platform": _PLATFORM}


# ─────────────────────────────────────────────
# GET /api/whatsapp/link-status
# ─────────────────────────────────────────────

@linking_router.get("/link-status", summary="Check whether WhatsApp is linked")
async def link_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.user_id  == current_user.id,
            UserExternalAccount.platform == _PLATFORM,
            UserExternalAccount.is_linked == True,  # noqa: E712
        )
    )).scalar_one_or_none()

    if ext:
        return {
            "linked": True,
            "whatsapp_number": ext.external_id,
            "linked_at": ext.linked_at.isoformat() if ext.linked_at else None,
            "last_used_at": ext.last_used_at.isoformat() if ext.last_used_at else None,
        }
    return {"linked": False}


# ─────────────────────────────────────────────
# DELETE /api/whatsapp/unlink
# ─────────────────────────────────────────────

@linking_router.delete("/unlink", summary="Unlink WhatsApp from this account")
async def unlink_whatsapp(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.user_id  == current_user.id,
            UserExternalAccount.platform == _PLATFORM,
        )
    )).scalar_one_or_none()

    if not ext:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No linked WhatsApp account found",
        )

    await db.delete(ext)
    await db.commit()
    return {"status": "unlinked"}
