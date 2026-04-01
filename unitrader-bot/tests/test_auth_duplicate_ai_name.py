"""
tests/test_auth_duplicate_ai_name.py — Regression coverage for duplicate bot names.

Ensures ai_name remains a display field and does not need to be globally unique.
"""

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from database import Base
from models import RefreshToken, User, UserSettings
from routers.auth import ClerkSetupRequest, clerk_setup


_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_test_engine = create_async_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

_TestSession = async_sessionmaker(
    bind=_test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_tables():
    import models  # noqa: F401

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db():
    async with _TestSession() as session:
        yield session
        await session.rollback()


async def _create_user(session: AsyncSession, user_id: str, email: str) -> User:
    user = User(
        id=user_id,
        email=email,
        password_hash="hashed",
        ai_name="",
        email_verified=False,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_clerk_setup_allows_duplicate_ai_names(db: AsyncSession):
    await _create_user(db, "user-duplicate-1", "one@example.com")
    await _create_user(db, "user-duplicate-2", "two@example.com")

    first = await clerk_setup(
        ClerkSetupRequest(user_id="user-duplicate-1", ai_name="TradeMaster"),
        db=db,
    )
    second = await clerk_setup(
        ClerkSetupRequest(user_id="user-duplicate-2", ai_name="TradeMaster"),
        db=db,
    )

    assert first["status"] == "logged_in"
    assert second["status"] == "logged_in"

    users = (
        await db.execute(
            select(User).where(User.id.in_(["user-duplicate-1", "user-duplicate-2"]))
        )
    ).scalars().all()
    assert len(users) == 2
    assert {user.ai_name for user in users} == {"TradeMaster"}


@pytest.mark.asyncio
async def test_clerk_setup_keeps_user_state_isolated(db: AsyncSession):
    await _create_user(db, "user-isolated-1", "isolated-one@example.com")
    await _create_user(db, "user-isolated-2", "isolated-two@example.com")

    await clerk_setup(
        ClerkSetupRequest(user_id="user-isolated-1", ai_name="SameBot"),
        db=db,
    )
    await clerk_setup(
        ClerkSetupRequest(user_id="user-isolated-2", ai_name="SameBot"),
        db=db,
    )

    settings = (
        await db.execute(
            select(UserSettings).where(
                UserSettings.user_id.in_(["user-isolated-1", "user-isolated-2"])
            )
        )
    ).scalars().all()
    tokens = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id.in_(["user-isolated-1", "user-isolated-2"])
            )
        )
    ).scalars().all()

    assert {setting.user_id for setting in settings} == {
        "user-isolated-1",
        "user-isolated-2",
    }
    assert {token.user_id for token in tokens} == {
        "user-isolated-1",
        "user-isolated-2",
    }
