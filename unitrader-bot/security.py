"""
security.py — Authentication, encryption, and validation utilities.

All sensitive operations (password hashing, JWT, Fernet encryption) live here
so the rest of the codebase never handles raw secrets directly.
"""

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

from config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─────────────────────────────────────────────
# Password Hashing
# ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return a bcrypt hash of the given plain-text password."""
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Return True if plain-text password matches the bcrypt hash."""
    return pwd_context.verify(password, hashed)


# ─────────────────────────────────────────────
# API Key Encryption (Fernet)
# ─────────────────────────────────────────────

def _get_fernet(key: str) -> Fernet:
    """Instantiate a Fernet cipher from a base64-encoded key string."""
    if not key:
        raise ValueError("Encryption key is not configured in .env")
    return Fernet(key.encode())


def encrypt_api_key(api_key: str, api_secret: str) -> tuple[str, str]:
    """Encrypt broker api_key and api_secret separately.

    Returns:
        (encrypted_api_key, encrypted_api_secret) — both base64 strings.
    """
    f = _get_fernet(settings.field_encryption_key)
    return (
        f.encrypt(api_key.encode()).decode(),
        f.encrypt(api_secret.encode()).decode(),
    )


def decrypt_api_key(encrypted_key: str, encrypted_secret: str) -> tuple[str, str]:
    """Decrypt previously encrypted broker credentials.

    Returns:
        (api_key, api_secret) as plain strings.

    Raises:
        InvalidToken: if the ciphertext has been tampered with.
    """
    f = _get_fernet(settings.field_encryption_key)
    try:
        return (
            f.decrypt(encrypted_key.encode()).decode(),
            f.decrypt(encrypted_secret.encode()).decode(),
        )
    except InvalidToken as exc:
        logger.error("Failed to decrypt API key — possible tampering detected")
        raise exc


def hash_api_key(api_key: str) -> str:
    """Return a SHA-256 hex digest of the api_key for quick verification.

    Never store the plain key; only ever store this hash alongside the
    encrypted value.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def encrypt_field(value: str) -> str:
    """Encrypt a single string field (e.g. 2FA secret)."""
    f = _get_fernet(settings.field_encryption_key)
    return f.encrypt(value.encode()).decode()


def decrypt_field(encrypted_value: str) -> str:
    """Decrypt a single encrypted field."""
    f = _get_fernet(settings.field_encryption_key)
    return f.decrypt(encrypted_value.encode()).decode()


# ─────────────────────────────────────────────
# JWT Token Management
# ─────────────────────────────────────────────

def create_access_token(
    user_id: str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a short-lived JWT access token for the given user.

    Args:
        user_id: The user's UUID string.
        extra_claims: Optional additional claims to embed (e.g. roles).

    Returns:
        Signed JWT string.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        hours=settings.access_token_expire_hours
    )
    payload: dict[str, Any] = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> tuple[str, datetime]:
    """Create a long-lived JWT refresh token.

    Returns:
        (token_string, expiry_datetime)
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload: dict[str, Any] = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expire


def verify_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT, returning the full payload.

    Raises:
        JWTError: if the token is invalid, expired, or tampered with.
    """
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def get_token_subject(token: str) -> str | None:
    """Safely extract the 'sub' claim; returns None on any error."""
    try:
        payload = verify_token(token)
        return payload.get("sub")
    except JWTError:
        return None


# ─────────────────────────────────────────────
# Secure Random Generation
# ─────────────────────────────────────────────

def generate_secure_token(length: int = 32) -> str:
    """Return a URL-safe cryptographically secure random token."""
    return secrets.token_urlsafe(length)


def generate_2fa_secret() -> str:
    """Generate a random base32 TOTP secret for use with authenticator apps."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str, issuer: str = "Unitrader") -> str:
    """Return the otpauth:// URI used to generate a QR code."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code against the stored secret.

    Allows a 1-step window to account for clock skew.
    """
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_backup_codes(count: int = 8) -> list[str]:
    """Generate one-time backup codes for 2FA recovery."""
    return [secrets.token_hex(5).upper() for _ in range(count)]


# ─────────────────────────────────────────────
# Input Validation Helpers
# ─────────────────────────────────────────────

def validate_email(email: str) -> bool:
    """Basic email format check (Pydantic's EmailStr is preferred in schemas)."""
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_password(password: str) -> bool:
    """Check password meets complexity requirements.

    Rules: ≥12 chars, uppercase, lowercase, digit, special character.
    """
    if len(password) < 12:
        return False
    if not any(c.isupper() for c in password):
        return False
    if not any(c.islower() for c in password):
        return False
    if not any(c.isdigit() for c in password):
        return False
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False
    return True


def validate_ai_name(name: str) -> bool:
    """Check ai_name is alphanumeric (letters, digits, underscores), 2–20 chars."""
    return bool(re.match(r"^[a-zA-Z0-9_]{2,20}$", name))
