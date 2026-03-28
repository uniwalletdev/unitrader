"""
config.py — Application configuration.

All settings are loaded from environment variables (via .env file).
Required variables are validated on startup; missing values will raise an error.
"""

import logging
from functools import lru_cache
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Central configuration for Unitrader.

    All fields map 1-to-1 to environment variables (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─────────────────────────────────────────────
    # Application
    # ─────────────────────────────────────────────
    app_name: str = "Unitrader"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    api_host: str = "http://localhost"
    api_port: int = 8000
    frontend_url: str = "http://localhost:3000"  # used in Stripe redirect URLs

    # ─────────────────────────────────────────────
    # Database
    # ─────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./unitrader.db"
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800  # recycle connections every 30 min
    # Set DB_USE_NULLPOOL=true to force NullPool for all postgres connections
    # (only needed for PgBouncer transaction-mode poolers not on port 6543)
    db_use_nullpool: bool = False

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    # ─────────────────────────────────────────────
    # Authentication / JWT
    # ─────────────────────────────────────────────
    clerk_publishable_key: str = ""   # pk_test_... (from .env CLERK_API_KEY)
    clerk_secret_key: str = ""         # sk_test_... (required for backend JWT verification)

    @property
    def clerk_jwks_url(self) -> str:
        """Derive the Clerk JWKS endpoint from the publishable key."""
        key = self.clerk_publishable_key or self.clerk_api_key
        if not key:
            return ""
        # publishable key = "pk_test_" + base64(domain)
        try:
            import base64
            suffix = key.split("_", 2)[-1]  # strip pk_test_ or pk_live_
            # pad base64 if needed
            padded = suffix + "=" * (-len(suffix) % 4)
            domain = base64.b64decode(padded).decode().rstrip("$")
            return f"https://{domain}/.well-known/jwks.json"
        except Exception:
            return ""

    # keep old field name as alias for backward compatibility
    clerk_api_key: str = ""
    jwt_secret_key: str = "change-this-in-production-min-32-chars!!"
    jwt_algorithm: str = "HS256"
    access_token_expire_hours: int = 1
    refresh_token_expire_days: int = 30

    # ─────────────────────────────────────────────
    # Encryption
    # ─────────────────────────────────────────────
    master_encryption_key: str = ""
    field_encryption_key: str = ""

    # ─────────────────────────────────────────────
    # AI / LLM
    # ─────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-haiku-20240307"
    anthropic_base_url: str = "https://api.anthropic.com"

    # ─────────────────────────────────────────────
    # Payments
    # ─────────────────────────────────────────────
    stripe_secret_key: str = ""
    stripe_public_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_pro_price_id: str = ""  # Stripe Price ID for Pro monthly plan
    stripe_base_url: str = "https://api.stripe.com"

    # ─────────────────────────────────────────────
    # Email
    # ─────────────────────────────────────────────
    resend_api_key: str = ""
    email_from: str = "noreply@unitrader.app"
    resend_base_url: str = "https://api.resend.com"

    # ─────────────────────────────────────────────
    # Trading APIs
    # ─────────────────────────────────────────────
    # Comma-separated list of exchanges available for user connections.
    # Set ENABLED_EXCHANGES in Railway to add more when they're ready.
    enabled_exchanges: str = "alpaca,coinbase"

    @property
    def enabled_exchange_list(self) -> list[str]:
        return [e.strip().lower() for e in self.enabled_exchanges.split(",") if e.strip()]

    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_base_url: str = "https://api.binance.com"

    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_data_url: str = "https://data.alpaca.markets"

    oanda_api_key: str = ""
    oanda_account_id: str = ""
    oanda_base_url: str = "https://api-fxpractice.oanda.com"

    # ─────────────────────────────────────────────
    # Telegram Bot
    # ─────────────────────────────────────────────
    telegram_bot_token:    str = ""
    telegram_bot_username: str = "unitrader_bot"  # e.g. unitraderAI_bot (no @)
    # Public HTTPS URL used for Telegram webhook registration and logs.
    # Production (Railway): https://api.unitrader.ai  (set API_BASE_URL in Railway)
    # Development: use ngrok — ngrok http 8000 → copy the https URL
    api_base_url: str = "http://localhost:8000"

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def telegram_bot_handle(self) -> str:
        """Return @username (always includes the @ prefix)."""
        u = self.telegram_bot_username.lstrip("@")
        return f"@{u}" if u else "@unitrader_bot"

    # ─────────────────────────────────────────────
    # WhatsApp / Twilio
    # ─────────────────────────────────────────────
    twilio_account_sid:      str = ""
    twilio_auth_token:       str = ""
    # Twilio WhatsApp sender — Sandbox: +14155238886, Production: your approved number
    twilio_whatsapp_number:  str = ""

    @property
    def whatsapp_enabled(self) -> bool:
        return all([
            self.twilio_account_sid,
            self.twilio_auth_token,
            self.twilio_whatsapp_number,
        ])

    # ─────────────────────────────────────────────
    # Monitoring
    # ─────────────────────────────────────────────
    sentry_dsn: str = ""

    # ─────────────────────────────────────────────
    # CORS
    # ─────────────────────────────────────────────
    # Production: set ALLOWED_ORIGINS to your Vercel URL(s) + custom frontend domain if any.
    allowed_origins: str = (
        "http://localhost:3000,http://localhost:8080,"
        "https://unitraderai.vercel.app,https://unitrader.ai"
    )

    # ─────────────────────────────────────────────
    # Rate Limiting
    # ─────────────────────────────────────────────
    rate_limit_login: str = "5/15minutes"
    rate_limit_general: str = "100/minute"
    rate_limit_trading: str = "10/minute"

    # ─────────────────────────────────────────────
    # Admin
    # ─────────────────────────────────────────────
    # Set ADMIN_SECRET_KEY in your .env to a strong random string.
    # This key protects the admin-only endpoints (e.g. force-delete a user).
    admin_secret_key: str = ""

    # ─────────────────────────────────────────────
    # Feature Flags
    # ─────────────────────────────────────────────
    feature_2fa_enabled: bool = True
    feature_trading_enabled: bool = True
    feature_ai_analysis_enabled: bool = True
    feature_email_verification: bool = True
    feature_stripe_billing: bool = False  # enable when Stripe is configured
    testing_mode: str = "false"  # Set to "true" to bypass trade limits

    # ─────────────────────────────────────────────
    # Validators
    # ─────────────────────────────────────────────

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}")
        return v

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("jwt_secret_key must be at least 32 characters")
        return v

    # ─────────────────────────────────────────────
    # Computed properties
    # ─────────────────────────────────────────────

    @property
    def allowed_origins_list(self) -> List[str]:
        """Return CORS origins as a list."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_staging(self) -> bool:
        return self.environment == "staging"

    @property
    def use_ssl(self) -> bool:
        """Whether SSL should be enforced (production/staging only)."""
        return self.environment in {"production", "staging"}

    @property
    def db_ssl_args(self) -> dict:
        """Extra SQLAlchemy connect_args for asyncpg.

        Supabase poolers (both Session :5432 and Transaction :6543) use a
        self-signed certificate chain that asyncpg rejects with ssl=True.
        No SSL connect_args are needed — the pooler handles encryption.

        For standard PostgreSQL with SSL, pass ssl=True.
        """
        if "pooler.supabase.com" in self.database_url:
            return {}  # Supabase pooler handles SSL internally
        if self.use_ssl and "postgresql" in self.database_url:
            return {"ssl": True}
        return {}


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    _settings = Settings()
    logger.info(
        "Config loaded — env=%s debug=%s", _settings.environment, _settings.debug
    )
    return _settings


settings = get_settings()
