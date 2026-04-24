"""
tests/test_etoro_client.py — MVP-B scope tests for the rewritten
EtoroClient endpoints.

Covers the five read paths against their real eToro URLs + regression
guards:

    1.  verify_connection hits /watchlists (not /identity)
    2.  verify_connection 401 -> EtoroAuthError
    3.  _resolve_instrument_id uses internalSymbolFull + fields
    4.  portfolio path: /trading/info/demo/portfolio vs /trading/info/portfolio
    5.  get_account_balance reads Credit
    6.  get_current_price uses the batch /instruments/rates endpoint
    7.  404 surfaces as EtoroApiError, not EtoroAuthError (regression)
    8.  All four write methods raise NotImplementedError (lock-in)

The tests are self-contained: they swap ``EtoroClient._http`` with an
``httpx.AsyncClient`` backed by ``httpx.MockTransport`` so no real
network calls are made.
"""

from __future__ import annotations

from typing import Callable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from src.integrations.etoro_client import (
    EtoroApiError,
    EtoroAuthError,
    EtoroClient,
)


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    is_paper: bool = True,
) -> EtoroClient:
    """Build an EtoroClient whose HTTP transport is a MockTransport."""
    client = EtoroClient(
        api_key="test-user-key",
        api_secret="test-api-key-id",
        is_paper=is_paper,
        public_api_key="test-public-key",
    )
    transport = httpx.MockTransport(handler)
    client._http = httpx.AsyncClient(
        base_url="https://public-api.etoro.com/api/v1",
        timeout=5.0,
        transport=transport,
    )
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Read-path tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_connection_hits_watchlists():
    """verify_connection must hit /watchlists (not /identity) for auth."""
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path.endswith("/watchlists"):
            return httpx.Response(200, json={"watchlists": []})
        if "portfolio" in request.url.path:
            return httpx.Response(200, json={"Credit": 1234.56, "CID": "42"})
        return httpx.Response(404, json={"errorCode": "RouteNotFound"})

    client = _make_client(handler, is_paper=True)
    result = await client.verify_connection()

    assert any(p.endswith("/watchlists") for p in seen_paths), (
        f"verify_connection must call /watchlists, got: {seen_paths}"
    )
    assert not any(p.endswith("/identity") for p in seen_paths), (
        f"verify_connection must NOT call /identity (fictional), got: {seen_paths}"
    )
    assert result["available_cash"] == pytest.approx(1234.56)
    assert result["account_id"] == "42"
    assert result["environment"] == "demo"


@pytest.mark.asyncio
async def test_verify_connection_auth_failure():
    """401 on /watchlists must raise EtoroAuthError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errorCode": "Unauthorized"})

    client = _make_client(handler)
    with pytest.raises(EtoroAuthError):
        await client.verify_connection()


@pytest.mark.asyncio
async def test_resolve_instrument_id_uses_internal_symbol_full():
    """_resolve_instrument_id must use internalSymbolFull + fields, not query."""
    seen_queries: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = parse_qs(urlparse(str(request.url)).query)
        seen_queries.append({k: v[0] for k, v in q.items()})
        return httpx.Response(
            200,
            json={
                "instruments": [
                    {
                        "instrumentId": 100000,
                        "internalSymbolFull": "AAPL",
                        "displayname": "Apple Inc.",
                    }
                ]
            },
        )

    client = _make_client(handler)
    iid = await client._resolve_instrument_id("AAPL")
    assert iid == 100000

    assert seen_queries, "no request was made"
    q = seen_queries[0]
    assert q.get("internalSymbolFull") == "AAPL", (
        f"must filter by internalSymbolFull, got: {q}"
    )
    assert "fields" in q and "instrumentId" in q["fields"], (
        f"fields param required by eToro, got: {q}"
    )
    assert "query" not in q, (
        f"the old `query` param is fictional and must not be sent, got: {q}"
    )


@pytest.mark.asyncio
async def test_portfolio_demo_vs_real_path():
    """demo keeps /demo/ in path, real omits env segment entirely."""
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"Credit": 0})

    demo_client = _make_client(handler, is_paper=True)
    await demo_client.get_account_balance()
    assert any(p.endswith("/trading/info/demo/portfolio") for p in seen_paths), (
        f"demo must hit /trading/info/demo/portfolio, got: {seen_paths}"
    )

    seen_paths.clear()
    real_client = _make_client(handler, is_paper=False)
    await real_client.get_account_balance()
    assert any(p.endswith("/trading/info/portfolio") for p in seen_paths), (
        f"real must hit /trading/info/portfolio (no env segment), got: {seen_paths}"
    )
    assert not any("/real/" in p for p in seen_paths), (
        f"real must NOT include /real/ in the URL, got: {seen_paths}"
    )


@pytest.mark.asyncio
async def test_get_account_balance_reads_credit():
    """get_account_balance reads the PascalCase ``Credit`` field."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Credit": 12345.67, "Positions": []})

    client = _make_client(handler)
    balance = await client.get_account_balance()
    assert balance == pytest.approx(12345.67)


@pytest.mark.asyncio
async def test_get_current_price_uses_rates_endpoint():
    """get_current_price must use batch /instruments/rates, not /{id}/rate."""
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        path = request.url.path
        if path.endswith("/market-data/search"):
            return httpx.Response(
                200,
                json={
                    "instruments": [
                        {"instrumentId": 77, "internalSymbolFull": "AAPL"}
                    ]
                },
            )
        if path.endswith("/market-data/instruments/rates"):
            return httpx.Response(
                200,
                json={"rates": [{"instrumentId": 77, "last": 192.34}]},
            )
        return httpx.Response(404)

    client = _make_client(handler)
    price = await client.get_current_price("AAPL")
    assert price == pytest.approx(192.34)

    assert any("/market-data/instruments/rates" in u for u in seen_urls), (
        f"must hit batch rates endpoint, got: {seen_urls}"
    )
    assert not any("/market-data/instruments/77/rate" in u for u in seen_urls), (
        f"must NOT hit the fictional /instruments/{{id}}/rate endpoint, got: {seen_urls}"
    )
    rates_calls = [u for u in seen_urls if "/instruments/rates" in u]
    assert any("instrumentIds=77" in u for u in rates_calls), (
        f"rates call must include instrumentIds=77 query, got: {rates_calls}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Regression guards
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_404_raises_etoro_api_error_not_auth_error():
    """Regression guard for the original bug: 404 RouteNotFound was being
    mis-classified as a credential failure. 404 must surface as
    EtoroApiError so callers can distinguish "wrong URL" from "wrong key"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"errorCode": "RouteNotFound", "errorMessage": "Route not found"},
        )

    client = _make_client(handler)
    with pytest.raises(EtoroApiError) as excinfo:
        await client.verify_connection()
    assert excinfo.value.status_code == 404
    assert not isinstance(excinfo.value, EtoroAuthError), (
        "404 must NOT be classified as EtoroAuthError — that was the original bug."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name,args",
    [
        ("place_order", ("AAPL", "BUY", 100.0)),
        ("close_position", ("AAPL",)),
        ("get_open_orders", ("AAPL",)),
        ("get_order_status", ("AAPL", "order-123")),
    ],
)
async def test_write_methods_raise_not_implemented(method_name, args):
    """MVP-B lock-in: the four write methods must raise NotImplementedError.

    If this test starts failing, either:
      (a) the write path has been implemented — great, expand to cover
          real behaviour and remove this guard, OR
      (b) the method has been accidentally re-wired to an old stub. In
          case (b), do NOT weaken this test — fix the method.
    """
    client = _make_client(lambda req: httpx.Response(500))
    method = getattr(client, method_name)
    with pytest.raises(NotImplementedError):
        await method(*args)


# ─────────────────────────────────────────────────────────────────────────────
# Router-layer belt-and-braces (MVP-B)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_returns_501_for_etoro():
    """POST /api/trading/execute must 501 for exchange=='etoro' during MVP-B.

    This is the defence-in-depth layer guarding against any code path that
    reaches the client stubs. Tests the guard as a narrow unit; the full
    HTTP stack is not exercised here.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import HTTPException

    from routers.trading import execute_trade

    # Minimal request body — only `exchange` matters for this assertion.
    body = SimpleNamespace(
        symbol="AAPL",
        exchange="etoro",
        trading_account_id=None,
        is_paper=True,
    )

    # Mock: user, db, trade-limit check. The guard fires BEFORE any
    # TradingAgent code runs, so we only need to get past the onboarding
    # gate and the trade-limit gate.
    mock_user = SimpleNamespace(id="user-under-test")
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # no UserSettings row
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch(
        "routers.trading.check_trade_limit",
        new=AsyncMock(return_value={"allowed": True}),
    ):
        with pytest.raises(HTTPException) as excinfo:
            await execute_trade(body=body, current_user=mock_user, db=mock_db)

    assert excinfo.value.status_code == 501, (
        f"eToro /execute must return 501, got {excinfo.value.status_code}"
    )
    detail = excinfo.value.detail
    assert isinstance(detail, dict), f"detail must be a dict, got: {detail!r}"
    assert detail.get("code") == "etoro_trade_execution_pending", (
        f"missing sentinel code in detail: {detail!r}"
    )
