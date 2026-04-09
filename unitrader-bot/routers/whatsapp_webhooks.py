"""
routers/whatsapp_webhooks.py — Twilio WhatsApp webhook + account-linking API.

Endpoints:
    GET  /webhooks/whatsapp                    — Probe (200) — confirms traffic reaches the app
    POST /webhooks/whatsapp                    — Receive updates from Twilio (also POST …/whatsapp/)
    POST /api/whatsapp/generate-code           — (Authenticated) Generate a 6-digit link code
    POST /api/whatsapp/complete-link           — (Authenticated) Complete a bot-initiated link
    GET  /api/whatsapp/link-status             — (Authenticated) Check link status
    DELETE /api/whatsapp/unlink                — (Authenticated) Remove a linked account

Twilio request validation:
  In production, every inbound webhook is verified using the X-Twilio-Signature
  HMAC header. The signed URL is taken from X-Forwarded-Proto / Host (Railway),
  not API_BASE_URL, so the hostname Twilio calls must match what the edge forwards.

Railway: if Twilio shows 404 with body "Application not found" and header
  x-railway-fallback: true, the edge did not reach this process — check the
  service has a public domain, deployment is healthy, and GET /webhooks/whatsapp
  returns 200 from the same host you configured in Twilio.
"""

import asyncio
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
from database import AsyncSessionLocal
from models import BotMessage, OnboardingMessage, TelegramLinkingCode, User, UserExternalAccount
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

_PLATFORM = "whatsapp"

# ─────────────────────────────────────────────
# Simulated typing indicator (acknowledgement)
# ─────────────────────────────────────────────

try:
    from twilio.rest import Client
except Exception:  # pragma: no cover
    Client = None  # type: ignore[assignment]

twilio_client = (
    Client(settings.twilio_account_sid, settings.twilio_auth_token)
    if Client and settings.whatsapp_enabled
    else None
)

TYPING_ACKNOWLEDGEMENTS = [
    "On it...",
    "Let me check that for you...",
    "Thinking...",
    "Looking into that now...",
    "Give me a moment...",
]


def _is_genuine_user_text(form: dict) -> bool:
    """Return True only for inbound user text messages (not delivery/read callbacks)."""
    body = (form.get("Body") or "").strip()
    if not body:
        return False
    # Twilio status callbacks include MessageStatus/SmsStatus without a real user body.
    # If present and not "received", treat as non-user event.
    sms_status = (form.get("SmsStatus") or "").strip().lower()
    msg_status = (form.get("MessageStatus") or "").strip().lower()
    if sms_status and sms_status != "received":
        return False
    if msg_status and msg_status != "received":
        return False
    return True


def _twilio_webhook_request_url(request: Request) -> str:
    """Rebuild the exact public URL Twilio POSTed to (required for signature validation).

    Railway sets X-Forwarded-Proto and Host; if we use API_BASE_URL here and it is wrong
    or out of date, validation fails with 403. The request headers are authoritative.
    """
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https")
    proto = proto.split(",")[0].strip()
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or ""
    )
    host = host.split(",")[0].strip()
    if not host:
        host = request.url.netloc
    path = request.url.path
    qs = request.url.query
    base = f"{proto}://{host}{path}"
    return f"{base}?{qs}" if qs else base

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
# GET /webhooks/whatsapp — probe (browser / uptime); Twilio uses POST only for messages
# ─────────────────────────────────────────────

@webhook_router.get("/whatsapp", include_in_schema=False)
async def whatsapp_webhook_probe():
    """Lightweight 200 so operators can verify the route reaches the app (not Railway edge 404)."""
    return {"status": "ok", "webhook": "whatsapp"}


# ─────────────────────────────────────────────
# POST /webhooks/whatsapp  (+ trailing slash so proxies do not 307 POST away)
# ─────────────────────────────────────────────

@webhook_router.post("/whatsapp", include_in_schema=False)
@webhook_router.post("/whatsapp/", include_in_schema=False)
async def whatsapp_webhook(
    request: Request,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
):
    """Receive and dispatch a Twilio WhatsApp update.

    Signature validation is enforced in production; skipped in development.
    Returns 200 immediately after validation + ack, then processes the
    message in a background task to avoid Twilio timeout retries.
    """
    svc = _whatsapp_bot_service
    if not svc:
        # Bot not initialised — still return 200 to prevent Twilio retries
        return {"status": "ok"}

    # ── Parse Twilio form-data payload ────────────────────────────────────────
    form = await request.form()
    # Snapshot form data before the request scope closes
    form_dict = dict(form)

    # ── Signature validation (production only) ────────────────────────────────
    if settings.is_production:
        try:
            from twilio.request_validator import RequestValidator
            validator    = RequestValidator(settings.twilio_auth_token)
            webhook_url  = _twilio_webhook_request_url(request)
            sig_valid    = validator.validate(webhook_url, form_dict, x_twilio_signature or "")
            if not sig_valid:
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

    from_field = form_dict.get("From", "")
    message_body = (form_dict.get("Body") or "").strip()

    if not from_field:
        return {"status": "ok"}   # empty update — ignore

    # STEP 1 — send acknowledgement instantly for genuine user text messages
    if _is_genuine_user_text(form_dict) and twilio_client:
        try:
            to = from_field
            ack = random.choice(TYPING_ACKNOWLEDGEMENTS)
            # Twilio client is synchronous; send sequentially before AI generation.
            twilio_client.messages.create(
                from_=f"whatsapp:{settings.twilio_whatsapp_number}",
                to=to,
                body=ack,
            )
            # Best-effort: persist acknowledgement as assistant history (linked users only).
            phone = from_field.removeprefix("whatsapp:").strip()
            async with AsyncSessionLocal() as db:
                ext = (
                    await db.execute(
                        select(UserExternalAccount).where(
                            UserExternalAccount.platform == _PLATFORM,
                            UserExternalAccount.external_id == phone,
                            UserExternalAccount.is_linked == True,  # noqa: E712
                        )
                    )
                ).scalar_one_or_none()
                if ext and ext.user_id:
                    db.add(OnboardingMessage(user_id=str(ext.user_id), role="assistant", content=ack))
                    await db.commit()
        except Exception as exc:
            logger.warning("Failed to send WhatsApp acknowledgement: %s", exc)

    # STEP 2 — dispatch heavy processing as a background task and return 200 now
    asyncio.create_task(_process_whatsapp_message(svc, from_field, message_body))

    return {"status": "ok"}


async def _process_whatsapp_message(svc, from_field: str, message_body: str) -> None:
    """Background task: run the bot handler + persist the response history."""
    try:
        await svc.handle_incoming_message(from_field, message_body)
        # Persist the final bot response to onboarding_messages (assistant)
        try:
            phone = from_field.removeprefix("whatsapp:").strip()
            async with AsyncSessionLocal() as db:
                ext = (
                    await db.execute(
                        select(UserExternalAccount).where(
                            UserExternalAccount.platform == _PLATFORM,
                            UserExternalAccount.external_id == phone,
                            UserExternalAccount.is_linked == True,  # noqa: E712
                        )
                    )
                ).scalar_one_or_none()
                if ext and ext.user_id:
                    last = (
                        await db.execute(
                            select(BotMessage)
                            .where(
                                BotMessage.platform == _PLATFORM,
                                BotMessage.external_user_id == phone,
                            )
                            .order_by(BotMessage.created_at.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if last and last.bot_response:
                        db.add(
                            OnboardingMessage(
                                user_id=str(ext.user_id),
                                role="assistant",
                                content=str(last.bot_response),
                            )
                        )
                        await db.commit()
        except Exception as exc:
            logger.warning("Failed to persist WhatsApp bot response history: %s", exc)
    except Exception as e:
        logger.error(
            "Orchestrator call failed: %s: %s", type(e).__name__, e, exc_info=True
        )
        logger.error("Error handling WhatsApp message from %s: %s", from_field, e)


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
