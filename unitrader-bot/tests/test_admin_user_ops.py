"""
tests/test_admin_user_ops.py — Phase 13 backoffice endpoints.

Covers panic-stop, exchange-key revoke, support notes, and verification
that the existing PATCH + DELETE endpoints behave correctly.

The global `create_tables()` helper currently fails on SQLite because an
unrelated legacy table uses a PG-only UUID column. We therefore create
only the tables these tests need, mirroring the Phase-12 test pattern.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, select

from config import settings as app_settings
from database import AsyncSessionLocal, engine
from models import (
    AdminUserNote,
    ExchangeAPIKey,
    Trade,
    TradingAccount,
    User,
    UserExternalAccount,
    UserSettings,
)
from routers import admin as admin_router


# ─── Table setup ────────────────────────────────────────────────────────────

_TABLES = [
    User.__table__,
    UserSettings.__table__,
    TradingAccount.__table__,
    ExchangeAPIKey.__table__,
    Trade.__table__,
    UserExternalAccount.__table__,
    AdminUserNote.__table__,
]


async def _create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: [t.create(sync_conn, checkfirst=True) for t in _TABLES]
        )


async def _wipe_tables() -> None:
    async with AsyncSessionLocal() as db:
        # Child-first to respect FKs
        await db.execute(delete(AdminUserNote))
        await db.execute(delete(Trade))
        await db.execute(delete(ExchangeAPIKey))
        await db.execute(delete(TradingAccount))
        await db.execute(delete(UserSettings))
        await db.execute(delete(UserExternalAccount))
        await db.execute(delete(User))
        await db.commit()


# ─── Fixtures ───────────────────────────────────────────────────────────────

ADMIN_SECRET = "test-admin-secret-phase13"


@pytest_asyncio.fixture(scope="function")
async def db_clean():
    await _create_tables()
    await _wipe_tables()
    yield
    await _wipe_tables()


@pytest_asyncio.fixture
async def app_client(db_clean):
    """FastAPI app + AsyncClient wired to the admin router only."""
    # Configure admin secret on the imported settings singleton used by the router
    app_settings.admin_secret_key = ADMIN_SECRET

    app = FastAPI()
    app.include_router(admin_router.router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _make_user(email: str = "alice@example.com") -> User:
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash="x",
            ai_name="Apex",
            subscription_tier="pro",
            trial_status="active",
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        db.add(UserSettings(user_id=u.id, trading_paused=False))
        await db.commit()
        return u


async def _make_trade(user_id: str, status: str = "open") -> Trade:
    async with AsyncSessionLocal() as db:
        t = Trade(
            user_id=user_id,
            exchange="binance",
            symbol="BTC/USDT",
            side="BUY",
            quantity=0.01,
            entry_price=50_000.0,
            stop_loss=49_000.0,
            take_profit=52_000.0,
            status=status,
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)
        return t


async def _make_exchange_key(
    user_id: str, with_account: bool = True
) -> tuple[ExchangeAPIKey, TradingAccount | None]:
    async with AsyncSessionLocal() as db:
        account = None
        if with_account:
            account = TradingAccount(
                user_id=user_id,
                exchange="binance",
                is_paper=False,
                account_label="Main Live",
            )
            db.add(account)
            await db.commit()
            await db.refresh(account)

        key = ExchangeAPIKey(
            user_id=user_id,
            trading_account_id=account.id if account else None,
            exchange="binance",
            encrypted_api_key="enc-key",
            encrypted_api_secret="enc-secret",
            key_hash="hash-123",
            is_active=True,
            is_paper=False,
        )
        db.add(key)
        await db.commit()
        await db.refresh(key)
        return key, account


H_AUTH = {"X-Admin-Secret": ADMIN_SECRET, "X-Admin-Author": "test-admin"}


# ─── Tests ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_secret_required(app_client):
    u = await _make_user()
    r = await app_client.post(
        f"/api/admin/users/{u.id}/panic-stop", json={"reason": "t"}
    )
    # Missing header → FastAPI returns 422 for Header(...) required
    assert r.status_code in (401, 403, 422)


@pytest.mark.asyncio
async def test_suspend_user_sets_inactive(app_client):
    u = await _make_user()
    r = await app_client.patch(
        f"/api/admin/users/{u.id}", json={"is_active": False}, headers=H_AUTH
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    async with AsyncSessionLocal() as db:
        db_user = (await db.execute(select(User).where(User.id == u.id))).scalar_one()
        assert db_user.is_active is False


@pytest.mark.asyncio
async def test_extend_trial_updates_end_date(app_client):
    u = await _make_user()
    new_end = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    r = await app_client.patch(
        f"/api/admin/users/{u.id}",
        json={"trial_end_date": new_end, "trial_status": "active"},
        headers=H_AUTH,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trial_status"] == "active"
    assert body["trial_end_date"] is not None


@pytest.mark.asyncio
async def test_delete_user_removes_user(app_client):
    """Delete endpoint must remove the user row. FK cascade for dependents is
    enforced at the DB layer in Postgres (ON DELETE CASCADE)."""
    u = await _make_user()
    r = await app_client.delete(f"/api/admin/users/{u.id}", headers=H_AUTH)
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as db:
        assert (
            await db.execute(select(User).where(User.id == u.id))
        ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_panic_stop_closes_open_trades(app_client):
    u = await _make_user()
    t1 = await _make_trade(u.id, status="open")
    t2 = await _make_trade(u.id, status="open")

    r = await app_client.post(
        f"/api/admin/users/{u.id}/panic-stop",
        json={"reason": "fraud investigation"},
        headers=H_AUTH,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["closed"] == 2
    assert body["paused"] is True

    async with AsyncSessionLocal() as db:
        for tid in (t1.id, t2.id):
            tr = (await db.execute(select(Trade).where(Trade.id == tid))).scalar_one()
            assert tr.status == "closed"
            assert tr.closed_at is not None
        settings = (
            await db.execute(select(UserSettings).where(UserSettings.user_id == u.id))
        ).scalar_one()
        assert settings.trading_paused is True


@pytest.mark.asyncio
async def test_panic_stop_ignores_closed_trades(app_client):
    u = await _make_user()
    closed_trade = await _make_trade(u.id, status="closed")

    r = await app_client.post(
        f"/api/admin/users/{u.id}/panic-stop",
        json={"reason": "routine"},
        headers=H_AUTH,
    )
    assert r.status_code == 200
    assert r.json()["closed"] == 0

    async with AsyncSessionLocal() as db:
        tr = (
            await db.execute(select(Trade).where(Trade.id == closed_trade.id))
        ).scalar_one()
        assert tr.status == "closed"


@pytest.mark.asyncio
async def test_panic_stop_creates_audit_note(app_client):
    u = await _make_user()
    await _make_trade(u.id)
    await app_client.post(
        f"/api/admin/users/{u.id}/panic-stop",
        json={"reason": "chargeback"},
        headers=H_AUTH,
    )

    async with AsyncSessionLocal() as db:
        notes = (
            await db.execute(select(AdminUserNote).where(AdminUserNote.user_id == u.id))
        ).scalars().all()
        assert len(notes) == 1
        assert "PANIC STOP" in notes[0].body
        assert "chargeback" in notes[0].body
        assert notes[0].author == "test-admin"


@pytest.mark.asyncio
async def test_revoke_key_soft_disables(app_client):
    u = await _make_user()
    key, _ = await _make_exchange_key(u.id, with_account=False)

    r = await app_client.post(
        f"/api/admin/users/{u.id}/exchange-keys/{key.id}/revoke",
        json={"reason": "key leak"},
        headers=H_AUTH,
    )
    assert r.status_code == 200, r.text
    assert r.json()["revoked"] is True

    async with AsyncSessionLocal() as db:
        db_key = (
            await db.execute(select(ExchangeAPIKey).where(ExchangeAPIKey.id == key.id))
        ).scalar_one()
        assert db_key.is_active is False
        # Encrypted blob preserved for forensics
        assert db_key.encrypted_api_key == "enc-key"
        assert db_key.encrypted_api_secret == "enc-secret"


@pytest.mark.asyncio
async def test_revoke_key_disables_linked_account(app_client):
    u = await _make_user()
    key, account = await _make_exchange_key(u.id, with_account=True)
    assert account is not None

    r = await app_client.post(
        f"/api/admin/users/{u.id}/exchange-keys/{key.id}/revoke",
        json={"reason": "user request"},
        headers=H_AUTH,
    )
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        db_account = (
            await db.execute(
                select(TradingAccount).where(TradingAccount.id == account.id)
            )
        ).scalar_one()
        assert db_account.is_active is False


@pytest.mark.asyncio
async def test_add_note_and_list(app_client):
    u = await _make_user()

    r1 = await app_client.post(
        f"/api/admin/users/{u.id}/notes",
        json={"body": "First contact — offered extension"},
        headers=H_AUTH,
    )
    assert r1.status_code == 200, r1.text

    # Ensure ordering differs
    await asyncio.sleep(0.01)

    r2 = await app_client.post(
        f"/api/admin/users/{u.id}/notes",
        json={"body": "Second note"},
        headers=H_AUTH,
    )
    assert r2.status_code == 200

    r = await app_client.get(f"/api/admin/users/{u.id}/notes", headers=H_AUTH)
    assert r.status_code == 200
    notes = r.json()
    assert len(notes) == 2
    # Newest first
    assert notes[0]["body"] == "Second note"
    assert notes[1]["body"] == "First contact — offered extension"
    assert all(n["author"] == "test-admin" for n in notes)


@pytest.mark.asyncio
async def test_add_note_rejects_empty_body(app_client):
    u = await _make_user()
    r = await app_client.post(
        f"/api/admin/users/{u.id}/notes", json={"body": "   "}, headers=H_AUTH
    )
    assert r.status_code == 400
