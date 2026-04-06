import pytest


@pytest.mark.asyncio
async def test_account_balances_endpoint_falls_back_to_last_known_balance():
    """GET /api/trading/account-balances returns cached balance when live fetch fails."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient
    from main import app
    from database import get_db
    from routers.auth import get_current_user

    # Minimal objects with the fields accessed by the endpoint
    mock_user = SimpleNamespace(id="user-001")

    key = SimpleNamespace(
        user_id="user-001",
        is_active=True,
        is_paper=True,
        exchange="binance",
        trading_account_id="acct-001",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
        last_used_at=None,
        encrypted_api_key="enc",
        encrypted_api_secret="enc",
    )
    acct = SimpleNamespace(
        id="acct-001",
        account_label="Binance Paper",
        last_known_balance_usd=250.0,
        last_balance_synced_at=datetime.now(timezone.utc) - timedelta(minutes=12),
        last_synced_at=None,
    )

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: [(key, acct)]))
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_session

    class _FailClient:
        async def get_account_balance(self) -> float:
            raise Exception("boom")

        async def aclose(self) -> None:
            return None

    try:
        with patch("routers.trading.decrypt_api_key", return_value=("k", "s")):
            with patch("routers.trading.get_exchange_client", return_value=_FailClient()):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/trading/account-balances")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "success"
    items = payload["data"]
    assert len(items) == 1
    assert items[0]["balance"] == 250.0
    assert "cached" in (items[0].get("balance_note") or "").lower()


@pytest.mark.asyncio
async def test_sharedmemory_trading_accounts_snapshot_falls_back_to_last_known():
    """SharedMemory snapshot uses last-known trading_accounts when live fetch fails."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from src.agents.shared_memory import SharedMemory

    key = SimpleNamespace(
        exchange="binance",
        is_paper=True,
        encrypted_api_key="enc",
        encrypted_api_secret="enc",
        id="key-1",
        trading_account_id="acct-001",
    )
    acct = SimpleNamespace(
        last_known_balance_usd=123.0,
        last_balance_synced_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        last_synced_at=None,
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: [(key, acct)]))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    class _FailClient:
        async def get_account_balance(self) -> float:
            raise Exception("boom")

        async def aclose(self) -> None:
            return None

    with patch("src.agents.shared_memory.decrypt_api_key", return_value=("k", "s")):
        with patch("src.agents.shared_memory.get_exchange_client", return_value=_FailClient()):
            out = await SharedMemory._fetch_trading_accounts_snapshot("user-001", db)  # noqa: SLF001

    assert isinstance(out, list)
    assert out and out[0]["balance_usd"] == 123.0
    assert "cached" in (out[0].get("balance_note") or "").lower()

