"""
routers/auth.py — Authentication endpoints for Unitrader.

Endpoints:
    POST /api/auth/register              — Create account
    POST /api/auth/verify-email          — Confirm email address
    POST /api/auth/login                 — Get JWT tokens
    POST /api/auth/logout                — Revoke refresh token
    POST /api/auth/refresh-token         — Issue new access token
    POST /api/auth/2fa/setup             — Generate TOTP secret + QR code
    POST /api/auth/2fa/verify            — Activate 2FA
    POST /api/auth/password-reset-request — Send reset email
    POST /api/auth/password-reset        — Apply new password
    GET  /api/auth/me                    — Current user profile
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import (
    AuditLog,
    ExchangeAPIKey,
    RefreshToken,
    TelegramLinkingCode,
    User,
    UserExternalAccount,
    UserSettings,
)
from schemas import (
    AccessTokenResponse,
    EmailVerifyRequest,
    LogoutRequest,
    PasswordResetBody,
    PasswordResetRequestBody,
    RefreshTokenRequest,
    SuccessResponse,
    TokenResponse,
    TwoFASetupResponse,
    TwoFAVerifyRequest,
    UserRegisterRequest,
    UserResponse,
    UserLoginRequest,
)
from security import (
    create_access_token,
    create_refresh_token,
    decrypt_field,
    encrypt_field,
    generate_2fa_secret,
    generate_backup_codes,
    generate_secure_token,
    get_totp_uri,
    hash_password,
    verify_password,
    verify_token,
    verify_totp,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ─────────────────────────────────────────────
# Shared dependency
# ─────────────────────────────────────────────

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate the Bearer token and return the active User."""
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = verify_token(token)
        if payload.get("type") != "access":
            raise exc
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise exc
    except JWTError:
        raise exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise exc
    return user


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

async def _log_event(
    db: AsyncSession,
    event_type: str,
    request: Request,
    user_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Insert an AuditLog row (best-effort — never raises)."""
    try:
        log = AuditLog(
            user_id=user_id,
            event_type=event_type,
            event_details=details or {},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.add(log)
    except Exception:
        logger.warning("Failed to write audit log for event=%s", event_type)


async def _send_verification_email(email: str, token: str) -> None:
    """Send email verification link via Resend (stub — implement when Resend is configured)."""
    if not settings.resend_api_key:
        logger.warning("Resend not configured — skipping verification email to %s", email)
        return
    try:
        import resend
        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": settings.email_from,
            "to": email,
            "subject": "Verify your Unitrader account",
            "html": (
                f"<p>Click the link below to verify your account:</p>"
                f"<p><a href='{settings.api_host}:{settings.api_port}"
                f"/api/auth/verify-email?token={token}'>Verify Email</a></p>"
            ),
        })
    except Exception as exc:
        logger.error("Failed to send verification email: %s", exc)


async def _send_password_reset_email(email: str, token: str) -> None:
    """Send password reset link via Resend (stub — implement when Resend is configured)."""
    if not settings.resend_api_key:
        logger.warning("Resend not configured — skipping reset email to %s", email)
        return
    try:
        import resend
        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": settings.email_from,
            "to": email,
            "subject": "Reset your Unitrader password",
            "html": (
                f"<p>Use the link below to reset your password (expires in 1 hour):</p>"
                f"<p><a href='{settings.api_host}:{settings.api_port}"
                f"/reset-password?token={token}'>Reset Password</a></p>"
            ),
        })
    except Exception as exc:
        logger.error("Failed to send password reset email: %s", exc)


# ─────────────────────────────────────────────
# POST /api/auth/register
# ─────────────────────────────────────────────

@router.post("/register", response_model=SuccessResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user account.

    - Validates email uniqueness.
    - Hashes password with bcrypt.
    - Creates default UserSettings.
    - Sends a verification email.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    verification_token = generate_secure_token(32)

    now = datetime.now(timezone.utc)
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        ai_name=body.ai_name,
        email_verification_token=verification_token,
        trial_started_at=now,
        trial_end_date=now + timedelta(days=14),
        trial_status="active",
    )
    db.add(user)
    await db.flush()  # get user.id without committing

    # Default settings
    db.add(UserSettings(user_id=user.id))

    await _log_event(db, "register", request, user_id=user.id)
    await _send_verification_email(body.email, verification_token)

    logger.info("New user registered: %s", body.email)
    return SuccessResponse(message="Registration successful. Check your email to verify your account.")


# ─────────────────────────────────────────────
# POST /api/auth/verify-email
# ─────────────────────────────────────────────

@router.post("/verify-email", response_model=SuccessResponse)
async def verify_email(
    body: EmailVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Confirm a user's email address using the token from the verification email."""
    result = await db.execute(
        select(User).where(User.email_verification_token == body.verification_token)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    user.email_verified = True
    user.email_verification_token = None
    await _log_event(db, "email_verified", request, user_id=user.id)

    return SuccessResponse(message="Email verified successfully")


# ─────────────────────────────────────────────
# POST /api/auth/login
# ─────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    body: UserLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and return JWT access + refresh tokens.

    Rate limited to 5 attempts per 15 minutes (enforced at the middleware level).
    If 2FA is enabled, the response contains status='awaiting_2fa' and no tokens.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        await _log_event(
            db, "login_failed", request,
            details={"email": body.email, "reason": "bad credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    if user.two_fa_enabled:
        # Return a challenge — client must hit /api/auth/2fa/verify next
        return JSONResponse(  # type: ignore[return-value]
            status_code=status.HTTP_200_OK,
            content={"status": "awaiting_2fa", "user_id": user.id},
        )

    access_token = create_access_token(user.id)
    refresh_token_str, expires_at = create_refresh_token(user.id)

    db.add(
        RefreshToken(
            token=refresh_token_str,
            user_id=user.id,
            expires_at=expires_at,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    )

    user.last_login = datetime.now(timezone.utc)
    await _log_event(db, "login", request, user_id=user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_str,
        expires_in=settings.access_token_expire_hours * 3600,
    )


# ─────────────────────────────────────────────
# POST /api/auth/logout
# ─────────────────────────────────────────────

@router.post("/logout", response_model=SuccessResponse)
async def logout(
    body: LogoutRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke the provided refresh token, effectively ending the session."""
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == body.refresh_token,
            RefreshToken.user_id == current_user.id,
        )
    )
    token = result.scalar_one_or_none()
    if token:
        token.is_revoked = True

    await _log_event(db, "logout", request, user_id=current_user.id)
    return SuccessResponse(message="Successfully logged out")


# ─────────────────────────────────────────────
# POST /api/auth/refresh-token
# ─────────────────────────────────────────────

@router.post("/refresh-token", response_model=AccessTokenResponse)
async def refresh_token(
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid refresh token for a new access token."""
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )
    try:
        payload = verify_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise exc
        user_id: str = payload["sub"]
    except JWTError:
        raise exc

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == body.refresh_token,
            RefreshToken.is_revoked == False,  # noqa: E712
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    if not result.scalar_one_or_none():
        raise exc

    return AccessTokenResponse(
        access_token=create_access_token(user_id),
        expires_in=settings.access_token_expire_hours * 3600,
    )


# ─────────────────────────────────────────────
# POST /api/auth/2fa/setup
# ─────────────────────────────────────────────

@router.post("/2fa/setup", response_model=TwoFASetupResponse)
async def setup_2fa(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a TOTP secret and QR code URI for the user to scan.

    The user must call /api/auth/2fa/verify with a valid code to activate 2FA.
    """
    secret = generate_2fa_secret()
    current_user.two_fa_secret = encrypt_field(secret)
    backup_codes = generate_backup_codes()

    qr_uri = get_totp_uri(secret, current_user.email, issuer=settings.app_name)
    await _log_event(db, "2fa_setup_initiated", request, user_id=current_user.id)

    return TwoFASetupResponse(
        secret=secret,
        qr_code_url=qr_uri,
        backup_codes=backup_codes,
    )


# ─────────────────────────────────────────────
# POST /api/auth/2fa/verify
# ─────────────────────────────────────────────

@router.post("/2fa/verify", response_model=SuccessResponse)
async def verify_2fa(
    body: TwoFAVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify a TOTP code and enable 2FA on the account."""
    if not current_user.two_fa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA setup not initiated. Call /api/auth/2fa/setup first.",
        )

    secret = decrypt_field(current_user.two_fa_secret)
    if not verify_totp(secret, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid 2FA code",
        )

    current_user.two_fa_enabled = True
    await _log_event(db, "2fa_enabled", request, user_id=current_user.id)

    return SuccessResponse(message="Two-factor authentication enabled")


# ─────────────────────────────────────────────
# POST /api/auth/password-reset-request
# ─────────────────────────────────────────────

@router.post("/password-reset-request", response_model=SuccessResponse)
async def password_reset_request(
    body: PasswordResetRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send a password reset link to the given email address.

    Always returns success to avoid email enumeration attacks.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user:
        token = generate_secure_token(32)
        expire = datetime.now(timezone.utc).replace(
            hour=(datetime.now(timezone.utc).hour + 1) % 24
        )
        user.password_reset_token = token
        user.password_reset_expires = expire
        await _log_event(db, "password_reset_requested", request, user_id=user.id)
        await _send_password_reset_email(body.email, token)

    return SuccessResponse(message="If that email exists, a reset link has been sent")


# ─────────────────────────────────────────────
# POST /api/auth/password-reset
# ─────────────────────────────────────────────

@router.post("/password-reset", response_model=SuccessResponse)
async def password_reset(
    body: PasswordResetBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Apply a new password using the token from the reset email."""
    result = await db.execute(
        select(User).where(
            User.password_reset_token == body.reset_token,
            User.password_reset_expires > datetime.now(timezone.utc),
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user.password_hash = hash_password(body.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    await _log_event(db, "password_reset", request, user_id=user.id)

    return SuccessResponse(message="Password reset successfully")


# ─────────────────────────────────────────────
# GET /api/auth/me
# ─────────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user


# ─────────────────────────────────────────────
# POST /api/auth/clerk-sync
# ─────────────────────────────────────────────

class ClerkSyncRequest(BaseModel):
    clerk_token: str


@router.post("/clerk-sync")
async def clerk_sync(
    body: ClerkSyncRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify a Clerk session token and return our internal JWT.

    Flow:
    1. Verify the Clerk JWT using their JWKS endpoint.
    2. Extract user email and Clerk user ID from claims.
    3. Find or create the user in our database.
    4. If the user has no AI name yet, return status='needs_setup'.
    5. Otherwise, return access_token + refresh_token.
    """
    if not settings.clerk_publishable_key and not settings.clerk_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Clerk authentication is not configured on this server",
        )

    # ── Verify Clerk JWT via JWKS ─────────────────────────────────────
    jwks_url = settings.clerk_jwks_url
    if not jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not derive Clerk JWKS URL from publishable key",
        )

    try:
        import httpx as _httpx
        from jose import jwt as _jwt, JWTError as _JWTError
        from jose.exceptions import ExpiredSignatureError

        async with _httpx.AsyncClient(timeout=10) as client:
            jwks_resp = await client.get(jwks_url)
            jwks_resp.raise_for_status()
            jwks = jwks_resp.json()

        claims = _jwt.decode(
            body.clerk_token,
            jwks,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clerk session has expired — please sign in again",
        )
    except Exception as exc:
        logger.warning("Clerk token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Clerk session token",
        )

    # ── Extract claims ────────────────────────────────────────────────
    clerk_user_id: str = claims.get("sub", "")
    # Clerk puts email in different places depending on sign-in method
    email: str = (
        claims.get("email")
        or claims.get("primary_email_address_id", "")
        or f"{clerk_user_id}@clerk.local"
    )
    # Try to get email from the email_addresses claim (Clerk v2 JWT template)
    if "email" not in claims and "email_addresses" in claims:
        addresses = claims["email_addresses"]
        if addresses:
            email = addresses[0].get("email_address", email)

    if not clerk_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Clerk token is missing user ID (sub claim)",
        )

    # ── Find or create user ───────────────────────────────────────────
    result = await db.execute(
        select(User).where(User.email == email.lower())
    )
    user = result.scalar_one_or_none()

    if not user:
        # New user — create with no AI name yet (they'll set it up next)
        _now = datetime.now(timezone.utc)
        user = User(
            email=email.lower(),
            password_hash="__clerk__",   # placeholder — Clerk manages password
            ai_name="",                  # must be set during onboarding
            email_verified=True,         # Clerk already verified
            is_active=True,
            subscription_tier="free",
            trial_started_at=_now,
            trial_end_date=_now + timedelta(days=14),
            trial_status="active",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("New user created via Clerk: %s", email)

    # ── AI name onboarding gate ────────────────────────────────────────
    if not user.ai_name:
        return {
            "status": "needs_setup",
            "user_id": str(user.id),
            "email": user.email,
            "message": "Please choose a name for your AI to get started.",
        }

    # ── Issue our JWT tokens ───────────────────────────────────────────
    access_token = create_access_token(user.id)
    refresh_token_str, refresh_expires = create_refresh_token(user.id)

    rt = RefreshToken(
        token=refresh_token_str,
        user_id=user.id,
        expires_at=refresh_expires,
    )
    db.add(rt)
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    return {
        "status": "logged_in",
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_hours * 3600,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "ai_name": user.ai_name,
            "subscription_tier": user.subscription_tier,
        },
    }


# ─────────────────────────────────────────────
# POST /api/auth/clerk-setup  (set AI name after Clerk sign-up)
# ─────────────────────────────────────────────

class ClerkSetupRequest(BaseModel):
    user_id: str
    ai_name: str


@router.post("/clerk-setup")
async def clerk_setup(
    body: ClerkSetupRequest,
    db: AsyncSession = Depends(get_db),
):
    """Set the AI name for a newly Clerk-authenticated user.

    Called after clerk-sync returns status='needs_setup'.
    Returns JWT tokens on success.
    """
    from security import validate_ai_name

    if not validate_ai_name(body.ai_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI name must be 2–20 characters, letters/numbers/underscores only",
        )

    result = await db.execute(select(User).where(User.id == body.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check AI name not taken
    taken = await db.execute(select(User).where(User.ai_name == body.ai_name))
    if taken.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That AI name is already taken — try another",
        )

    user.ai_name = body.ai_name
    user.email_verified = True

    # Create default settings
    existing_settings = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    if not existing_settings.scalar_one_or_none():
        db.add(UserSettings(user_id=user.id))

    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(user.id)
    refresh_token_str, refresh_expires = create_refresh_token(user.id)

    rt = RefreshToken(
        token=refresh_token_str,
        user_id=user.id,
        expires_at=refresh_expires,
    )
    db.add(rt)
    await db.commit()

    logger.info("AI name set for user %s: %s", user.id, body.ai_name)

    return {
        "status": "logged_in",
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_hours * 3600,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "ai_name": user.ai_name,
            "subscription_tier": user.subscription_tier,
        },
    }


# ─────────────────────────────────────────────
# POST /api/auth/telegram/linking-code
# ─────────────────────────────────────────────

@router.post("/telegram/linking-code")
async def generate_telegram_linking_code(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a 6-digit OTP the user can send to the Telegram bot as /link CODE.

    Old unused codes for this user are expired immediately to avoid confusion.
    The new code expires in 15 minutes and is single-use.
    """
    now = datetime.now(timezone.utc)

    # Invalidate any previous unused codes for this user
    old_codes = await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.user_id == current_user.id,
            TelegramLinkingCode.is_used == False,  # noqa: E712
        )
    )
    for row in old_codes.scalars().all():
        await db.delete(row)

    # Generate a 6-digit numeric code (100000–999999)
    code = str(secrets.randbelow(900_000) + 100_000)
    expires_at = now + timedelta(minutes=15)

    db.add(TelegramLinkingCode(
        code=code,
        user_id=current_user.id,
        expires_at=expires_at,
    ))
    await _log_event(db, "telegram_link_code_generated", request, user_id=current_user.id)

    return {
        "status": "success",
        "code": code,
        "expires_in_minutes": 15,
        "instruction": f"Send to {settings.telegram_bot_handle}: /link {code}",
    }


# ─────────────────────────────────────────────
# POST /api/auth/telegram/link-account
# ─────────────────────────────────────────────

class LinkTelegramAccountRequest(BaseModel):
    code: str
    telegram_user_id: str
    telegram_username: str | None = None


@router.post("/telegram/link-account")
async def link_telegram_account(
    body: LinkTelegramAccountRequest,
    db: AsyncSession = Depends(get_db),
):
    """Complete a web-initiated Telegram link.

    Called by the Telegram bot when a user sends /link CODE.
    The code itself authenticates the request — no JWT required.
    """
    now = datetime.now(timezone.utc)

    # Validate the code
    row = (await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.code == body.code,
            TelegramLinkingCode.is_used == False,  # noqa: E712
            TelegramLinkingCode.expires_at > now,
        )
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired linking code",
        )

    # Guard: this Telegram account may already be linked to a *different* user
    existing = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.external_id == body.telegram_user_id,
            UserExternalAccount.platform == "telegram",
        )
    )).scalar_one_or_none()

    if existing and existing.user_id != row.user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Telegram account is already linked to a different Unitrader account",
        )

    if existing:
        # Re-link (was previously unlinked)
        existing.is_linked = True
        existing.linked_at = now
        existing.external_username = body.telegram_username or existing.external_username
    else:
        db.add(UserExternalAccount(
            user_id=row.user_id,
            platform="telegram",
            external_id=body.telegram_user_id,
            external_username=body.telegram_username,
            is_linked=True,
            settings={"notifications": True, "trade_alerts": True},
        ))

    # Mark code as consumed
    row.is_used = True
    row.used_at = now

    await db.commit()

    return {
        "status": "success",
        "message": "Telegram account linked successfully",
    }


# ─────────────────────────────────────────────
# GET /api/auth/external-accounts
# ─────────────────────────────────────────────

@router.get("/external-accounts")
async def get_external_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all external platform accounts linked to the current user."""
    accounts = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.user_id == current_user.id,
            UserExternalAccount.is_linked == True,  # noqa: E712
        )
    )).scalars().all()

    return {
        "accounts": [
            {
                "platform": acc.platform,
                "username": acc.external_username,
                "linked_at": acc.linked_at.isoformat() if acc.linked_at else None,
                "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else None,
            }
            for acc in accounts
        ]
    }


# ─────────────────────────────────────────────
# POST /api/auth/unlink-external-account
# ─────────────────────────────────────────────

class UnlinkExternalAccountRequest(BaseModel):
    platform: str


@router.post("/unlink-external-account")
async def unlink_external_account(
    body: UnlinkExternalAccountRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently remove a linked external account (Telegram, Discord, etc.)."""
    account = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.user_id == current_user.id,
            UserExternalAccount.platform == body.platform,
        )
    )).scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No linked {body.platform} account found",
        )

    await db.delete(account)
    await _log_event(
        db, "external_account_unlinked", request,
        user_id=current_user.id,
        details={"platform": body.platform},
    )

    return {"status": "success", "message": f"{body.platform.capitalize()} account unlinked"}


# ─────────────────────────────────────────────
# POST /api/auth/whatsapp/linking-code
# ─────────────────────────────────────────────

@router.post("/whatsapp/linking-code")
async def generate_whatsapp_linking_code(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a 6-digit OTP the user can text to the Unitrader WhatsApp number.

    The bot recognises: LINK 123456
    Codes expire in 15 minutes and are single-use.
    Old unused codes for this user are cleaned up immediately.
    """
    now = datetime.now(timezone.utc)

    old_codes = await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.user_id == current_user.id,
            TelegramLinkingCode.is_used == False,  # noqa: E712
        )
    )
    for row in old_codes.scalars().all():
        await db.delete(row)

    code       = str(secrets.randbelow(900_000) + 100_000)
    expires_at = now + timedelta(minutes=15)

    db.add(TelegramLinkingCode(
        code=code,
        user_id=current_user.id,
        expires_at=expires_at,
    ))
    await _log_event(db, "whatsapp_link_code_generated", request, user_id=current_user.id)

    return {
        "status": "success",
        "code": code,
        "expires_in_minutes": 15,
        "instruction": f"Send to the Unitrader WhatsApp number: LINK {code}",
    }


# ─────────────────────────────────────────────
# POST /api/auth/whatsapp/link-account
# ─────────────────────────────────────────────

class LinkWhatsAppAccountRequest(BaseModel):
    code: str
    whatsapp_number: str


@router.post("/whatsapp/link-account")
async def link_whatsapp_account(
    body: LinkWhatsAppAccountRequest,
    db: AsyncSession = Depends(get_db),
):
    """Complete a web-initiated WhatsApp link.

    Called by the WhatsApp bot when a user sends LINK CODE.
    The code itself authenticates the request — no JWT needed.
    """
    now = datetime.now(timezone.utc)

    row = (await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.code     == body.code,
            TelegramLinkingCode.is_used  == False,  # noqa: E712
            TelegramLinkingCode.expires_at > now,
        )
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired linking code",
        )

    existing = (await db.execute(
        select(UserExternalAccount).where(
            UserExternalAccount.external_id == body.whatsapp_number,
            UserExternalAccount.platform    == "whatsapp",
        )
    )).scalar_one_or_none()

    if existing and existing.user_id != row.user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This WhatsApp number is already linked to a different Unitrader account",
        )

    if existing:
        existing.is_linked         = True
        existing.linked_at         = now
        existing.external_username = body.whatsapp_number
    else:
        db.add(UserExternalAccount(
            user_id=row.user_id,
            platform="whatsapp",
            external_id=body.whatsapp_number,
            external_username=body.whatsapp_number,
            is_linked=True,
            settings={"notifications": True, "trade_alerts": True},
        ))

    row.is_used = True
    row.used_at = now
    await db.commit()

    return {
        "status": "success",
        "message": "WhatsApp account linked successfully",
    }


# Resolve forward reference used in login endpoint
from fastapi.responses import JSONResponse  # noqa: E402 (intentional late import)
