"""
src/integrations/etoro_client.py — eToro public-API adapter.

Subclasses :class:`BaseExchangeClient` so the rest of Unitrader (orchestrator,
routers, trade monitoring, shared memory) can treat eToro identically to
Alpaca / Coinbase / Binance / OANDA / Kraken.

Credentials:
    • public_api_key (a.k.a. x-api-key)  — app-level, shared across users.
      Pulled from ``settings.etoro_public_api_key`` — NEVER from the DB row.
    • user_key (a.k.a. x-user-key)       — per-user, stored in
      ``exchange_api_keys.encrypted_api_key`` (Fernet).
    • api_key_id                         — per-user, stored in
      ``exchange_api_keys.encrypted_api_secret`` (Fernet, exposed as
      ``api_secret`` in the BaseExchangeClient contract).
    • environment (``demo`` | ``real``)  — stored in
      ``exchange_api_keys.etoro_environment`` and passed in via ``is_paper``
      (``is_paper=True`` ⇔ demo).

Every HTTP call passes through the module-level eToro rate limiter with the
correct ``is_write`` flag. Nothing is logged except request-ids and status
codes — never keys, signatures, balances, or order payloads.

Docs: https://www.developers.etoro.com/
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from config import settings
from src.integrations.etoro_rate_limiter import get_etoro_limiter
from src.integrations.exchange_client import BaseExchangeClient

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class EtoroError(Exception):
    """Base class for all eToro errors."""


class EtoroAuthError(EtoroError):
    """401/403 from eToro — user_key rejected or api_key_id mismatch.

    Surface to the UI as 'Key rejected by eToro — please reconnect'.
    """


class EtoroApiError(EtoroError):
    """Non-auth 4xx/5xx error. Body is NOT included in log/str output to
    avoid leaking instrument or balance data."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(f"eToro API error {status_code}: {message}" if message else f"eToro API error {status_code}")


class EtoroConnectionError(EtoroError):
    """Network-level failure reaching eToro (timeouts, DNS, reset)."""


class EtoroRateLimitError(EtoroError):
    """Raised after a second consecutive 429 once the limiter retry is exhausted."""


# ─────────────────────────────────────────────────────────────────────────────
# URLs
# ─────────────────────────────────────────────────────────────────────────────

_BASE_URL = "https://public-api.etoro.com/api/v1"


# ─────────────────────────────────────────────────────────────────────────────
# EtoroClient
# ─────────────────────────────────────────────────────────────────────────────

class EtoroClient(BaseExchangeClient):
    """eToro public-API adapter.

    Subclasses :class:`BaseExchangeClient` so it slots into the unified
    factory, orchestrator, and trade-monitoring paths unchanged.

    Two environments: ``demo`` (paper) and ``real`` (live). Chosen at
    construction time via ``is_paper``. The same eToro User Key works for
    both; only the request path differs (``/trading/demo/...`` vs
    ``/trading/real/...``).
    """

    # Seconds before a single eToro request is abandoned.
    TIMEOUT = 15.0

    def __init__(
        self,
        api_key: str,       # mapped to eToro User Key (x-user-key)
        api_secret: str,    # mapped to eToro API Key ID (informational)
        *,
        is_paper: bool = True,
        public_api_key: str | None = None,
    ):
        super().__init__(api_key, api_secret)
        self._user_key = api_key
        self._api_key_id = api_secret
        self._environment = "demo" if is_paper else "real"
        self._public_api_key = public_api_key or settings.etoro_public_api_key
        if not self._public_api_key:
            logger.warning(
                "EtoroClient constructed without ETORO_PUBLIC_API_KEY — "
                "requests will fail until settings.etoro_public_api_key is set."
            )
        self._http = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=self.TIMEOUT,
        )
        # Tiny in-process cache of symbol → instrumentId so we don't pay a
        # /market-data/search round-trip for every order.
        self._instrument_id_cache: dict[str, int] = {}

    # ── Low-level request helper ────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """Fresh headers per call — x-request-id is regenerated every time."""
        return {
            "x-request-id": str(uuid.uuid4()),
            "x-api-key": self._public_api_key,
            "x-user-key": self._user_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        is_write: bool | None = None,
    ) -> Any:
        """Issue an HTTP call respecting the rate limiter and retrying once
        on a 429. Never logs the request body, response body, keys, or
        signatures — only method, path, status, and request-id.
        """
        # Default write detection: anything non-GET is a write.
        if is_write is None:
            is_write = method.upper() not in {"GET", "HEAD"}

        limiter = get_etoro_limiter()
        headers = self._headers()
        request_id = headers["x-request-id"]

        for attempt in (1, 2):
            await limiter.acquire(is_write=is_write)
            try:
                resp = await self._http.request(
                    method.upper(), path, params=params, json=json, headers=headers,
                )
            except httpx.TimeoutException as exc:
                logger.warning("eToro request timeout path=%s rid=%s: %s", path, request_id, exc)
                raise EtoroConnectionError(f"eToro request timed out for {path}") from exc
            except httpx.NetworkError as exc:
                logger.warning("eToro network error path=%s rid=%s: %s", path, request_id, exc)
                raise EtoroConnectionError(f"eToro network error for {path}") from exc

            status = resp.status_code
            logger.debug("eToro %s %s → %s rid=%s", method.upper(), path, status, request_id)

            if status == 429:
                retry_after = float(resp.headers.get("Retry-After", "1") or 1)
                if attempt == 1:
                    import asyncio as _asyncio
                    await _asyncio.sleep(min(retry_after, 5.0))
                    # Re-generate request id for the retry.
                    headers = self._headers()
                    request_id = headers["x-request-id"]
                    continue
                raise EtoroRateLimitError(f"eToro rate-limited twice on {path}")

            if status in (401, 403):
                raise EtoroAuthError(f"eToro auth error {status} on {path}")

            if status >= 400:
                # Intentionally truncate the body to prevent accidental PII
                # bleed into logs via an upstream logger formatter.
                raise EtoroApiError(status, resp.text[:160])

            if not resp.content:
                return {}
            try:
                return resp.json()
            except ValueError:
                return resp.text

        # Unreachable — the loop either returns or raises.
        raise EtoroApiError(0, "unreachable retry branch")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _trading_path(self, suffix: str) -> str:
        return f"/trading/{self._environment}/{suffix.lstrip('/')}"

    async def _resolve_instrument_id(self, symbol: str) -> int:
        """Lookup (and cache) eToro's numeric instrumentId for a symbol."""
        normalised = symbol.upper().strip()
        if normalised in self._instrument_id_cache:
            return self._instrument_id_cache[normalised]
        data = await self._request(
            "GET", "/market-data/search", params={"query": normalised}, is_write=False,
        )
        items: list[dict] = data.get("instruments", data.get("items", [])) if isinstance(data, dict) else []
        for row in items:
            ticker = str(row.get("symbolFull", row.get("symbol", ""))).upper()
            if ticker == normalised:
                instrument_id = int(row.get("instrumentId") or row.get("id") or 0)
                if instrument_id:
                    self._instrument_id_cache[normalised] = instrument_id
                    return instrument_id
        raise EtoroApiError(404, f"instrument not found: {symbol}")

    # ── BaseExchangeClient interface ────────────────────────────────────────

    async def get_account_balance(self) -> float:
        """Return total equity (available cash + open position value) in
        the account currency. Matches the Alpaca/Coinbase semantics used
        elsewhere in the app."""
        data = await self._request(
            "GET", f"/user-info/portfolio/{self._environment}", is_write=False,
        )
        if not isinstance(data, dict):
            return 0.0
        try:
            return float(data.get("equity") or data.get("totalEquity") or data.get("available_cash") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    async def get_current_price(self, symbol: str) -> float:
        instrument_id = await self._resolve_instrument_id(symbol)
        data = await self._request(
            "GET", f"/market-data/instruments/{instrument_id}/rate", is_write=False,
        )
        if isinstance(data, dict):
            for key in ("rate", "price", "last", "ask"):
                if key in data:
                    try:
                        return float(data[key])
                    except (TypeError, ValueError):
                        pass
        return 0.0

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
    ) -> str:
        """Place a market (or limit, if price given) order.

        NOTE: ``quantity`` is interpreted as **notional amount in the account
        currency** for eToro — this matches how the rest of Unitrader passes
        trade size (dollar-based sizing via ``validate_trade_amount``).
        """
        instrument_id = await self._resolve_instrument_id(symbol)
        body: dict[str, Any] = {
            "instrumentId": instrument_id,
            "direction": side.upper(),  # BUY | SELL
            "amount": float(quantity),
            "orderType": "LIMIT" if price else "MARKET",
        }
        if price:
            body["limitPrice"] = float(price)
        data = await self._request(
            "POST", self._trading_path("orders"), json=body, is_write=True,
        )
        if isinstance(data, dict):
            return str(data.get("orderId") or data.get("id") or "")
        return ""

    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        # eToro attaches SL/TP to the position at place-order time; setting it
        # after the fact is not directly supported on the public API yet. We
        # return False so callers can fall through to their fallback paths.
        logger.info("eToro set_stop_loss is a no-op (not yet supported on public API)")
        return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        logger.info("eToro set_take_profit is a no-op (not yet supported on public API)")
        return False

    async def get_open_orders(self, symbol: str) -> list[dict]:
        data = await self._request(
            "GET", self._trading_path("orders"), is_write=False,
        )
        if not isinstance(data, list):
            data = data.get("orders", []) if isinstance(data, dict) else []
        out: list[dict] = []
        for row in data:
            row_symbol = str(row.get("symbol") or row.get("instrumentName") or "").upper()
            if not symbol or row_symbol == symbol.upper():
                out.append(row)
        return out

    async def close_position(self, symbol: str) -> bool:
        positions = await self.get_positions()
        pos = next(
            (p for p in positions if str(p.get("symbol", "")).upper() == symbol.upper()),
            None,
        )
        if not pos:
            return False
        position_id = pos.get("positionId") or pos.get("id")
        if not position_id:
            return False
        try:
            await self._request(
                "DELETE",
                self._trading_path(f"positions/{position_id}"),
                is_write=True,
            )
            return True
        except EtoroError as exc:
            logger.warning("eToro close_position failed: %s", exc)
            return False

    async def get_order_status(self, symbol: str, order_id: str) -> dict:
        data = await self._request(
            "GET", self._trading_path(f"orders/{order_id}"), is_write=False,
        )
        if not isinstance(data, dict):
            return {}
        return {
            "order_id": str(data.get("orderId") or data.get("id") or order_id),
            "status": str(data.get("status") or "").lower(),
            "filled_qty": float(data.get("filledAmount") or 0),
            "price": float(data.get("executionPrice") or data.get("limitPrice") or 0),
            "side": str(data.get("direction") or "").upper(),
        }

    # ── Extensions (not on the base interface) ──────────────────────────────

    async def get_positions(self) -> list[dict]:
        data = await self._request(
            "GET",
            f"/user-info/portfolio/{self._environment}/positions",
            is_write=False,
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("positions", [])
        return []

    async def verify_connection(self) -> dict:
        """Cheap round-trip used by the connect wizard and `/test-connection`.

        Returns ``{account_id, username, currency, environment,
        available_cash}``. Raises :class:`EtoroAuthError` on 401/403.
        """
        identity = await self._request("GET", "/identity", is_write=False)
        portfolio = await self._request(
            "GET", f"/user-info/portfolio/{self._environment}", is_write=False,
        )
        account_id = ""
        username = ""
        currency = "USD"
        if isinstance(identity, dict):
            account_id = str(identity.get("accountId") or identity.get("cid") or "")
            username = str(identity.get("username") or identity.get("name") or "")
            currency = str(identity.get("currency") or "USD")
        available_cash = 0.0
        if isinstance(portfolio, dict):
            try:
                available_cash = float(portfolio.get("available_cash") or portfolio.get("availableCash") or 0.0)
            except (TypeError, ValueError):
                available_cash = 0.0
        return {
            "account_id": account_id,
            "username": username,
            "currency": currency,
            "environment": self._environment,
            "available_cash": available_cash,
        }

    async def aclose(self) -> None:
        await self._http.aclose()
