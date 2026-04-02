"""
tests/test_market_endpoints_account_scoping.py — Regression coverage for exchange-aware market widgets.

Focus: ensure /market-top and /exchange-assets resolve exchange from trading_account_id
and do not depend on hardcoded frontend exchange values.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from database import Base  # noqa: E402
from models import TradingAccount, User  # noqa: E402
from routers import trading as trading_router  # noqa: E402


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
    # Create only the tables this test needs.
    # Some production tables use Postgres-only types (e.g., UUID) and can't be
    # created under SQLite for unit tests.
    async with _test_engine.begin() as conn:
        await conn.run_sync(User.__table__.create, checkfirst=True)
        await conn.run_sync(TradingAccount.__table__.create, checkfirst=True)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(TradingAccount.__table__.drop, checkfirst=True)
        await conn.run_sync(User.__table__.drop, checkfirst=True)


@pytest_asyncio.fixture
async def db():
    async with _TestSession() as session:
        yield session
        await session.rollback()


async def _create_user(session: AsyncSession, user_id: str) -> None:
    session.add(
        User(
            id=user_id,
            email=f"{user_id}@example.com",
            password_hash="hashed",
            ai_name="Bot",
            email_verified=True,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_exchange_assets_resolves_exchange_from_trading_account_id(db: AsyncSession):
    await _create_user(db, "market-user-1")
    acct = TradingAccount(
        user_id="market-user-1",
        exchange="coinbase",
        is_paper=True,
        account_label="Coinbase Paper",
        is_active=True,
    )
    db.add(acct)
    await db.commit()

    current_user = SimpleNamespace(id="market-user-1")
    res = await trading_router.get_exchange_assets(
        exchange="alpaca",  # intentionally wrong; should be ignored when trading_account_id provided
        trading_account_id=acct.id,
        limit=5,
        current_user=current_user,
        db=db,
    )

    assert res["status"] == "success"
    data = res["data"]
    assert isinstance(data, list)
    assert len(data) == 5
    # Coinbase universe uses dash-format symbols like BTC-USD
    assert data[0]["symbol"].endswith("-USD")


@pytest.mark.asyncio
async def test_market_top_uses_account_exchange_for_cache_key(db: AsyncSession):
    await _create_user(db, "market-user-2")
    acct = TradingAccount(
        user_id="market-user-2",
        exchange="coinbase",
        is_paper=True,
        account_label="Coinbase Paper",
        is_active=True,
    )
    db.add(acct)
    await db.commit()

    # Prime cache for coinbase so the endpoint returns quickly (no external calls)
    trading_router._market_top_cache["coinbase"] = {  # noqa: SLF001
        "data": [{"symbol": "BTC-USD", "label": "Bitcoin", "decision": "WAIT", "confidence": 50}],
        "at": datetime.now(timezone.utc),
    }

    current_user = SimpleNamespace(id="market-user-2")
    res = await trading_router.get_market_top(
        exchange="alpaca",  # intentionally wrong; should be ignored when trading_account_id provided
        trading_account_id=acct.id,
        limit=1,
        refresh=False,
        current_user=current_user,
        db=db,
    )

    assert res["status"] == "success"
    assert res.get("cached") is True
    assert res["data"][0]["symbol"] == "BTC-USD"

