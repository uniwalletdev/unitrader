"""
database.py — Async SQLAlchemy engine, session factory, and helpers.

Uses asyncpg for PostgreSQL (production) and aiosqlite for SQLite (development).
Connection pooling is configured for production workloads.

Future migrations: use Alembic (alembic init alembic) once the schema stabilises.
"""

import logging
from collections.abc import AsyncGenerator
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────

# Translate sync postgres:// → async asyncpg driver notation
_db_url = settings.database_url
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)

# SQLite doesn't support pool_size / max_overflow
_is_sqlite = "sqlite" in _db_url

# In managed production setups (Railway/Supabase/PgBouncer), asyncpg prepared
# statement caching can produce "already exists" / "does not exist" errors.
# Use NullPool + disabled statement caching for ALL PostgreSQL connections
# to keep connections stateless and PgBouncer-safe.  There is no meaningful
# downside even when PgBouncer is absent.
_is_postgres = "postgresql+asyncpg://" in _db_url
_pgbouncer_safe_mode = _is_postgres and not _is_sqlite

# SQLAlchemy's asyncpg dialect still prepares statements by default. With the
# Supabase transaction pooler, those statements can collide or disappear across
# backend connections unless we disable the cache and use unique names.
if _pgbouncer_safe_mode and "prepared_statement_cache_size=" not in _db_url:
    _db_url = f"{_db_url}{'&' if '?' in _db_url else '?'}prepared_statement_cache_size=0"

_engine_kwargs: dict = {
    "echo": settings.debug,
    "future": True,
}

_connect_args: dict = {}
if settings.db_ssl_args:
    _connect_args.update(settings.db_ssl_args)

if _pgbouncer_safe_mode:
    _engine_kwargs["poolclass"] = NullPool
    _connect_args.update(
        {
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        }
    )
elif not _is_sqlite:
    _engine_kwargs.update(
        {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
            "pool_pre_ping": True,  # validate connections before use
        }
    )

if _connect_args:
    _engine_kwargs["connect_args"] = _connect_args

engine = create_async_engine(_db_url, **_engine_kwargs)

logger.info(
    "DB engine created — pgbouncer_safe_mode=%s pool=%s",
    _pgbouncer_safe_mode,
    "NullPool" if _pgbouncer_safe_mode else "QueuePool",
)

# ─────────────────────────────────────────────
# Session Factory
# ─────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ─────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ─────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────

async def create_tables() -> None:
    """Create all tables defined in models.py.

    Idempotent — safe to call multiple times; existing tables are left intact.
    Also runs lightweight column migrations for SQLite (ALTER TABLE ADD COLUMN).
    """
    import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # SQLite doesn't support IF NOT EXISTS on ADD COLUMN — use try/except per column
    if _is_sqlite:
        new_columns = [
            # Trial system columns (added in earlier sprint)
            ("users", "trial_started_at", "DATETIME"),
            ("users", "trial_status",     "VARCHAR(20) NOT NULL DEFAULT 'active'"),
            # bot_messages: response timing (added with external-account models)
            ("bot_messages", "response_time_ms", "INTEGER"),
            # telegram_linking_codes: bot-initiated flow fields
            ("telegram_linking_codes", "telegram_user_id", "VARCHAR(128)"),
            ("telegram_linking_codes", "telegram_username", "VARCHAR(128)"),
        ]
        # user_external_accounts, bot_messages, telegram_linking_codes are new tables
        # and are fully created by create_all above — only need column migrations for
        # columns added after the initial table creation.
        async with engine.begin() as conn:
            for table, col, col_def in new_columns:
                try:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"
                    )
                    logger.info("Migration: added column %s.%s", table, col)
                except Exception:
                    pass  # column already exists — safe to ignore

    logger.info("Database tables initialised")

    # Ensure the 'system' user exists — required as FK target for agent_outcomes
    # when background agents (content, learning) write outcomes without a real user.
    await _ensure_system_user()


async def _ensure_system_user() -> None:
    """Create a sentinel 'system' user row if it doesn't already exist.

    Background agents (content scheduler, learning hub) write to
    agent_outcomes with user_id='system'.  Without this row the FK
    constraint on agent_outcomes.user_id → users.id fails.

    Uses raw SQL to avoid ORM column-mapping issues with Supabase.
    """
    from sqlalchemy import text

    try:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT id FROM users WHERE id = :uid"),
                {"uid": "system"},
            )
            if row.first() is None:
                await conn.execute(
                    text(
                        "INSERT INTO users "
                        "(id, email, password_hash, ai_name, subscription_tier, "
                        " trial_status, email_verified, is_active, two_fa_enabled) "
                        "VALUES "
                        "(:id, :email, :pw, :ai, :tier, :ts, :ev, :ia, :tfa)"
                    ),
                    {
                        "id": "system",
                        "email": "system@unitrader.internal",
                        "pw": "!system-no-login",
                        "ai": "System",
                        "tier": "pro",
                        "ts": "active",
                        "ev": True,
                        "ia": True,
                        "tfa": False,
                    },
                )
                logger.info("Created sentinel 'system' user for background agents")
            else:
                logger.debug("Sentinel 'system' user already exists")
    except Exception as exc:
        logger.warning("Could not ensure system user (non-fatal): %s", exc)


async def drop_tables() -> None:
    """Drop ALL tables — for use in tests only, never in production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.warning("All database tables dropped")


# ─────────────────────────────────────────────
# Dependency Injection
# ─────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session per request.

    Commits on success, rolls back on any exception, always closes.

    Usage:
        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
