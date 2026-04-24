"""Endpoint-level regression tests for POST /api/trading/exchange-keys.

Model-level schema tests live in tests/test_trading.py
(TestConnectExchangeRequest). These tests go through FastAPI's
TestClient so we verify the full request path: 422 envelope shape,
`loc` field preservation, and that the eToro branch actually runs the
route body (not just schema validation).

The eToro cases cover the production regression where api_secret was
required non-empty and the wizard legitimately sent "" for eToro.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ──────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────

def _install_overrides():
    """Wire auth + db overrides for the FastAPI app.

    Returns the monkeypatched app so the caller can clear overrides.
    """
    from main import app
    from database import get_db
    from routers.auth import get_current_user

    mock_user = SimpleNamespace(id="user-test-001")

    # The connect path does:
    #   db.execute(select(ExchangeAPIKey)...) -> scalar_one_or_none()
    #   db.add(new_key); await db.commit(); await db.refresh(new_key)
    # We patch the route's _ensure_trading_account + encrypt/hash
    # helpers so the only db touchpoints left are the existing-key
    # lookup, add, commit, refresh — all no-ops on this mock session.
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
    )
    mock_session.add = lambda obj: None
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.refresh = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_session

    return app


def _patches_for_successful_connect():
    """Return a list of `patch(...)` context managers for a happy-path connect.

    Callers enter them with ExitStack. The patches cover:
    - _validate_exchange_keys (no real HTTP to exchanges)
    - _ensure_trading_account (returns a stub account)
    - _sync_preferred_trading_account_if_stale (no-op)
    - encrypt_api_key, hash_api_key (deterministic no-op)
    - check_etoro_connect_allowed (always allow; Trust-Ladder tested elsewhere)
    - SharedMemory.load (minimal stub with trust_ladder_stage)
    """
    stub_account = SimpleNamespace(id="acct-xyz", account_label="Etoro Demo")

    return [
        patch(
            "routers.trading._validate_exchange_keys",
            new=AsyncMock(return_value=1234.56),
        ),
        patch(
            "routers.trading._ensure_trading_account",
            new=AsyncMock(return_value=stub_account),
        ),
        patch(
            "routers.trading._sync_preferred_trading_account_if_stale",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "routers.trading.encrypt_api_key",
            return_value=("enc-k", "enc-s"),
        ),
        patch("routers.trading.hash_api_key", return_value="hash-abc"),
        patch(
            "src.services.etoro_trust_ladder.check_etoro_connect_allowed",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.agents.shared_memory.SharedMemory.load",
            new=AsyncMock(
                return_value=SimpleNamespace(trust_ladder_stage=3)
            ),
        ),
    ]


# ──────────────────────────────────────────────────────────────────────
# 422 shape preservation — the production regression
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alpaca_missing_secret_returns_422_with_api_secret_field():
    """Non-eToro exchanges with empty api_secret must 422 with field='body.api_secret'.

    main.py installs a custom RequestValidationError handler that
    flattens loc to a dot-joined `field` string and emits a log line
    `fields=['body.api_secret']`. Our ops playbook and Sentry grouping
    both key on that string. If this test starts reporting field='body'
    instead, someone swapped field_validator for model_validator on
    ConnectExchangeRequest.api_secret — revert it.
    """
    app = _install_overrides()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/trading/exchange-keys",
                json={
                    "exchange": "alpaca",
                    "api_key": "PK12345",
                    "api_secret": "",
                    "is_paper": True,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    body = resp.json()
    # Custom 422 envelope: {"status": "error", "error": "...", "details": [...]}
    details = body.get("details", [])
    api_secret_errors = [e for e in details if e.get("field") == "body.api_secret"]
    assert api_secret_errors, (
        f"Expected 422 error with field='body.api_secret', got {details}"
    )


# ──────────────────────────────────────────────────────────────────────
# eToro happy paths — the three branches that used to never run
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_etoro_accepts_empty_secret_and_returns_200():
    """eToro connect with api_secret='' and environment='demo' → 200, is_paper=True."""
    app = _install_overrides()
    patches = _patches_for_successful_connect()
    try:
        for p in patches:
            p.start()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/trading/exchange-keys",
                json={
                    "exchange": "etoro",
                    "api_key": "user-key-abc",
                    "api_secret": "",
                    "is_paper": True,
                    "etoro_environment": "demo",
                },
            )
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["exchange"] == "etoro"
    assert data["is_paper"] is True


@pytest.mark.asyncio
async def test_etoro_real_environment_sets_is_paper_false():
    """eToro connect with environment='real' → is_paper derived to False."""
    app = _install_overrides()
    patches = _patches_for_successful_connect()
    try:
        for p in patches:
            p.start()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/trading/exchange-keys",
                json={
                    "exchange": "etoro",
                    "api_key": "user-key-abc",
                    "api_secret": "",
                    "is_paper": False,
                    "etoro_environment": "real",
                },
            )
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["is_paper"] is False


@pytest.mark.asyncio
async def test_etoro_environment_overrides_is_paper_body_flag():
    """When body is_paper=True contradicts environment='real', environment wins.

    Route contract: etoro_environment is the source of truth; is_paper
    is derived. This pins the precedence so a future refactor can't
    silently flip it.
    """
    app = _install_overrides()
    patches = _patches_for_successful_connect()
    try:
        for p in patches:
            p.start()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/trading/exchange-keys",
                json={
                    "exchange": "etoro",
                    "api_key": "user-key-abc",
                    "api_secret": "",
                    # Deliberately contradictory — environment must win.
                    "is_paper": True,
                    "etoro_environment": "real",
                },
            )
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["is_paper"] is False
