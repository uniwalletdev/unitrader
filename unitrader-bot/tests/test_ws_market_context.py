"""
tests/test_ws_market_context.py — Regression coverage for MarketContext-aware price streaming.

Focus:
- trading_account_id ownership enforcement for WS routing helpers
- Coinbase mode blocks stock symbols (stocks require Alpaca connection)
"""

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from models import TradingAccount, User  # noqa: E402
from routers import ws as ws_router  # noqa: E402
from src.market_context import resolve_market_context  # noqa: E402


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
async def test_resolve_market_context_enforces_ownership(db: AsyncSession):
    await _create_user(db, "ws-user-1")
    acct = TradingAccount(
        user_id="ws-user-1",
        exchange="coinbase",
        is_paper=False,
        account_label="Coinbase Live",
        is_active=True,
    )
    db.add(acct)
    await db.commit()

    ctx = await resolve_market_context(db=db, user_id="ws-user-1", trading_account_id=acct.id)
    assert ctx.exchange.value == "coinbase"
    assert ctx.is_paper is False

    with pytest.raises(HTTPException) as exc:
        await resolve_market_context(db=db, user_id="ws-user-OTHER", trading_account_id=acct.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_coinbase_blocks_stock_symbols():
    with pytest.raises(ValueError) as exc:
        await ws_router._fetch_latest_quote("AAPL", exchange="coinbase")  # noqa: SLF001
    assert "stocks_require_alpaca" in str(exc.value)

