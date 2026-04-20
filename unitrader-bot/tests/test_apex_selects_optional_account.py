import pytest


@pytest.mark.asyncio
async def test_apex_selects_no_trading_account_id_returns_empty():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient
    from main import app
    from database import get_db
    from routers.auth import get_current_user

    mock_user = SimpleNamespace(id="user-001")

    # No settings row → endpoint should still return empty success (not 422/400).
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
    )

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/signals/apex-selects")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["signals"] == []


@pytest.mark.asyncio
async def test_apex_selects_invalid_trading_account_id_returns_empty():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient
    from main import app
    from database import get_db
    from routers.auth import get_current_user

    mock_user = SimpleNamespace(id="user-001")
    mock_session = AsyncMock()

    # Provide a settings row so we hit resolve_market_context with a bad ID.
    settings_row = SimpleNamespace(
        preferred_trading_account_id="bad-acct",
        guided_confidence_threshold=70,
        apex_selects_max_trades=2,
        apex_selects_asset_classes=["stocks", "crypto"],
        watchlist=[],
    )
    mock_session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: settings_row)
    )

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_session

    async def _raise_404(*_args, **_kwargs):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail={"code": "trading_account_not_found"})

    try:
        with patch("routers.signals.resolve_market_context", new=_raise_404):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/signals/apex-selects")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["signals"] == []

