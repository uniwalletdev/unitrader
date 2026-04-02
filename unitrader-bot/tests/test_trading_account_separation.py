"""
tests/test_trading_account_separation.py — Regression coverage for account scoping.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from database import Base
from models import Trade, TradingAccount, User, UserSettings
from routers.trading import _resolve_trading_account_for_user, get_trade_history


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
        await conn.run_sync(UserSettings.__table__.create, checkfirst=True)
        await conn.run_sync(TradingAccount.__table__.create, checkfirst=True)
        await conn.run_sync(Trade.__table__.create, checkfirst=True)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Trade.__table__.drop, checkfirst=True)
        await conn.run_sync(TradingAccount.__table__.drop, checkfirst=True)
        await conn.run_sync(UserSettings.__table__.drop, checkfirst=True)
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
async def test_resolve_prefers_user_selected_trading_account(db: AsyncSession):
    await _create_user(db, "account-user-1")
    paper = TradingAccount(
        user_id="account-user-1",
        exchange="alpaca",
        is_paper=True,
        account_label="Alpaca Paper",
    )
    live = TradingAccount(
        user_id="account-user-1",
        exchange="alpaca",
        is_paper=False,
        account_label="Alpaca Live",
    )
    db.add_all([paper, live])
    await db.flush()
    db.add(UserSettings(user_id="account-user-1", preferred_trading_account_id=live.id))
    await db.commit()

    resolved = await _resolve_trading_account_for_user(
        db,
        user_id="account-user-1",
        exchange="alpaca",
    )

    assert resolved is not None
    assert resolved.id == live.id


@pytest.mark.asyncio
async def test_trade_history_filters_by_trading_account(db: AsyncSession):
    await _create_user(db, "account-user-2")
    paper = TradingAccount(
        user_id="account-user-2",
        exchange="alpaca",
        is_paper=True,
        account_label="Alpaca Paper",
    )
    live = TradingAccount(
        user_id="account-user-2",
        exchange="alpaca",
        is_paper=False,
        account_label="Alpaca Live",
    )
    db.add_all([paper, live])
    await db.flush()
    db.add_all(
        [
            Trade(
                user_id="account-user-2",
                trading_account_id=paper.id,
                exchange="alpaca",
                is_paper=True,
                account_scope="account_scoped",
                symbol="AAPL",
                side="BUY",
                quantity=1,
                entry_price=100,
                exit_price=110,
                profit=10,
                profit_percent=10,
                stop_loss=95,
                take_profit=120,
                status="closed",
            ),
            Trade(
                user_id="account-user-2",
                trading_account_id=live.id,
                exchange="alpaca",
                is_paper=False,
                account_scope="account_scoped",
                symbol="MSFT",
                side="BUY",
                quantity=1,
                entry_price=200,
                exit_price=180,
                loss=20,
                profit_percent=-10,
                stop_loss=190,
                take_profit=220,
                status="closed",
            ),
        ]
    )
    await db.commit()

    current_user = SimpleNamespace(id="account-user-2")
    response = await get_trade_history(
        current_user=current_user,
        db=db,
        symbol=None,
        from_date=None,
        to_date=None,
        outcome=None,
        trading_account_id=paper.id,
        exchange=None,
        is_paper=None,
        limit=50,
        offset=0,
    )

    trades = response["data"]["trades"]
    assert len(trades) == 1
    assert trades[0]["trading_account_id"] == paper.id
    assert trades[0]["is_paper"] is True
