import pytest


@pytest.mark.asyncio
async def test_chat_bootstrap_not_connected():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient
    from main import app
    from database import get_db
    from routers.auth import get_current_user
    from src.agents.shared_memory import SharedContext

    mock_user = SimpleNamespace(id="user-001", email="u@example.com")
    mock_session = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        ctx = SharedContext.default("user-001")
        ctx.ai_name = "Zeus"
        ctx.trading_accounts = []
        with patch(
            "src.agents.shared_memory.SharedMemory.load",
            new=AsyncMock(return_value=ctx),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/chat/bootstrap")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["data"]["ai_name"] == "Zeus"
    assert data["data"]["has_exchange_connected"] is False


@pytest.mark.asyncio
async def test_chat_bootstrap_connected():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient
    from main import app
    from database import get_db
    from routers.auth import get_current_user
    from src.agents.shared_memory import SharedContext

    mock_user = SimpleNamespace(id="user-002", email="u2@example.com")
    mock_session = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        ctx = SharedContext.default("user-002")
        ctx.ai_name = "Apex"
        ctx.trading_accounts = [{"exchange": "binance", "is_paper": True, "balance_usd": 123.45}]
        with patch(
            "src.agents.shared_memory.SharedMemory.load",
            new=AsyncMock(return_value=ctx),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/chat/bootstrap")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["data"]["has_exchange_connected"] is True
    assert "binance" in data["data"]["connected_exchanges"]

