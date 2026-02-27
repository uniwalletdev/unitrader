"""
models.py — SQLAlchemy ORM models for Unitrader.

All models use UUIDs as primary keys and include audit timestamps.
Sensitive fields (API keys) are stored encrypted via security.py.
"""

import uuid
from datetime import datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# REFRESH TOKEN
# ─────────────────────────────────────────────────────────────────────────────

class RefreshToken(Base):
    """Long-lived JWT refresh token stored per session.

    Tokens are revoked on logout and expire automatically.
    One user can have multiple active sessions (devices).
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    token: Mapped[str] = mapped_column(
        String(512), unique=True, nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<RefreshToken id={self.id} user_id={self.user_id} revoked={self.is_revoked}>"


class TimestampMixin:
    """Adds created_at / updated_at to any model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────────────────────────────────────

class User(TimestampMixin, Base):
    """Registered Unitrader user.

    Contains credentials, subscription state, and 2FA configuration.
    Broker API keys are stored in the separate ExchangeAPIKey model.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Personalisation
    ai_name: Mapped[str] = mapped_column(String(20), nullable=False, default="Claude")

    # Subscription
    subscription_tier: Mapped[str] = mapped_column(
        String(20), nullable=False, default="free"  # free | pro
    )
    trial_end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"  # active | expired | converted
    )

    # Account state
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 2FA
    two_fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_fa_secret: Mapped[str | None] = mapped_column(
        String(512), nullable=True  # stored encrypted
    )

    # Stripe billing
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    stripe_subscription_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True  # active | trialing | past_due | canceled | unpaid
    )
    subscription_current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Email verification / password reset tokens
    email_verification_token: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    password_reset_token: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    password_reset_expires: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────────────
    trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ExchangeAPIKey"]] = relationship(
        "ExchangeAPIKey", back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped["UserSettings | None"] = relationship(
        "UserSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="user", cascade="all, delete-orphan"
    )
    external_accounts: Mapped[list["UserExternalAccount"]] = relationship(
        "UserExternalAccount", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"


# ─────────────────────────────────────────────────────────────────────────────
# TRADE
# ─────────────────────────────────────────────────────────────────────────────

class Trade(Base):
    """A single trade executed (or proposed) by the AI.

    Captures entry/exit prices, risk parameters, and the AI's confidence
    score at the time of execution.
    """

    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Trade details
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. BTC/USD
    side: Mapped[str] = mapped_column(String(4), nullable=False)      # BUY | SELL
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # P&L
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Risk management
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")  # open | closed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_time: Mapped[float | None] = mapped_column(Float, nullable=True)  # ms

    # AI metadata
    claude_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0–100
    market_condition: Mapped[str | None] = mapped_column(
        String(20), nullable=True  # uptrend | downtrend | consolidating
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="trades")

    # ── Indexes ───────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_trades_user_status", "user_id", "status"),
        Index("ix_trades_user_created", "user_id", "created_at"),
        Index("ix_trades_user_symbol", "user_id", "symbol"),
    )

    def __repr__(self) -> str:
        return f"<Trade id={self.id} symbol={self.symbol} side={self.side} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION
# ─────────────────────────────────────────────────────────────────────────────

class Conversation(Base):
    """A single message–response exchange between the user and the AI.

    Context type categorises the conversation so history can be filtered
    per domain (e.g. only load trading context for trade decisions).
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    message: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    context_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="chat"  # chat | trading | support | analysis
    )
    sentiment: Mapped[str | None] = mapped_column(
        String(10), nullable=True  # positive | negative | neutral
    )
    is_helpful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="conversations")

    __table_args__ = (
        Index("ix_conversations_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} user_id={self.user_id} type={self.context_type}>"


# ─────────────────────────────────────────────────────────────────────────────
# EXCHANGE API KEY
# ─────────────────────────────────────────────────────────────────────────────

class ExchangeAPIKey(Base):
    """Encrypted broker API credentials belonging to a user.

    Both api_key and api_secret are stored using Fernet symmetric encryption.
    key_hash allows verification without decryption.
    """

    __tablename__ = "exchange_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    exchange: Mapped[str] = mapped_column(
        String(20), nullable=False  # binance | alpaca | oanda
    )
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_secret: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="api_keys")

    def __repr__(self) -> str:
        return f"<ExchangeAPIKey id={self.id} exchange={self.exchange} user_id={self.user_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# USER SETTINGS
# ─────────────────────────────────────────────────────────────────────────────

class UserSettings(Base):
    """Per-user trading risk limits and UI preferences.

    One-to-one with User; created automatically on registration.
    """

    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Risk limits (percentages of account balance)
    max_position_size: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    max_daily_loss: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)

    # Allowed assets (JSON array: ["BTC", "ETH", ...])
    approved_assets: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Trading hours (UTC)
    trading_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    trading_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    # Require manual confirmation for trades above this USD value
    require_confirmation_above: Mapped[float | None] = mapped_column(Float, nullable=True)

    # UI
    theme: Mapped[str] = mapped_column(String(10), default="dark", nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="settings")

    def __repr__(self) -> str:
        return f"<UserSettings id={self.id} user_id={self.user_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────────────────────

class AuditLog(Base):
    """Immutable record of security-relevant events.

    Never updated — only inserted. event_details is free-form JSON so new
    event types can be added without schema migrations.
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,  # nullable for system-level events
    )

    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
        # login | logout | register | trade_executed | api_key_added |
        # api_key_rotated | password_changed | 2fa_enabled | 2fa_disabled
    )
    event_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User | None"] = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_logs_user_timestamp", "user_id", "timestamp"),
        Index("ix_audit_logs_event_timestamp", "event_type", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} event={self.event_type} user_id={self.user_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# EXTERNAL PLATFORM ACCOUNTS (Telegram / Discord / WhatsApp)
# ─────────────────────────────────────────────────────────────────────────────

class UserExternalAccount(Base):
    """Links a Unitrader user to a messaging-platform identity.

    A user can connect multiple platforms (Telegram + Discord + WhatsApp).
    Each row is uniquely identified by (platform, external_id) — one platform
    identity can only ever belong to one Unitrader account at a time.

    settings stores per-platform preferences, e.g.:
        {"notifications": true, "trade_alerts": true, "daily_summary": false}
    """

    __tablename__ = "user_external_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    platform: Mapped[str] = mapped_column(
        String(20), nullable=False  # telegram | discord | whatsapp
    )
    external_id: Mapped[str] = mapped_column(
        String(128), nullable=False  # Telegram user_id, Discord snowflake, WhatsApp phone
    )
    external_username: Mapped[str | None] = mapped_column(
        String(128), nullable=True  # @handle, display name, or phone number
    )

    is_linked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Platform-specific preferences JSON (notifications, trade_alerts, etc.)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="external_accounts")

    __table_args__ = (
        # One platform identity can only link to one Unitrader account
        UniqueConstraint("platform", "external_id", name="uq_platform_external_id"),
        Index("ix_uea_user_platform", "user_id", "platform"),
        Index("ix_uea_external_platform", "external_id", "platform"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserExternalAccount platform={self.platform} "
            f"external_id={self.external_id} user_id={self.user_id}>"
        )


class BotMessage(Base):
    """Immutable log of every message exchanged with a platform bot.

    Written on every inbound command and every outbound reply.
    Drives analytics (most-used commands, error rates) and debugging.

    message_type values:
        "command"  — /portfolio, /trade, /status, etc.
        "message"  — free-text conversation
        "trade"    — AI executed a trade triggered from bot
        "query"    — read-only data request (price, balance)
        "alert"    — outbound notification sent to user (no inbound)
    """

    __tablename__ = "bot_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,  # nullable — message may arrive before account is linked
    )

    platform: Mapped[str] = mapped_column(
        String(20), nullable=False  # telegram | discord | whatsapp
    )
    external_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False  # raw platform ID, always present
    )

    message_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="message"
        # command | message | trade | query | alert
    )
    command: Mapped[str | None] = mapped_column(
        String(64), nullable=True  # "/portfolio", "/trade BTC", etc.
    )

    user_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success"
        # success | error | pending | ignored
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # How long the bot took to respond (milliseconds)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User | None"] = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_bot_messages_created", "created_at"),
        Index("ix_bot_messages_user_platform", "user_id", "platform"),
        Index("ix_bot_messages_external_platform", "external_user_id", "platform"),
        Index("ix_bot_messages_status", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<BotMessage platform={self.platform} type={self.message_type} "
            f"status={self.status}>"
        )


class TelegramLinkingCode(Base):
    """Short-lived 6-digit code used to connect a Telegram account to Unitrader.

    Two flows use this table:

    Web-initiated (most common):
        1. Logged-in user clicks "Connect Telegram" in the dashboard
        2. Backend generates a code and stores it with user_id pre-filled
        3. User sends /link <code> to the bot
        4. Bot finds the code, marks it used, creates UserExternalAccount

    Bot-initiated:
        1. User sends /link to the bot with no prior web session
        2. Bot generates a code with user_id=None
        3. User enters the code on the Unitrader website to complete linking
        4. Website resolves user_id, marks code used, creates UserExternalAccount

    Codes expire after 15 minutes and are invalidated on first use.
    """

    __tablename__ = "telegram_linking_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(
        String(6), unique=True, nullable=False, index=True  # 6-digit numeric string
    )

    # Pre-filled for web-initiated flow; null for bot-initiated flow
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    # Filled by the bot during bot-initiated flow (the Telegram user_id)
    telegram_user_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    telegram_username: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )

    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False  # created_at + 15 minutes
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User | None"] = relationship("User")

    __table_args__ = (
        Index("ix_tlc_expires_used", "expires_at", "is_used"),
    )

    def __repr__(self) -> str:
        return (
            f"<TelegramLinkingCode code={self.code} used={self.is_used} "
            f"user_id={self.user_id}>"
        )


# ─────────────────────────────────────────────────────────────────────────────
# LEARNING HUB — Pattern / Instruction / Output
# ─────────────────────────────────────────────────────────────────────────────

class Pattern(Base):
    """A discovered cross-agent pattern stored by LearningHub.

    Examples:
        "Momentum trades on BTC achieve 85% win rate"
        "Content about risk management drives 3x engagement"
    """

    __tablename__ = "patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    pattern_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    supporting_agents: Mapped[list | None] = mapped_column(
        JSON, nullable=True  # ["trading", "content", "conversation"]
    )
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        String(30), nullable=False, default="general"
        # trading | content | support | general
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_patterns_active_category", "is_active", "category"),
        Index("ix_patterns_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<Pattern id={self.id} name={self.pattern_name!r} score={self.confidence_score}>"


class AgentInstruction(Base):
    """A directive sent from LearningHub to a specific agent.

    Agents poll for their active instructions before each work cycle.
    Once followed, the instruction is marked 'completed'.
    """

    __tablename__ = "agent_instructions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_name: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
        # trading | content_writer | social_media | conversation | email
    )
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    source_pattern_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("patterns.id", ondelete="SET NULL"), nullable=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)  # 1 (low) – 10 (critical)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"  # active | completed | archived
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Relationships ──────────────────────────────────────────────────────
    source_pattern: Mapped["Pattern | None"] = relationship("Pattern")

    __table_args__ = (
        Index("ix_agent_instructions_agent_status", "agent_name", "status"),
    )

    def __repr__(self) -> str:
        return f"<AgentInstruction agent={self.agent_name} priority={self.priority} status={self.status}>"


class AgentOutput(Base):
    """A record of anything an agent produced — trade, post, email, analysis.

    Metrics and outcome are filled in after the fact so LearningHub can
    measure what actually worked.
    """

    __tablename__ = "agent_outputs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_name: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    output_type: Mapped[str] = mapped_column(
        String(30), nullable=False
        # "trade" | "blog_post" | "social_post" | "email" | "pattern_analysis"
    )
    content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # engagement, pnl, open_rate, etc.
    outcome: Mapped[str | None] = mapped_column(
        String(20), nullable=True  # "success" | "failure" | "pending"
    )
    source_instruction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_instructions.id", ondelete="SET NULL"), nullable=True
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────────────────
    source_instruction: Mapped["AgentInstruction | None"] = relationship("AgentInstruction")

    __table_args__ = (
        Index("ix_agent_outputs_agent_type", "agent_name", "output_type"),
        Index("ix_agent_outputs_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AgentOutput agent={self.agent_name} type={self.output_type} outcome={self.outcome}>"


# ─────────────────────────────────────────────────────────────────────────────
# BLOG POST
# ─────────────────────────────────────────────────────────────────────────────

class BlogPost(Base):
    """AI-generated blog post for marketing content.

    Generated by ContentWriterAgent and stored for publishing/review.
    seo_keywords is a JSON array of target keyword strings.
    """

    __tablename__ = "blog_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(350), unique=True, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    seo_keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    estimated_read_time: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<BlogPost id={self.id} slug={self.slug}>"


# ─────────────────────────────────────────────────────────────────────────────
# SOCIAL POST
# ─────────────────────────────────────────────────────────────────────────────

class SocialPost(Base):
    """AI-generated social media post.

    Supports multiple platforms; hashtags stored as a JSON array.
    scheduled_for tracks when it should be published in the social calendar.
    """

    __tablename__ = "social_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(
        String(20), nullable=False  # twitter | linkedin | instagram | facebook
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    post_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="educational"
        # educational | social_proof | call_to_action | inspirational
    )
    topic: Mapped[str | None] = mapped_column(String(300), nullable=True)
    estimated_engagement: Mapped[str | None] = mapped_column(
        String(10), nullable=True  # high | medium | low
    )
    is_posted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_social_posts_scheduled", "scheduled_for", "is_posted"),
        Index("ix_social_posts_platform", "platform", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SocialPost id={self.id} platform={self.platform} type={self.post_type}>"
