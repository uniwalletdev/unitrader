"""
routers/auth.py — Authentication endpoints for Unitrader.

Endpoints:
    POST   /api/auth/register              — Create account
    POST   /api/auth/verify-email          — Confirm email address
    POST   /api/auth/login                 — Get JWT tokens
    POST   /api/auth/logout                — Revoke refresh token
    POST   /api/auth/refresh-token         — Issue new access token
    POST   /api/auth/2fa/setup             — Generate TOTP secret + QR code
    POST   /api/auth/2fa/verify            — Activate 2FA
    POST   /api/auth/password-reset-request — Send reset email
    POST   /api/auth/password-reset        — Apply new password
    GET    /api/auth/me                    — Current user profile
    DELETE /api/auth/account               — Permanently delete account
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
    UpdateUserSettingsRequest,
    UserRegisterRequest,
    UserResponse,
    UserLoginRequest,
    UserSettingsResponse,
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
    except JWTError as e:
        error_str = str(e).lower()
        if "expired" in error_str or "expir" in error_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "TOKEN_EXPIRED",
                    "message": "Token has expired — please refresh",
                },
                headers={"WWW-Authenticate": "Bearer"},
            ) from e
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_INVALID",
                "message": "Invalid authentication token",
            },
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

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

    # Delete any existing refresh tokens for this user to avoid unique constraint violations
    existing_tokens = (await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )).scalars().all()
    for token in existing_tokens:
        await db.delete(token)

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
        expire = datetime.now(timezone.utc) + timedelta(hours=1)
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
# GET /api/auth/settings
# ─────────────────────────────────────────────

@router.get("/settings", response_model=UserSettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the user's settings.
    
    If no settings row exists, creates one with defaults and returns it.
    Includes computed min_trade_amount and trade_limits based on trader_class.
    """
    from src.agents.core.trading_agent import CLASS_TRADE_LIMITS
    from src.agents.shared_memory import SharedMemory

    try:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        user_settings = result.scalar_one_or_none()

        if not user_settings:
            # Create defaults
            user_settings = UserSettings(user_id=current_user.id)
            db.add(user_settings)
            await db.commit()
            await db.refresh(user_settings)

        # Compute class-based trade limits
        trader_class = user_settings.trader_class or "complete_novice"
        class_limits = CLASS_TRADE_LIMITS.get(trader_class, CLASS_TRADE_LIMITS["complete_novice"])

        # Build response dict with computed fields merged in
        response = UserSettingsResponse.model_validate(user_settings)
        response.min_trade_amount = class_limits["min"]
        response.trade_limits = CLASS_TRADE_LIMITS.get(trader_class, {})

        return response

    except Exception as exc:
        logger.error(f"Failed to get settings for user {current_user.id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve settings",
        )


# ─────────────────────────────────────────────
# PATCH /api/auth/settings
# ─────────────────────────────────────────────

@router.patch("/settings", response_model=UserSettingsResponse)
async def update_settings(
    body: UpdateUserSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user settings.
    
    Only the provided fields will be updated. Allowed fields:
    - explanation_level (string)
    - trade_mode (string)
    - max_trade_amount (float, USD)
    - max_daily_loss (float, percentage)
    - trading_paused (boolean)
    - leaderboard_opt_out (boolean)
    - approved_assets (list of symbols, maps to favourite_symbols)
    - first_trade_done (boolean)
    - push_token (string, for mobile push notifications)
    """
    try:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        settings = result.scalar_one_or_none()

        if not settings:
            # Create defaults if doesn't exist
            settings = UserSettings(user_id=current_user.id)
            db.add(settings)

        # Update only provided fields
        update_data = body.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(settings, field):
                setattr(settings, field, value)

        await db.commit()
        await db.refresh(settings)

        logger.info(f"Updated settings for user {current_user.id}: {list(update_data.keys())}")

        return settings

    except Exception as exc:
        await db.rollback()
        logger.error(f"Failed to update settings for user {current_user.id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update settings",
        )


# ─────────────────────────────────────────────
# Clerk helpers
# ─────────────────────────────────────────────

# In-memory JWKS cache — avoids a Clerk network round-trip on every login.
_jwks_cache: dict = {}  # keys: "data" (jwks dict), "ts" (monotonic float)


async def _get_cached_jwks(jwks_url: str) -> dict:
    """Return cached JWKS, refreshing from Clerk when older than 1 hour."""
    import time
    import httpx as _httpx

    if _jwks_cache.get("data") and (time.monotonic() - _jwks_cache.get("ts", 0.0)) < 3600:
        return _jwks_cache["data"]  # type: ignore[return-value]

    async with _httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        data = resp.json()

    _jwks_cache["data"] = data
    _jwks_cache["ts"] = time.monotonic()
    return data


async def _fetch_clerk_email(clerk_user_id: str) -> str | None:
    """Fetch the user's primary email from Clerk's Backend API.

    Requires CLERK_SECRET_KEY to be set.  Returns None on any failure so
    callers can fall back gracefully.
    """
    if not settings.clerk_secret_key:
        return None
    try:
        import httpx as _httpx

        async with _httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            )
            if resp.status_code != 200:
                logger.warning(
                    "Clerk API returned %d while fetching user %s",
                    resp.status_code, clerk_user_id,
                )
                return None
            data = resp.json()
            primary_id = data.get("primary_email_address_id")
            for addr in data.get("email_addresses", []):
                if addr.get("id") == primary_id:
                    return addr.get("email_address")
            # fallback: first available address
            addrs = data.get("email_addresses", [])
            return addrs[0].get("email_address") if addrs else None
    except Exception as exc:
        logger.warning("Could not fetch Clerk user email via API: %s", exc)
        return None


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
    1. Verify the Clerk JWT using JWKS (cached in memory for 1 hour).
    2. Extract email: JWT claim → Clerk Backend API → stable synthetic fallback.
    3. Find or create the user in our database.
    4. If the user has no AI name yet, return status='needs_setup'.
    5. Otherwise, return access_token + refresh_token.
    """
    if not settings.clerk_publishable_key and not settings.clerk_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Clerk authentication is not configured on this server",
        )

    # ── Verify Clerk JWT via JWKS (cached) ───────────────────────────
    jwks_url = settings.clerk_jwks_url
    if not jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not derive Clerk JWKS URL from publishable key",
        )

    try:
        from jose import jwt as _jwt
        from jose.exceptions import ExpiredSignatureError

        jwks = await _get_cached_jwks(jwks_url)
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
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Clerk token verification failed: %s", exc)
        # Bust the JWKS cache so the next request fetches fresh keys
        _jwks_cache.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Clerk session token",
        )

    # ── Extract claims ────────────────────────────────────────────────
    clerk_user_id: str = claims.get("sub", "")
    if not clerk_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Clerk token is missing user ID (sub claim)",
        )

    # Clerk's default session JWT does NOT include email.
    # `primary_email_address_id` is an object ID (e.g. "idn_abc123"), not an
    # email address — we must NOT use it as one.
    email: str = claims.get("email", "")

    # Some Clerk JWT templates include email_addresses array
    if not email and "email_addresses" in claims:
        addresses = claims["email_addresses"]
        if addresses:
            email = addresses[0].get("email_address", "")

    # If still no real email (no "@"), call Clerk Backend API
    if not email or "@" not in email:
        fetched = await _fetch_clerk_email(clerk_user_id)
        if fetched:
            email = fetched
        else:
            # Stable synthetic address keyed to the immutable Clerk user ID
            email = f"{clerk_user_id}@clerk.unitrader.internal"

    logger.debug("clerk-sync: clerk_id=%s resolved_email=%s", clerk_user_id, email)

    # ── Find or create user ───────────────────────────────────────────
    try:
        # Primary lookup: by Clerk user ID (immutable, survives email changes)
        result = await db.execute(
            select(User).where(User.clerk_user_id == clerk_user_id)
        )
        user = result.scalar_one_or_none()

        # Fallback: by email (for users created before clerk_user_id tracking)
        if not user:
            result = await db.execute(
                select(User).where(User.email == email.lower())
            )
            user = result.scalar_one_or_none()
            # Backfill clerk_user_id on existing user
            if user and not user.clerk_user_id:
                user.clerk_user_id = clerk_user_id
                await db.commit()

        if not user:
            _now = datetime.now(timezone.utc)
            user = User(
                email=email.lower(),
                password_hash="__clerk__",   # placeholder — Clerk manages auth
                ai_name="",                  # set during onboarding
                email_verified=True,
                is_active=True,
                subscription_tier="free",
                trial_started_at=_now,
                trial_end_date=_now + timedelta(days=14),
                trial_status="active",
                clerk_user_id=clerk_user_id,
            )
            db.add(user)
            await db.flush()          # obtain user.id before committing
            db.add(UserSettings(user_id=user.id))  # default settings immediately
            await db.commit()
            await db.refresh(user)
            logger.info("New user created via Clerk: %s", email)

    except Exception as exc:
        logger.error("clerk-sync DB error during user lookup/create: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account sync is temporarily unavailable — please try again in a moment",
        )

    # ── AI name onboarding gate ────────────────────────────────────────
    if not user.ai_name:
        return {
            "status": "needs_setup",
            "user_id": str(user.id),
            "email": user.email,
            "message": "Please choose a name for your AI to get started.",
        }

    # ── Issue our JWT tokens ───────────────────────────────────────────
    try:
        access_token = create_access_token(user.id)
        refresh_token_str, refresh_expires = create_refresh_token(user.id)

        existing_tokens = (await db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        )).scalars().all()
        for token in existing_tokens:
            await db.delete(token)

        rt = RefreshToken(
            token=refresh_token_str,
            user_id=user.id,
            expires_at=refresh_expires,
        )
        db.add(rt)
        user.last_login = datetime.now(timezone.utc)
        await db.commit()

    except Exception as exc:
        logger.error("clerk-sync DB error during token issuance: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account sync is temporarily unavailable — please try again in a moment",
        )

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

    # Delete any existing refresh tokens for this user to avoid unique constraint violations
    existing_tokens = (await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )).scalars().all()
    for token in existing_tokens:
        await db.delete(token)

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

    Old expired codes are cleaned up but active WhatsApp codes are preserved.
    The new code expires in 15 minutes and is single-use.
    """
    now = datetime.now(timezone.utc)

    # Clean up only expired codes (preserve any active WhatsApp linking codes)
    expired_codes = await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.user_id == current_user.id,
            TelegramLinkingCode.is_used == False,  # noqa: E712
            TelegramLinkingCode.expires_at <= now,
        )
    )
    for row in expired_codes.scalars().all():
        await db.delete(row)

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
        "data": {"code": code},
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

    if not row.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Linking code has no associated user — please generate a new code from the dashboard",
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
# POST /api/auth/telegram/webhook
# ─────────────────────────────────────────────

@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Telegram Bot incoming message webhook.
    Telegram sends JSON POST.

    Handles:
    - /start          → welcome message
    - /link {code}    → links Telegram account to Unitrader user
    - /status         → shows current trading status
    - /positions      → shows open positions
    - /pause          → pauses AI trading
    - /resume         → resumes AI trading
    - Any other msg   → passes to conversation agent for AI response
    """

    # ── Parse Telegram JSON payload ────────────────────────────────
    try:
        data = await request.json()
    except Exception:
        return {"status": "ok"}  # always return 200 to Telegram

    # Extract message details
    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"status": "ok"}  # ignore non-message updates (polls etc)

    chat_id      = str(message.get("chat", {}).get("id", ""))
    telegram_uid = str(message.get("from", {}).get("id", ""))
    username     = message.get("from", {}).get("username")
    text         = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"status": "ok"}

    # ── Command router ─────────────────────────────────────────────

    # /start
    if text.lower() == "/start":
        reply = (
            "👋 Welcome to Unitrader!\n\n"
            "I'm your AI trading assistant. To get started:\n\n"
            "1️⃣ Log into unitraderai.vercel.app\n"
            "2️⃣ Go to Settings → Connect Telegram\n"
            "3️⃣ Send me: /link YOUR_CODE\n\n"
            "Once linked I'll send you trade alerts and you "
            "can chat with your AI trader here anytime."
        )

    # /link CODE
    elif text.lower().startswith("/link "):
        code = text.split(" ", 1)[1].strip()
        try:
            link_body = LinkTelegramAccountRequest(
                code=code,
                telegram_user_id=telegram_uid,
                telegram_username=username,
            )
            await link_telegram_account(link_body, db)
            reply = (
                "✅ Your Telegram is now linked to Unitrader!\n\n"
                "You'll receive trade alerts here and can chat "
                "with your AI trader anytime.\n\n"
                "Try asking: 'What is Bitcoin doing today?'"
            )
        except HTTPException as e:
            if e.status_code == 400:
                reply = (
                    "❌ Invalid or expired code.\n\n"
                    "Please generate a new code from your "
                    "Unitrader dashboard and try again."
                )
            elif e.status_code == 409:
                reply = (
                    "⚠️ This Telegram account is already linked "
                    "to another Unitrader account."
                )
            else:
                reply = "Something went wrong. Please try again."

    # /status — show trading status
    elif text.lower() == "/status":
        account = (await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.external_id == telegram_uid,
                UserExternalAccount.platform    == "telegram",
                UserExternalAccount.is_linked   == True,  # noqa: E712
            )
        )).scalar_one_or_none()

        if not account:
            reply = "⚠️ Please link your account first. Send /link YOUR_CODE"
        else:
            user = (await db.execute(
                select(User).where(User.id == account.user_id)
            )).scalar_one_or_none()

            if user:
                reply = (
                    f"🤖 {user.ai_name} Status\n\n"
                    f"Account: {user.email}\n"
                    f"Subscription: {user.subscription_tier}\n"
                    f"Trial: {user.trial_status}\n\n"
                    "Send /positions to see open trades."
                )
            else:
                reply = "⚠️ Could not find your account. Please contact support."

    # /positions — show open positions
    elif text.lower() == "/positions":
        account = (await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.external_id == telegram_uid,
                UserExternalAccount.platform    == "telegram",
                UserExternalAccount.is_linked   == True,  # noqa: E712
            )
        )).scalar_one_or_none()

        if not account:
            reply = "⚠️ Please link your account first. Send /link YOUR_CODE"
        else:
            from models import Trade
            trades = (await db.execute(
                select(Trade).where(
                    Trade.user_id == account.user_id,
                    Trade.status  == "open",
                )
            )).scalars().all()

            if not trades:
                reply = "📊 No open positions right now."
            else:
                lines = ["📊 *Open Positions*\n"]
                for t in trades:
                    pnl_sign = "+" if (t.pnl or 0) >= 0 else ""
                    lines.append(
                        f"• {t.symbol} {t.side} "
                        f"@ ${t.entry_price:.2f} "
                        f"P&L: {pnl_sign}${t.pnl or 0:.2f}"
                    )
                reply = "\n".join(lines)

    # /pause — pause AI trading
    elif text.lower() == "/pause":
        account = (await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.external_id == telegram_uid,
                UserExternalAccount.platform    == "telegram",
                UserExternalAccount.is_linked   == True,  # noqa: E712
            )
        )).scalar_one_or_none()

        if not account:
            reply = "⚠️ Please link your account first. Send /link YOUR_CODE"
        else:
            from models import UserSettings
            user_settings = (await db.execute(
                select(UserSettings).where(
                    UserSettings.user_id == account.user_id
                )
            )).scalar_one_or_none()

            if user_settings:
                user_settings.trading_enabled = False
                await db.commit()
                reply = (
                    "⏸ Trading paused.\n\n"
                    "Your AI trader will not open new positions "
                    "until you send /resume."
                )
            else:
                reply = "⚠️ Could not find your settings. Please contact support."

    # /resume — resume AI trading
    elif text.lower() == "/resume":
        account = (await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.external_id == telegram_uid,
                UserExternalAccount.platform    == "telegram",
                UserExternalAccount.is_linked   == True,  # noqa: E712
            )
        )).scalar_one_or_none()

        if not account:
            reply = "⚠️ Please link your account first. Send /link YOUR_CODE"
        else:
            from models import UserSettings
            user_settings = (await db.execute(
                select(UserSettings).where(
                    UserSettings.user_id == account.user_id
                )
            )).scalar_one_or_none()

            if user_settings:
                user_settings.trading_enabled = True
                await db.commit()
                reply = (
                    "▶️ Trading resumed!\n\n"
                    "Your AI trader is now active and watching "
                    "the markets again."
                )
            else:
                reply = "⚠️ Could not find your settings. Please contact support."

    # Any other message — pass to conversation agent
    else:
        account = (await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.external_id == telegram_uid,
                UserExternalAccount.platform    == "telegram",
                UserExternalAccount.is_linked   == True,  # noqa: E712
            )
        )).scalar_one_or_none()

        if not account:
            reply = (
                "👋 I don't recognise you yet!\n\n"
                "Log into unitraderai.vercel.app, go to "
                "Settings → Connect Telegram, then send "
                "me /link YOUR_CODE to get started."
            )
        else:
            try:
                from src.agents.core.conversation_agent import ConversationAgent
                agent  = ConversationAgent()
                result = await agent.chat(
                    user_id=str(account.user_id),
                    message=text,
                    db=db,
                )
                reply = result.get(
                    "response",
                    "I'm thinking... try again in a moment."
                )
            except Exception as e:
                logger.error(f"Telegram conversation agent error: {e}")
                reply = (
                    "⚠️ Your AI trader is busy right now. "
                    "Try again in a moment."
                )

    # ── Send reply via Telegram Bot API ───────────────────────────
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": reply,
                    "parse_mode": "Markdown",
                },
            )
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

    # Always return 200 — if Telegram gets non-200 it retries repeatedly
    return {"status": "ok"}
    

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
    Old expired codes are cleaned up but active Telegram codes are preserved.
    """
    now = datetime.now(timezone.utc)

    # Only expire codes that have already timed out (don't invalidate
    # active Telegram linking codes that share the same table).
    expired_codes = await db.execute(
        select(TelegramLinkingCode).where(
            TelegramLinkingCode.user_id == current_user.id,
            TelegramLinkingCode.is_used == False,  # noqa: E712
            TelegramLinkingCode.expires_at <= now,
        )
    )
    for row in expired_codes.scalars().all():
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
        "data": {"code": code},
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

    if not row.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Linking code has no associated user — please generate a new code from the dashboard",
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

# ─────────────────────────────────────────────
# POST /api/auth/whatsapp/webhook
# ─────────────────────────────────────────────

from twilio.request_validator import RequestValidator
from fastapi import Form

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    Body: str = Form(default=""),
    From: str = Form(default=""),
    To: str = Form(default=""),
    ProfileName: str = Form(default=""),
    MessageSid: str = Form(default=""),
    WaId: str = Form(default=""),
):
    """
    Twilio WhatsApp incoming message webhook.
    Twilio sends form-encoded POST — NOT JSON.
    
    Handles:
    - LINK {code}     → links WhatsApp account to Unitrader user
    - Any other msg   → passes to conversation agent for AI response
    """

    # ── Optional: validate the request actually came from Twilio ──
    # Uncomment when TWILIO_AUTH_TOKEN is in env vars
    # validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    # url = str(request.url)
    # form_data = dict(await request.form())
    # signature = request.headers.get("X-Twilio-Signature", "")
    # if not validator.validate(url, form_data, signature):
    #     raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    whatsapp_number = From.replace("whatsapp:", "").strip()
    message_text    = Body.strip()

    # ── LINK flow ──────────────────────────────────────────────────
    if message_text.upper().startswith("LINK "):
        code = message_text.split(" ", 1)[1].strip()

        try:
            link_request = LinkWhatsAppAccountRequest(
                code=code,
                whatsapp_number=whatsapp_number,
            )
            await link_whatsapp_account(link_request, db)

            reply = (
                "✅ Your WhatsApp is now linked to Unitrader!\n\n"
                "You'll receive trade alerts and can chat with "
                "your AI trader here anytime."
            )

        except HTTPException as e:
            if e.status_code == 400:
                reply = (
                    "❌ Invalid or expired code.\n\n"
                    "Please generate a new code from your "
                    "Unitrader dashboard and try again."
                )
            elif e.status_code == 409:
                reply = (
                    "⚠️ This WhatsApp number is already linked "
                    "to another Unitrader account."
                )
            else:
                reply = "Something went wrong. Please try again."

    # ── AI conversation flow ───────────────────────────────────────
    else:
        # Find the linked user for this WhatsApp number
        account = (await db.execute(
            select(UserExternalAccount).where(
                UserExternalAccount.external_id == whatsapp_number,
                UserExternalAccount.platform    == "whatsapp",
                UserExternalAccount.is_linked   == True,  # noqa: E712
            )
        )).scalar_one_or_none()

        if not account:
            reply = (
                "👋 Welcome to Unitrader!\n\n"
                "To get started, log into unitraderai.vercel.app, "
                "go to Settings → Connect WhatsApp, and send the "
                "LINK code you receive here."
            )
        else:
            # User is linked — pass message to conversation agent
            try:
                from src.agents.orchestrator import get_orchestrator

                user_id = str(account.user_id)
                incoming_message_text = message_text
                preferred_trading_account_id = None

                orchestrator = get_orchestrator()
                orch_result = await orchestrator.route(
                    user_id=user_id,
                    action="chat",
                    payload={
                        "message": incoming_message_text,
                        "channel": "whatsapp",
                        "trading_account_id": str(preferred_trading_account_id)
                        if preferred_trading_account_id
                        else None,
                    },
                    db=db,
                )
                reply = orch_result.get("response") or orch_result.get("message", "")
            except Exception as e:
                logger.error(f"WhatsApp conversation agent error: {e}")
                reply = (
                    "⚠️ Your AI trader is busy right now. "
                    "Try again in a moment."
                )

    # ── Send reply via Twilio ──────────────────────────────────────
    try:
        from twilio.rest import Client as TwilioClient
        twilio = TwilioClient(
            settings.TWILIO_ACCOUNT_SID,
            settings.TWILIO_AUTH_TOKEN,
        )
        twilio.messages.create(
            from_=f"whatsapp:{settings.TWILIO_WHATSAPP_NUMBER}",
            to=f"whatsapp:{whatsapp_number}",
            body=reply,
        )
    except Exception as e:
        logger.error(f"Twilio send error: {e}")

    # Always return 200 to Twilio — if you return non-200,
    # Twilio retries repeatedly
    return {"status": "ok"}


# ─────────────────────────────────────────────
# DELETE /api/auth/account
# ─────────────────────────────────────────────

@router.delete("/account", response_model=SuccessResponse)
async def delete_account(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete the authenticated user and all associated data."""
    user_id = current_user.id
    user_email = current_user.email

    await _log_event(
        db, "account_deleted", request,
        user_id=user_id,
        details={"email": user_email},
    )

    await db.delete(current_user)
    await db.commit()

    logger.info("Account permanently deleted: user_id=%s email=%s", user_id, user_email)
    return SuccessResponse(message="Account permanently deleted")


# ─────────────────────────────────────────────
# DELETE /api/auth/admin/user
# ─────────────────────────────────────────────

class AdminDeleteUserRequest(BaseModel):
    email: str
    admin_secret: str


@router.delete("/admin/user", response_model=SuccessResponse)
async def admin_delete_user(
    body: AdminDeleteUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Admin-only: permanently delete any user by email.

    Requires the ADMIN_SECRET_KEY env var to be set and matched.
    """
    if not settings.admin_secret_key or body.admin_secret != settings.admin_secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin secret",
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user found with email: {body.email}",
        )

    user_id = user.id
    await _log_event(
        db, "admin_account_deleted", request,
        user_id=user_id,
        details={"email": body.email},
    )

    await db.delete(user)
    await db.commit()

    logger.info("Admin deleted account: user_id=%s email=%s", user_id, body.email)
    return SuccessResponse(message=f"User {body.email} permanently deleted")


# ─────────────────────────────────────────────
# POST /api/auth/generate-claim-token
# ─────────────────────────────────────────────

class ClaimTokenResponse(BaseModel):
    claim_url: str
    expires_in_minutes: int = 60


@router.post("/generate-claim-token", response_model=ClaimTokenResponse)
async def generate_claim_token(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a one-time claim URL for upgrading a provisional (chat-created) account.

    Only callable by provisional users (email ending in @provisional.unitrader.app).
    Returns a URL the user can tap to set up a full web account.
    """
    from src.services.provisional_user import is_provisional

    if not is_provisional(current_user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already a full account",
        )

    token = generate_secure_token(48)
    current_user.email_verification_token = token
    current_user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.commit()

    claim_url = f"{settings.frontend_url}/claim/{token}"
    return ClaimTokenResponse(claim_url=claim_url)


# ─────────────────────────────────────────────
# POST /api/auth/claim
# ─────────────────────────────────────────────

class ClaimAccountRequest(BaseModel):
    claim_token: str
    clerk_token: str


@router.post("/claim")
async def claim_provisional_account(
    body: ClaimAccountRequest,
    db: AsyncSession = Depends(get_db),
):
    """Merge a provisional (chat-created) account with a Clerk web identity.

    The provisional user keeps all their data (trades, conversations, settings,
    external accounts). Their email gets upgraded to the Clerk identity.
    """
    from src.services.provisional_user import PROVISIONAL_DOMAIN

    prov = (await db.execute(
        select(User).where(
            User.email_verification_token == body.claim_token,
            User.email.endswith(f"@{PROVISIONAL_DOMAIN}"),
        )
    )).scalar_one_or_none()

    if not prov:
        raise HTTPException(status_code=400, detail="Invalid or expired claim token")

    if prov.password_reset_expires and prov.password_reset_expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Claim token has expired")

    # Decode Clerk JWT to extract email (unverified decode — Clerk handles auth)
    import jwt as _jwt

    try:
        claims = _jwt.decode(body.clerk_token, options={"verify_signature": False})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Clerk token")

    email: str = claims.get("email", "")
    if not email and "email_addresses" in claims:
        addresses = claims["email_addresses"]
        if addresses and isinstance(addresses, list):
            email = addresses[0].get("email_address", "")
    if not email:
        raise HTTPException(status_code=400, detail="Could not extract email from Clerk token")

    # Check if a full account with this email already exists
    from sqlalchemy import update as sa_update
    from models import Conversation, Trade

    existing = (await db.execute(
        select(User).where(User.email == email, User.id != prov.id)
    )).scalar_one_or_none()

    if existing:
        # Merge: move all provisional user's data to the existing account
        for model_cls in (Trade, Conversation, UserExternalAccount, ExchangeAPIKey):
            await db.execute(
                sa_update(model_cls)
                .where(model_cls.user_id == prov.id)
                .values(user_id=existing.id)
            )
        # Copy AI name if the existing account hasn't set one
        if not existing.ai_name or existing.ai_name in ("Claude", "Apex"):
            existing.ai_name = prov.ai_name
        # Delete provisional user + their settings (CASCADE)
        await db.delete(prov)
        target_user = existing
    else:
        # Upgrade the provisional user in-place
        prov.email = email
        prov.email_verified = True
        prov.email_verification_token = None
        prov.password_reset_expires = None
        target_user = prov

    await db.commit()

    access_token = create_access_token(target_user.id)
    refresh_token_str, refresh_expires = create_refresh_token(target_user.id)

    rt = RefreshToken(
        token=refresh_token_str,
        user_id=target_user.id,
        expires_at=refresh_expires,
    )
    db.add(rt)
    await db.commit()

    logger.info("Provisional account claimed: user_id=%s email=%s", target_user.id, email)

    return {
        "status": "claimed",
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "user": {
            "id": str(target_user.id),
            "email": target_user.email,
            "ai_name": target_user.ai_name,
        },
    }