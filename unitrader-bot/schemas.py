"""
schemas.py — Pydantic request/response schemas for Unitrader.

Schemas validate input data and define the shape of API responses.
They are intentionally separate from SQLAlchemy models to keep the
API contract stable even when the database schema evolves.
"""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ─────────────────────────────────────────────
# Generic / Envelope
# ─────────────────────────────────────────────

class SuccessResponse(BaseModel):
    """Standard success envelope."""

    status: str = "success"
    message: str | None = None
    data: Any | None = None


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    status: str = "error"
    error: str
    code: str | None = None


# ─────────────────────────────────────────────
# Auth — Registration
# ─────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    """Payload for POST /api/auth/register."""

    email: EmailStr
    password: str = Field(..., min_length=12, max_length=128)
    ai_name: str = Field(..., min_length=2, max_length=20)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        """Enforce: uppercase, lowercase, digit, special character."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v

    @field_validator("ai_name")
    @classmethod
    def ai_name_alphanumeric(cls, v: str) -> str:
        """Only allow letters, digits, and underscores."""
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("ai_name must be alphanumeric (letters, digits, underscores only)")
        return v


# ─────────────────────────────────────────────
# Auth — Login
# ─────────────────────────────────────────────

class UserLoginRequest(BaseModel):
    """Payload for POST /api/auth/login."""

    email: EmailStr
    password: str


class TwoFAVerifyRequest(BaseModel):
    """Payload for POST /api/auth/2fa/verify."""

    code: str = Field(..., min_length=6, max_length=8)


class TwoFASetupResponse(BaseModel):
    """Response from POST /api/auth/2fa/setup."""

    status: str = "success"
    secret: str
    qr_code_url: str
    backup_codes: list[str]


# ─────────────────────────────────────────────
# Auth — Tokens
# ─────────────────────────────────────────────

class TokenResponse(BaseModel):
    """JWT token pair returned on successful login."""

    status: str = "logged_in"
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class AccessTokenResponse(BaseModel):
    """New access token from /api/auth/refresh-token."""

    status: str = "success"
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Payload for POST /api/auth/refresh-token."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Payload for POST /api/auth/logout."""

    refresh_token: str


# ─────────────────────────────────────────────
# Auth — Password Reset
# ─────────────────────────────────────────────

class PasswordResetRequestBody(BaseModel):
    """Payload for POST /api/auth/password-reset-request."""

    email: EmailStr


class PasswordResetBody(BaseModel):
    """Payload for POST /api/auth/password-reset."""

    reset_token: str
    new_password: str = Field(..., min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class EmailVerifyRequest(BaseModel):
    """Payload for POST /api/auth/verify-email."""

    verification_token: str


# ─────────────────────────────────────────────
# User
# ─────────────────────────────────────────────

class UserResponse(BaseModel):
    """Public user profile returned from the API."""

    id: str
    email: str
    ai_name: str
    subscription_tier: str
    trial_end_date: datetime | None
    email_verified: bool
    two_fa_enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────
# Trade
# ─────────────────────────────────────────────

class TradeResponse(BaseModel):
    """Trade record returned from the API."""

    id: str
    trading_account_id: str | None = None
    exchange: str | None = None
    is_paper: bool | None = None
    account_scope: str | None = None
    account_label: str | None = None
    symbol: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float | None
    profit: float | None
    loss: float | None
    profit_percent: float | None
    stop_loss: float
    take_profit: float
    status: str
    claude_confidence: float | None
    market_condition: str | None
    created_at: datetime
    closed_at: datetime | None

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────
# Conversation
# ─────────────────────────────────────────────

class ConversationResponse(BaseModel):
    """AI conversation record returned from the API."""

    id: str
    message: str
    response: str
    context_type: str
    sentiment: str | None
    is_helpful: bool | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────

class ServiceStatus(BaseModel):
    status: str  # healthy | degraded | error
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    services: dict[str, ServiceStatus] | None = None
    alpaca_rate_limiter: dict[str, Any] | None = None


# ─────────────────────────────────────────────
# User Settings
# ─────────────────────────────────────────────

class UserSettingsResponse(BaseModel):
    """User settings returned from GET /api/auth/settings."""

    id: str
    user_id: str
    max_position_size: float
    max_daily_loss: float
    max_trade_amount: float
    approved_assets: list[str] | None
    theme: str
    explanation_level: str
    trade_mode: str
    trading_paused: bool
    first_trade_done: bool
    leaderboard_opt_out: bool
    push_token: str | None
    signal_stack_mode: str = "browse"
    watchlist: list[str] | None = None
    auto_trade_enabled: bool = False
    auto_trade_threshold: int = 80
    auto_trade_max_per_scan: int = 1
    apex_selects_threshold: int = 75
    apex_selects_max_trades: int = 2
    apex_selects_asset_classes: list[str] | None = None
    morning_briefing_enabled: bool = True
    morning_briefing_time: str = "08:00"
    daily_digest_enabled: bool = True
    preferred_trading_account_id: str | None = None
    trader_class: str | None = None
    updated_at: datetime
    # Onboarding state — used by /trade gate and dashboard chat routing
    onboarding_complete: bool = False
    financial_goal: str | None = None
    risk_level_setting: str | None = None
    # Computed trade-size limits (from trader_class + trust ladder stage)
    min_trade_amount: float | None = None
    trade_limits: dict | None = None

    model_config = {"from_attributes": True}


class UpdateUserSettingsRequest(BaseModel):
    """Payload for PATCH /api/auth/settings.
    
    All fields are optional. Only provided fields will be updated.
    """

    explanation_level: str | None = None
    trade_mode: str | None = None
    max_trade_amount: float | None = None
    max_daily_loss: float | None = None
    max_position_size: float | None = None
    trading_paused: bool | None = None
    leaderboard_opt_out: bool | None = None
    approved_assets: list[str] | None = None
    first_trade_done: bool | None = None
    push_token: str | None = None
    signal_stack_mode: str | None = None
    watchlist: list[str] | None = None
    auto_trade_enabled: bool | None = None
    auto_trade_threshold: int | None = None
    auto_trade_max_per_scan: int | None = None
    apex_selects_threshold: int | None = None
    apex_selects_max_trades: int | None = None
    apex_selects_asset_classes: list[str] | None = None
    morning_briefing_enabled: bool | None = None
    morning_briefing_time: str | None = None
    daily_digest_enabled: bool | None = None
    preferred_trading_account_id: str | None = None
    trader_class: str | None = None
    # Onboarding fields
    onboarding_complete: bool | None = None
    financial_goal: str | None = None
    risk_level_setting: str | None = None
