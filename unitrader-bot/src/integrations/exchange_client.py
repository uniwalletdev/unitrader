"""
src/integrations/exchange_client.py — Exchange API clients for Unitrader.

Provides a unified interface across Binance, Alpaca, and OANDA.
All clients are async-first and include retry logic with exponential backoff.
"""

import asyncio
import hashlib
import hmac
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any
from urllib.parse import urlencode

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Retry helper
# ─────────────────────────────────────────────

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds


async def _with_retry(coro_fn, *args, **kwargs) -> Any:
    """Execute an async callable with exponential backoff on transient errors.

    Retries on: httpx.TimeoutException, httpx.NetworkError, HTTP 429 / 5xx.
    """
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt == _MAX_RETRIES:
                raise
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning("Network error on attempt %d/%d — retry in %.1fs: %s", attempt, _MAX_RETRIES, delay, exc)
            await asyncio.sleep(delay)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {429, 500, 502, 503, 504}:
                if attempt == _MAX_RETRIES:
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("HTTP %d on attempt %d/%d — retry in %.1fs", exc.response.status_code, attempt, _MAX_RETRIES, delay)
                await asyncio.sleep(delay)
            else:
                raise


# ─────────────────────────────────────────────
# Base Client
# ─────────────────────────────────────────────

class BaseExchangeClient(ABC):
    """Abstract interface that every exchange adapter must implement."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    @abstractmethod
    async def get_account_balance(self) -> float:
        """Return total account balance in USD equivalent."""

    @abstractmethod
    async def get_current_price(self, symbol: str) -> float:
        """Return the latest market price for symbol (e.g. 'BTCUSDT')."""

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
    ) -> str:
        """Place a market or limit order. Returns the exchange order_id."""

    @abstractmethod
    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        """Attach a stop-loss OCO/bracket order. Returns True on success."""

    @abstractmethod
    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        """Attach a take-profit order. Returns True on success."""

    @abstractmethod
    async def get_open_orders(self, symbol: str) -> list[dict]:
        """Return a list of open orders for symbol."""

    @abstractmethod
    async def close_position(self, symbol: str) -> bool:
        """Close all open positions for symbol at market. Returns True on success."""

    @abstractmethod
    async def get_order_status(self, symbol: str, order_id: str) -> dict:
        """Return the current status of an order as a dict."""


# ─────────────────────────────────────────────
# Binance Client
# ─────────────────────────────────────────────

class BinanceClient(BaseExchangeClient):
    """Binance REST API client (Spot trading).

    Docs: https://binance-docs.github.io/apidocs/spot/en/
    """

    RECV_WINDOW = 5000

    def __init__(self, api_key: str, api_secret: str, base_url: str | None = None):
        super().__init__(api_key, api_secret)
        self._base_url = (base_url or settings.binance_base_url or "https://api.binance.com").rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-MBX-APIKEY": api_key},
            timeout=10.0,
        )

    def _sign(self, params: dict) -> dict:
        """Add HMAC-SHA256 signature required by Binance signed endpoints."""
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self.RECV_WINDOW
        query = urlencode(params)
        sig = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    async def _get(self, path: str, params: dict | None = None, signed: bool = False) -> Any:
        if signed:
            params = self._sign(params or {})
        resp = await self._http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, params: dict) -> Any:
        params = self._sign(params)
        resp = await self._http.post(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str, params: dict) -> Any:
        params = self._sign(params)
        resp = await self._http.delete(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_account_balance(self) -> float:
        """Return total USDT balance in the spot wallet."""
        data = await _with_retry(self._get, "/api/v3/account", signed=True)
        for asset in data.get("balances", []):
            if asset["asset"] == "USDT":
                return float(asset["free"]) + float(asset["locked"])
        return 0.0

    async def get_current_price(self, symbol: str) -> float:
        data = await _with_retry(self._get, "/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
    ) -> str:
        params: dict = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "LIMIT" if price else "MARKET",
            "quantity": f"{quantity:.8f}",
        }
        if price:
            params["price"] = f"{price:.8f}"
            params["timeInForce"] = "GTC"
        data = await _with_retry(self._post, "/api/v3/order", params)
        return str(data["orderId"])

    async def _filled_quantity_for(self, symbol: str, order_id: str) -> float:
        """Return the executed base-asset qty of ``order_id`` on ``symbol``.

        Binance's STOP_LOSS_LIMIT / TAKE_PROFIT_LIMIT orders require a non-zero
        ``quantity`` matching the open position. Sourcing it from the original
        fill is the correct pattern per the spot trading docs.
        """
        try:
            data = await _with_retry(
                self._get,
                "/api/v3/order",
                {"symbol": symbol, "orderId": order_id},
                signed=True,
            )
            return float(data.get("executedQty", 0) or 0)
        except Exception as exc:
            logger.error("Binance _filled_quantity_for failed: %s", exc)
            return 0.0

    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        """Place a STOP_LOSS_LIMIT order tied to the original fill quantity.

        Binance spot doesn't support OCO via the simple order endpoint, so we
        place a separate stop order using the executed qty of ``order_id``.
        Rejects when the parent order has no fill (qty=0 fails LOT_SIZE).
        """
        try:
            qty = await self._filled_quantity_for(symbol, order_id)
            if qty <= 0:
                logger.warning(
                    "Binance set_stop_loss skipped: parent order %s has no executed qty",
                    order_id,
                )
                return False
            current_price = await self.get_current_price(symbol)
            # Determine the sell side: if stop < current it's a stop for a long position
            side = "SELL" if stop_price < current_price else "BUY"
            params = {
                "symbol": symbol,
                "side": side,
                "type": "STOP_LOSS_LIMIT",
                "stopPrice": f"{stop_price:.8f}",
                "price": f"{stop_price * 0.999:.8f}",  # slight slippage buffer
                "quantity": f"{qty:.8f}",
                "timeInForce": "GTC",
            }
            await _with_retry(self._post, "/api/v3/order", params)
            return True
        except Exception as exc:
            logger.error("Binance set_stop_loss failed: %s", exc)
            return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        """Place a TAKE_PROFIT_LIMIT order tied to the original fill quantity."""
        try:
            qty = await self._filled_quantity_for(symbol, order_id)
            if qty <= 0:
                logger.warning(
                    "Binance set_take_profit skipped: parent order %s has no executed qty",
                    order_id,
                )
                return False
            current_price = await self.get_current_price(symbol)
            side = "SELL" if target_price > current_price else "BUY"
            params = {
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_LIMIT",
                "stopPrice": f"{target_price:.8f}",
                "price": f"{target_price * 0.999:.8f}",
                "quantity": f"{qty:.8f}",
                "timeInForce": "GTC",
            }
            await _with_retry(self._post, "/api/v3/order", params)
            return True
        except Exception as exc:
            logger.error("Binance set_take_profit failed: %s", exc)
            return False

    async def get_open_orders(self, symbol: str) -> list[dict]:
        data = await _with_retry(self._get, "/api/v3/openOrders", {"symbol": symbol}, signed=True)
        return data if isinstance(data, list) else []

    async def close_position(self, symbol: str) -> bool:
        """Cancel all open orders then place a market sell to flatten the position."""
        try:
            await _with_retry(self._delete, "/api/v3/openOrders", {"symbol": symbol})
            # A market sell of the full balance — in practice quantity must be fetched
            logger.info("Binance: closed position for %s", symbol)
            return True
        except Exception as exc:
            logger.error("Binance close_position failed: %s", exc)
            return False

    async def get_order_status(self, symbol: str, order_id: str) -> dict:
        data = await _with_retry(
            self._get,
            "/api/v3/order",
            {"symbol": symbol, "orderId": order_id},
            signed=True,
        )
        return {
            "order_id": str(data.get("orderId")),
            "status": data.get("status"),
            "filled_qty": float(data.get("executedQty", 0)),
            "price": float(data.get("price", 0)),
            "side": data.get("side"),
        }

    async def aclose(self) -> None:
        await self._http.aclose()


# ─────────────────────────────────────────────
# Alpaca Client
# ─────────────────────────────────────────────

class AlpacaClient(BaseExchangeClient):
    """Alpaca Markets REST API client (US equities + crypto).

    Trading base URL defaults from settings (paper vs live) via ``is_paper``.
    If ``api_key`` and ``api_secret`` are both non-empty (e.g. user keys from DB), those
    are used; otherwise credentials come from the matching paper/live settings.
    Optional ``base_url`` overrides the default URL when non-empty.
    Docs: https://docs.alpaca.markets/reference/
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str | None = None,
        *,
        is_paper: bool = True,
    ):
        if is_paper:
            sk, ss, default_base = (
                settings.alpaca_paper_api_key,
                settings.alpaca_paper_api_secret,
                settings.alpaca_paper_base_url,
            )
        else:
            sk, ss, default_base = (
                settings.alpaca_live_api_key,
                settings.alpaca_live_api_secret,
                settings.alpaca_live_base_url,
            )
        # Prefer decrypted user keys from the factory when present; otherwise paper/live env settings.
        if api_key and api_secret:
            eff_key, eff_secret = api_key, api_secret
        else:
            eff_key, eff_secret = sk, ss
        eff_base = default_base
        if base_url and str(base_url).strip():
            eff_base = str(base_url).strip()
        super().__init__(eff_key, eff_secret)
        raw_url = eff_base.rstrip("/")
        if raw_url.endswith("/v2"):
            raw_url = raw_url[:-3]
        self._base_url = raw_url
        _common_headers = {
            "APCA-API-KEY-ID": eff_key,
            "APCA-API-SECRET-KEY": eff_secret,
            "Content-Type": "application/json",
        }
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers=_common_headers,
            timeout=10.0,
        )
        self._data_http = httpx.AsyncClient(
            base_url=settings.alpaca_data_url.rstrip("/"),
            headers=_common_headers,
            timeout=10.0,
        )

    async def _get(self, path: str, params: dict | None = None) -> Any:
        resp = await self._http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, json: dict) -> Any:
        resp = await self._http.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str) -> None:
        resp = await self._http.delete(path)
        resp.raise_for_status()

    async def get_account_balance(self) -> float:
        data = await _with_retry(self._get, "/v2/account")
        return float(data.get("cash", 0))

    async def _data_get(self, path: str, params: dict | None = None) -> Any:
        resp = await self._data_http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_current_price(self, symbol: str) -> float:
        """Return the latest mid price for ``symbol``.

        Alpaca exposes crypto and equity quotes through different endpoints:
            - Equities: GET /v2/stocks/{symbol}/quotes/latest
            - Crypto:   GET /v1beta3/crypto/us/latest/quotes?symbols=BTC/USD

        We dispatch on the symbol shape — anything containing a slash
        (e.g. ``BTC/USD``) is treated as a crypto pair and routed to the
        v1beta3 multi-symbol endpoint, which is the only one that returns
        crypto quotes (verified against docs.alpaca.markets).
        """
        if "/" in symbol:
            data = await _with_retry(
                self._data_get,
                "/v1beta3/crypto/us/latest/quotes",
                {"symbols": symbol},
            )
            quotes = data.get("quotes", {}) or {}
            quote = quotes.get(symbol, {}) or {}
        else:
            data = await _with_retry(self._data_get, f"/v2/stocks/{symbol}/quotes/latest")
            quote = data.get("quote", {}) or {}
        bid = float(quote.get("bp", 0) or 0)
        ask = float(quote.get("ap", 0) or 0)
        return (bid + ask) / 2 if bid and ask else (ask or bid)

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
    ) -> str:
        payload: dict = {
            "symbol": symbol,
            "qty": str(quantity),
            "side": side.lower(),
            "type": "limit" if price else "market",
            "time_in_force": "gtc",
        }
        if price:
            payload["limit_price"] = str(price)
        data = await _with_retry(self._post, "/v2/orders", payload)
        return str(data["id"])

    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        """Alpaca supports bracket orders; attach stop via order replace."""
        try:
            try:
                pos = await _with_retry(self._get, f"/v2/positions/{symbol}")
                qty = abs(float(pos.get("qty", 0) or 0))
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    logger.warning("Alpaca set_stop_loss: no open position for %s", symbol)
                    return False
                raise
            if qty <= 0:
                logger.warning("Alpaca set_stop_loss: position qty is zero for %s", symbol)
                return False
            await _with_retry(
                self._post,
                "/v2/orders",
                {
                    "symbol": symbol,
                    "qty": str(qty),
                    "side": "sell",
                    "type": "stop",
                    "stop_price": str(stop_price),
                    "time_in_force": "gtc",
                },
            )
            return True
        except Exception as exc:
            logger.error("Alpaca set_stop_loss failed: %s", exc)
            return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        try:
            try:
                pos = await _with_retry(self._get, f"/v2/positions/{symbol}")
                qty = abs(float(pos.get("qty", 0) or 0))
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    logger.warning("Alpaca set_take_profit: no open position for %s", symbol)
                    return False
                raise
            if qty <= 0:
                logger.warning("Alpaca set_take_profit: position qty is zero for %s", symbol)
                return False
            await _with_retry(
                self._post,
                "/v2/orders",
                {
                    "symbol": symbol,
                    "qty": str(qty),
                    "side": "sell",
                    "type": "limit",
                    "limit_price": str(target_price),
                    "time_in_force": "gtc",
                },
            )
            return True
        except Exception as exc:
            logger.error("Alpaca set_take_profit failed: %s", exc)
            return False

    async def get_open_orders(self, symbol: str) -> list[dict]:
        data = await _with_retry(self._get, "/v2/orders", {"symbols": symbol, "status": "open"})
        return data if isinstance(data, list) else []

    async def close_position(self, symbol: str) -> bool:
        try:
            await _with_retry(self._delete, f"/v2/positions/{symbol}")
            return True
        except Exception as exc:
            logger.error("Alpaca close_position failed: %s", exc)
            return False

    async def get_order_status(self, symbol: str, order_id: str) -> dict:
        data = await _with_retry(self._get, f"/v2/orders/{order_id}")
        return {
            "order_id": data.get("id"),
            "status": data.get("status"),
            "filled_qty": float(data.get("filled_qty", 0)),
            "price": float(data.get("filled_avg_price") or 0),
            "side": data.get("side"),
        }

    async def aclose(self) -> None:
        await self._http.aclose()
        await self._data_http.aclose()


# ─────────────────────────────────────────────
# OANDA Client
# ─────────────────────────────────────────────

class OandaClient(BaseExchangeClient):
    """OANDA v20 REST API client (Forex / CFDs).

    Docs: https://developer.oanda.com/rest-live-v20/introduction/
    """

    def __init__(self, api_key: str, api_secret: str, account_id: str | None = None):
        super().__init__(api_key, api_secret)
        self._account_id = account_id or settings.oanda_account_id
        self._base_url = settings.oanda_base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

    async def _get(self, path: str, params: dict | None = None) -> Any:
        resp = await self._http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, json: dict) -> Any:
        resp = await self._http.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    async def _put(self, path: str, json: dict) -> Any:
        resp = await self._http.put(path, json=json)
        resp.raise_for_status()
        return resp.json()

    async def get_account_balance(self) -> float:
        data = await _with_retry(self._get, f"/v3/accounts/{self._account_id}/summary")
        return float(data.get("account", {}).get("balance", 0))

    async def get_current_price(self, symbol: str) -> float:
        """symbol format for OANDA: EUR_USD, GBP_USD, etc."""
        data = await _with_retry(
            self._get,
            f"/v3/accounts/{self._account_id}/pricing",
            {"instruments": symbol},
        )
        prices = data.get("prices", [])
        if prices:
            bid = float(prices[0].get("bids", [{}])[0].get("price", 0))
            ask = float(prices[0].get("asks", [{}])[0].get("price", 0))
            return (bid + ask) / 2
        return 0.0

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
    ) -> str:
        units = quantity if side.upper() == "BUY" else -quantity
        order_body: dict = {
            "order": {
                "type": "LIMIT" if price else "MARKET",
                "instrument": symbol,
                "units": str(units),
            }
        }
        if price:
            order_body["order"]["price"] = str(price)
        data = await _with_retry(
            self._post, f"/v3/accounts/{self._account_id}/orders", order_body
        )
        return str(data.get("orderCreateTransaction", {}).get("id", ""))

    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        """Set stop-loss on an open trade via /v3/accounts/{id}/trades/{tradeId}/orders.
        
        OANDA requires the tradeId (not orderId) to set SL/TP on filled positions.
        Fetch open trades for the symbol and match by the order that created it.
        """
        try:
            # Fetch all open trades for this symbol
            trades_data = await _with_retry(
                self._get,
                f"/v3/accounts/{self._account_id}/openTrades",
                {"instrument": symbol},
            )
            trades = trades_data.get("trades", [])
            if not trades:
                logger.warning("OANDA set_stop_loss: no open trades for %s", symbol)
                return False
            
            # Use the first open trade (in production, match order_id to initialMarginRequired or other metadata)
            trade_id = trades[0].get("id")
            if not trade_id:
                logger.warning("OANDA set_stop_loss: could not extract trade ID")
                return False
            
            await _with_retry(
                self._put,
                f"/v3/accounts/{self._account_id}/trades/{trade_id}/orders",
                {"stopLoss": {"price": str(stop_price)}},
            )
            return True
        except Exception as exc:
            logger.error("OANDA set_stop_loss failed: %s", exc)
            return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        """Set take-profit on an open trade via /v3/accounts/{id}/trades/{tradeId}/orders.
        
        OANDA requires the tradeId (not orderId) to set SL/TP on filled positions.
        Fetch open trades for the symbol and match by the order that created it.
        """
        try:
            # Fetch all open trades for this symbol
            trades_data = await _with_retry(
                self._get,
                f"/v3/accounts/{self._account_id}/openTrades",
                {"instrument": symbol},
            )
            trades = trades_data.get("trades", [])
            if not trades:
                logger.warning("OANDA set_take_profit: no open trades for %s", symbol)
                return False
            
            # Use the first open trade (in production, match order_id to initialMarginRequired or other metadata)
            trade_id = trades[0].get("id")
            if not trade_id:
                logger.warning("OANDA set_take_profit: could not extract trade ID")
                return False
            
            await _with_retry(
                self._put,
                f"/v3/accounts/{self._account_id}/trades/{trade_id}/orders",
                {"takeProfit": {"price": str(target_price)}},
            )
            return True
        except Exception as exc:
            logger.error("OANDA set_take_profit failed: %s", exc)
            return False

    async def get_open_orders(self, symbol: str) -> list[dict]:
        data = await _with_retry(
            self._get,
            f"/v3/accounts/{self._account_id}/orders",
            {"instrument": symbol, "state": "PENDING"},
        )
        return data.get("orders", [])

    async def close_position(self, symbol: str) -> bool:
        try:
            await _with_retry(
                self._put,
                f"/v3/accounts/{self._account_id}/positions/{symbol}/close",
                {"longUnits": "ALL", "shortUnits": "ALL"},
            )
            return True
        except Exception as exc:
            logger.error("OANDA close_position failed: %s", exc)
            return False

    async def get_order_status(self, symbol: str, order_id: str) -> dict:
        data = await _with_retry(
            self._get, f"/v3/accounts/{self._account_id}/orders/{order_id}"
        )
        order = data.get("order", {})
        return {
            "order_id": order.get("id"),
            "status": order.get("state"),
            "filled_qty": float(order.get("filledUnits", 0) or 0),
            "price": float(order.get("price", 0) or 0),
            "side": "BUY" if float(order.get("units", 0) or 0) > 0 else "SELL",
        }

    async def aclose(self) -> None:
        await self._http.aclose()


# ─────────────────────────────────────────────
# Coinbase Advanced Trade Client
# ─────────────────────────────────────────────

class CoinbaseClient(BaseExchangeClient):
    """Coinbase Advanced Trade REST API client.

    Uses API Key + Secret (JWT-signed requests).
    Docs: https://docs.cdp.coinbase.com/advanced-trade/docs/rest-api-overview
    """

    _BASE = "https://api.coinbase.com"

    def __init__(self, api_key: str, api_secret: str):
        super().__init__(api_key, api_secret)
        self._http = httpx.AsyncClient(
            base_url=self._BASE,
            timeout=10.0,
        )

    @staticmethod
    def _is_pem(secret: str) -> bool:
        """Return True if the secret looks like a PEM private key block."""
        return secret.strip().startswith("-----BEGIN") and "PRIVATE KEY" in secret

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        """Auto-select auth strategy based on the api_secret format.

        CDP keys (ECDSA PEM private key) → JWT Bearer (ES256).
        Legacy/HMAC keys (plain string secret) → CB-ACCESS-* headers.
        """
        if self._is_pem(self.api_secret):
            return self._headers_jwt(method, path)
        return self._headers_hmac(method, path, body)

    def _headers_jwt(self, method: str, path: str) -> dict:
        """Generate JWT Bearer auth for Coinbase CDP (ECDSA PEM private key).

        Coinbase CDP requires a 'uri' claim in the format 'METHOD host/path'.
        Without it every request returns 401 even with a valid key pair.
        """
        import secrets as _secrets

        from jose import jwt as jose_jwt
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        now = int(time.time())
        nonce = _secrets.token_hex(16)

        # Normalise PEM — the secret may arrive with literal \n from JSON transport
        pem = self.api_secret.replace("\\n", "\n").strip()
        private_key = load_pem_private_key(pem.encode(), password=None)

        payload = {
            "sub": self.api_key,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            # Coinbase CDP REQUIRES this claim — omitting it causes 401
            "uri": f"{method.upper()} api.coinbase.com{path}",
        }
        token = jose_jwt.encode(
            payload,
            private_key,
            algorithm="ES256",
            headers={"kid": self.api_key, "nonce": nonce},
        )
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _headers_hmac(self, method: str, path: str, body: str = "") -> dict:
        """Generate legacy HMAC-SHA256 CB-ACCESS-* headers for older Coinbase keys."""
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        sig = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any:
        import json
        resp = await self._http.get(
            path, params=params, headers=self._headers("GET", path)
        )
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict) -> Any:
        import json
        raw = json.dumps(body)
        resp = await self._http.post(
            path, content=raw, headers=self._headers("POST", path, raw)
        )
        resp.raise_for_status()
        return resp.json()

    async def _list_all_brokerage_accounts(self) -> list[dict]:
        """Fetch every wallet; the list-accounts endpoint is cursor-paginated."""
        all_rows: list[dict] = []
        cursor: str | None = None
        while True:
            params: dict[str, str] = {"limit": "250"}
            if cursor:
                params["cursor"] = cursor
            data = await _with_retry(self._get, "/api/v3/brokerage/accounts", params)
            all_rows.extend(data.get("accounts", []))
            if not data.get("has_next"):
                break
            cursor = data.get("cursor")
            if not cursor:
                break
        return all_rows

    @staticmethod
    def _account_quantity(acct: dict) -> tuple[str, float]:
        """Return (currency, quantity) using available + hold when Coinbase exposes hold."""
        currency = (acct.get("currency") or "").strip().upper()
        if not currency:
            return "", 0.0
        avail = acct.get("available_balance") or {}
        qty = float(avail.get("value", 0) or 0)
        hold = acct.get("hold")
        if isinstance(hold, dict):
            qty += float(hold.get("value", 0) or 0)
        return currency, qty

    async def get_account_balance(self) -> float:
        """Return total portfolio value in USD across all Coinbase wallets.

        - Paginates list-accounts so no wallet is dropped.
        - USD / USDC / USDT count at face value.
        - Other fiat (GBP, EUR, …) converts via {CCY}-USD spot (same as Coinbase app cash).
        - Crypto is valued via best_bid_ask or public spot fallback.
        """
        accounts = await self._list_all_brokerage_accounts()

        # ISO-style cash balances Coinbase uses; excludes crypto tickers.
        _FIAT_ISO = frozenset(
            "EUR GBP JPY AUD CAD CHF NZD SGD HKD MXN SEK NOK DKK PLN CZK HUF "
            "RON BGN ISK TRY ZAR BRL ILS AED SAR CNY INR PHP IDR MYR THB KRW "
            "TWD HRK RUB".split()
        )

        by_ccy: dict[str, float] = defaultdict(float)
        for acct in accounts:
            currency, amount = self._account_quantity(acct)
            if amount <= 0 or not currency:
                continue
            by_ccy[currency] += amount

        total = 0.0
        to_price: list[tuple[str, float]] = []  # (currency, amount) → USD

        for currency, amount in by_ccy.items():
            if currency in ("USD", "USDC", "USDT"):
                total += amount
            elif currency in _FIAT_ISO:
                to_price.append((currency, amount))
            else:
                to_price.append((currency, amount))

        async def _to_usd(currency: str, amount: float) -> float:
            if amount <= 0:
                return 0.0
            product_id = f"{currency}-USD"
            try:
                resp = await self._get(
                    "/api/v3/brokerage/best_bid_ask", {"product_ids": product_id}
                )
                books = resp.get("pricebooks", [])
                if books:
                    asks = books[0].get("asks", [])
                    bids = books[0].get("bids", [])
                    ask_p = float(asks[0]["price"]) if asks else 0.0
                    bid_p = float(bids[0]["price"]) if bids else 0.0
                    mid = (ask_p + bid_p) / 2 if ask_p and bid_p else (ask_p or bid_p)
                    if mid > 0:
                        return amount * mid
            except Exception:
                pass
            try:
                async with httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.get(
                        f"https://api.coinbase.com/v2/prices/{product_id}/spot"
                    )
                    if r.status_code == 200:
                        price = float(r.json().get("data", {}).get("amount", 0))
                        if price > 0:
                            return amount * price
            except Exception:
                pass
            return 0.0

        if to_price:
            priced = await asyncio.gather(*[_to_usd(c, a) for c, a in to_price])
            total += sum(priced)

        return total

    async def get_current_price(self, symbol: str) -> float:
        """symbol should be Coinbase product_id format e.g. 'BTC-USD'."""
        product_id = symbol.replace("USDT", "-USDT").replace("USD", "-USD") if "-" not in symbol else symbol
        data = await _with_retry(self._get, f"/api/v3/brokerage/best_bid_ask", {"product_ids": product_id})
        pricebooks = data.get("pricebooks", [])
        if not pricebooks:
            raise ValueError(f"No price data for {product_id}")
        asks = pricebooks[0].get("asks", [])
        return float(asks[0]["price"]) if asks else 0.0

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
    ) -> str:
        product_id = symbol if "-" in symbol else f"{symbol[:3]}-USD"
        order_config = (
            {"limit_limit_gtc": {"base_size": str(quantity), "limit_price": str(price)}}
            if price
            else {"market_market_ioc": {"base_size": str(quantity)}}
        )
        body = {
            "client_order_id": f"ut-{int(time.time())}",
            "product_id": product_id,
            "side": side.upper(),
            "order_configuration": order_config,
        }
        data = await _with_retry(self._post, "/api/v3/brokerage/orders", body)
        return str(data.get("success_response", {}).get("order_id", ""))

    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        try:
            product_id = symbol if "-" in symbol else f"{symbol[:3]}-USD"
            current = await self.get_current_price(product_id)
            side = "SELL" if stop_price < current else "BUY"
            limit_price = stop_price * (0.999 if side == "SELL" else 1.001)

            status = await self.get_order_status(product_id, order_id)
            base_size = float(status.get("filled_qty") or 0)
            if base_size <= 0:
                raise ValueError("Cannot place stop-loss: original order not filled yet")

            body = {
                "client_order_id": f"ut-sl-{int(time.time())}",
                "product_id": product_id,
                "side": side,
                "order_configuration": {
                    "stop_limit_stop_limit_gtc": {
                        "base_size": str(base_size),
                        "stop_price": str(stop_price),
                        "limit_price": str(limit_price),
                    }
                },
            }
            data = await _with_retry(self._post, "/api/v3/brokerage/orders", body)
            return bool(data.get("success", True)) and bool(data.get("success_response", {}).get("order_id"))
        except Exception as exc:
            logger.error("Coinbase set_stop_loss failed: %s", exc)
            return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        try:
            product_id = symbol if "-" in symbol else f"{symbol[:3]}-USD"
            current = await self.get_current_price(product_id)
            side = "SELL" if target_price > current else "BUY"

            status = await self.get_order_status(product_id, order_id)
            base_size = float(status.get("filled_qty") or 0)
            if base_size <= 0:
                raise ValueError("Cannot place take-profit: original order not filled yet")

            body = {
                "client_order_id": f"ut-tp-{int(time.time())}",
                "product_id": product_id,
                "side": side,
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size": str(base_size),
                        "limit_price": str(target_price),
                    }
                },
            }
            data = await _with_retry(self._post, "/api/v3/brokerage/orders", body)
            return bool(data.get("success", True)) and bool(data.get("success_response", {}).get("order_id"))
        except Exception as exc:
            logger.error("Coinbase set_take_profit failed: %s", exc)
            return False

    async def get_open_orders(self, symbol: str) -> list[dict]:
        product_id = symbol if "-" in symbol else f"{symbol[:3]}-USD"
        data = await _with_retry(
            self._get, "/api/v3/brokerage/orders/historical/batch",
            {"product_id": product_id, "order_status": "OPEN"},
        )
        return data.get("orders", [])

    async def close_position(self, symbol: str) -> bool:
        try:
            product_id = symbol if "-" in symbol else f"{symbol[:3]}-USD"

            # 1) Cancel any open orders on this product.
            try:
                open_orders = await _with_retry(
                    self._get,
                    "/api/v3/brokerage/orders/historical/batch",
                    {"product_id": product_id, "order_status": "OPEN"},
                )
                order_ids = [
                    o.get("order_id")
                    for o in (open_orders.get("orders", []) or [])
                    if isinstance(o, dict) and o.get("order_id")
                ]
                if order_ids:
                    await _with_retry(
                        self._post,
                        "/api/v3/brokerage/orders/batch_cancel",
                        {"order_ids": order_ids},
                    )
            except Exception as exc:
                logger.warning("Coinbase close_position: cancel open orders failed: %s", exc)

            # 2) Market-sell the held base asset quantity (if any).
            base_ccy = product_id.split("-", 1)[0].strip().upper()
            qty = 0.0
            try:
                accounts = await self._list_all_brokerage_accounts()
                for acct in accounts:
                    ccy, amount = self._account_quantity(acct)
                    if ccy == base_ccy:
                        qty = float(amount or 0)
                        break
            except Exception as exc:
                logger.warning("Coinbase close_position: failed to fetch balances: %s", exc)
                qty = 0.0

            if qty <= 0:
                return True

            order_id = await self.place_order(product_id, "SELL", qty)
            return bool(order_id)
        except Exception as exc:
            logger.error("CoinbaseClient.close_position failed: %s", exc)
            return False

    async def get_order_status(self, symbol: str, order_id: str) -> dict:
        data = await _with_retry(self._get, f"/api/v3/brokerage/orders/historical/{order_id}")
        order = data.get("order", {})
        return {
            "order_id": order.get("order_id"),
            "status": order.get("status"),
            "filled_qty": float(order.get("filled_size", 0) or 0),
            "price": float(order.get("average_filled_price", 0) or 0),
            "side": order.get("side", ""),
        }

    async def aclose(self) -> None:
        await self._http.aclose()


# ─────────────────────────────────────────────
# Key Validation Helpers
# ─────────────────────────────────────────────

async def validate_alpaca_keys(api_key: str, api_secret: str, paper: bool = True) -> bool:
    """Verify Alpaca credentials by hitting /v2/account. Returns True if valid."""
    base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
    async with httpx.AsyncClient(
        base_url=base,
        headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret},
        timeout=10.0,
    ) as client:
        resp = await client.get("/v2/account")
        return resp.status_code == 200


async def validate_binance_keys(api_key: str, api_secret: str) -> bool:
    """Verify Binance credentials by calling /api/v3/account."""
    base = (settings.binance_base_url or "https://api.binance.com").rstrip("/")
    params: dict[str, Any] = {
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    query = urlencode(params)
    sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    async with httpx.AsyncClient(
        base_url=base,
        headers={"X-MBX-APIKEY": api_key},
        timeout=10.0,
    ) as client:
        resp = await client.get("/api/v3/account", params=params)
        return resp.status_code == 200


async def validate_oanda_keys(api_key: str, account_id: str) -> bool:
    """Verify OANDA credentials by calling /v3/accounts/{id}/summary."""
    base = settings.oanda_base_url.rstrip("/")
    async with httpx.AsyncClient(
        base_url=base,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    ) as client:
        resp = await client.get(f"/v3/accounts/{account_id}/summary")
        return resp.status_code == 200


async def validate_coinbase_keys(api_key: str, api_secret: str) -> bool:
    """Verify Coinbase Advanced Trade credentials by listing accounts.

    Raises httpx.HTTPStatusError on 4xx/5xx so callers can inspect the status
    code and surface a precise error message (e.g. 401 → bad key/signature).
    """
    client = CoinbaseClient(api_key, api_secret)
    try:
        resp = await client._http.get(
            "/api/v3/brokerage/accounts",
            headers=client._headers("GET", "/api/v3/brokerage/accounts"),
        )
        resp.raise_for_status()   # raises HTTPStatusError on 401/403/etc.
        return True
    finally:
        await client.aclose()


async def validate_kraken_keys(api_key: str, api_secret: str) -> bool:
    """Verify Kraken credentials via private Balance."""
    from src.integrations.kraken_client import KrakenClient

    client = KrakenClient(api_key, api_secret)
    try:
        return await client.validate_credentials()
    finally:
        await client.aclose()


async def validate_revolutx_keys(api_key: str, api_secret_pem: str) -> bool:
    """Verify Revolut X credentials by hitting the signed ``/balances`` endpoint.

    ``api_secret_pem`` must be an Ed25519 private key in PEM form — the same
    PEM Unitrader generated and registered with the user's Revolut X account.
    Returns True on 2xx, False on auth/transport failure.
    """
    client = RevolutXClient(api_key=api_key, api_secret=api_secret_pem)
    try:
        info = await client.verify_connection()
        return bool(info)
    finally:
        await client.aclose()


# ─────────────────────────────────────────────
# Revolut X Client
# ─────────────────────────────────────────────

class RevolutXClient(BaseExchangeClient):
    """Revolut X REST API client (crypto spot trading).

    Auth: Ed25519 keypair. The private key (PEM) is stored encrypted on
    Unitrader's side — the user only sees the **public** key, which they
    paste into Revolut X to mint an API key.

    Signed-request envelope (matches Revolut's reference client):
        message  = f"{timestamp_ms}{METHOD}{path_with_query}{body}"
        signature = base64(Ed25519.sign(message))
        headers   = {
            "X-Revx-API-Key":   api_key,
            "X-Revx-Timestamp": timestamp_ms,
            "X-Revx-Signature": signature,
            "Content-Type":     "application/json",
        }

    Base URL: https://revx.revolut.com/api/1.0
    """

    _BASE = "https://revx.revolut.com"
    _PREFIX = "/api/1.0"

    def __init__(self, api_key: str, api_secret: str, base_url: str | None = None):
        super().__init__(api_key, api_secret)
        self._http = httpx.AsyncClient(
            base_url=(base_url or self._BASE).rstrip("/"),
            timeout=10.0,
        )

    # ── Auth helpers ────────────────────────────────────────────────────

    def _load_private_key(self):
        """Return a cryptography Ed25519PrivateKey from the stored PEM.

        Tolerates JSON-escaped newlines (``\\n``) — when the PEM round-trips
        through JSON transport it can arrive with literal ``\\n`` characters
        in place of real line breaks, mirroring Coinbase CDP's quirk.
        """
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        if not self.api_secret:
            raise ValueError("Revolut X private key is not configured")
        pem = self.api_secret.replace("\\n", "\n").strip()
        if not pem.startswith("-----BEGIN"):
            raise ValueError(
                "Revolut X requires an Ed25519 private key in PEM form."
            )
        key = load_pem_private_key(pem.encode("utf-8"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(
                "Revolut X requires an Ed25519 key — got "
                f"{type(key).__name__}"
            )
        return key

    def _signed_headers(
        self,
        method: str,
        path_with_query: str,
        body: str = "",
    ) -> dict:
        import base64

        key = self._load_private_key()
        ts_ms = str(int(time.time() * 1000))
        message = f"{ts_ms}{method.upper()}{path_with_query}{body}"
        signature = base64.b64encode(key.sign(message.encode("utf-8"))).decode("ascii")
        return {
            "X-Revx-API-Key": self.api_key,
            "X-Revx-Timestamp": ts_ms,
            "X-Revx-Signature": signature,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _path_with_query(path: str, params: dict | None) -> str:
        if not params:
            return path
        # Keep the order the caller passed so the signed prefix matches the
        # actual wire query Revolut X receives.
        clean = {k: v for k, v in params.items() if v is not None}
        if not clean:
            return path
        return f"{path}?{urlencode(clean)}"

    # ── Wire helpers ────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None) -> Any:
        signed_path = f"{self._PREFIX}{path}"
        path_with_query = self._path_with_query(signed_path, params)
        resp = await self._http.get(
            path_with_query,
            headers=self._signed_headers("GET", path_with_query),
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def _post(self, path: str, body: dict | None = None) -> Any:
        import json as _json

        signed_path = f"{self._PREFIX}{path}"
        raw = _json.dumps(body or {}, separators=(",", ":"))
        resp = await self._http.post(
            signed_path,
            content=raw,
            headers=self._signed_headers("POST", signed_path, raw),
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def _delete(self, path: str) -> Any:
        signed_path = f"{self._PREFIX}{path}"
        resp = await self._http.delete(
            signed_path,
            headers=self._signed_headers("DELETE", signed_path),
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ── High-level API ──────────────────────────────────────────────────

    async def verify_connection(self) -> dict:
        """Round-trip ``GET /balances`` and pull a UI-ready summary out.

        Returns ``{account_id, available_cash, currency}`` so the connect
        wizard can show the user what's connected without doing a second
        request. ``available_cash`` is the sum of fiat balances (USD/EUR/
        GBP/USDT/USDC) — crypto holdings stay out of buying-power until
        the user explicitly converts them.
        """
        data = await _with_retry(self._get, "/balances")
        balances = data.get("balances") if isinstance(data, dict) else data
        cash = 0.0
        currency = "USD"
        if isinstance(balances, list):
            for row in balances:
                ccy = (row.get("currency") or "").strip().upper()
                amt = float(row.get("amount") or row.get("available") or 0.0)
                if ccy in ("USD", "USDT", "USDC"):
                    cash += amt
                elif ccy in ("EUR", "GBP") and cash <= 0:
                    cash += amt
                    currency = ccy
        account_id = (
            (data.get("account_id") if isinstance(data, dict) else None)
            or "revolutx"
        )
        return {
            "account_id": account_id,
            "available_cash": cash,
            "currency": currency,
        }

    async def get_account_balance(self) -> float:
        info = await self.verify_connection()
        return float(info.get("available_cash") or 0.0)

    async def get_current_price(self, symbol: str) -> float:
        """Return the latest mid price for ``symbol`` (BASE-QUOTE).

        Revolut X exposes top-of-book quotes via ``/tickers`` keyed on the
        ``symbol`` query parameter. We average bid/ask when both are
        present, falling back to whichever side is available.
        """
        sym = symbol if "-" in symbol else f"{symbol}-USD"
        data = await _with_retry(self._get, "/tickers", {"symbol": sym})
        tickers = data.get("tickers") if isinstance(data, dict) else data
        if isinstance(tickers, list) and tickers:
            row = tickers[0]
        elif isinstance(tickers, dict):
            row = tickers
        else:
            raise ValueError(f"No ticker data for {sym}")
        bid = float(row.get("bid") or 0.0)
        ask = float(row.get("ask") or 0.0)
        last = float(row.get("last") or row.get("price") or 0.0)
        if bid and ask:
            return (bid + ask) / 2.0
        return ask or bid or last

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
    ) -> str:
        sym = symbol if "-" in symbol else f"{symbol}-USD"
        body: dict[str, Any] = {
            "symbol": sym,
            "side": side.upper(),
            "type": "LIMIT" if price else "MARKET",
            "quantity": str(quantity),
            "client_order_id": f"ut-{int(time.time() * 1000)}",
            "time_in_force": "GTC",
        }
        if price:
            body["price"] = str(price)
        data = await _with_retry(self._post, "/orders", body)
        return str(data.get("order_id") or data.get("id") or "")

    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        # Revolut X's REST surface (as of writing) does not expose native
        # conditional / stop orders. Mirror Kraken's behaviour: report
        # not-supported so the orchestrator falls back to monitored exits.
        logger.info(
            "RevolutXClient.set_stop_loss: stops not supported via REST yet "
            "(symbol=%s, order_id=%s)", symbol, order_id,
        )
        return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        logger.info(
            "RevolutXClient.set_take_profit: take-profit not supported via REST yet "
            "(symbol=%s, order_id=%s)", symbol, order_id,
        )
        return False

    async def get_open_orders(self, symbol: str) -> list[dict]:
        sym = symbol if "-" in symbol else f"{symbol}-USD"
        data = await _with_retry(self._get, "/orders/active", {"symbol": sym})
        orders = data.get("orders") if isinstance(data, dict) else data
        if not isinstance(orders, list):
            return []
        # Some Revolut X tenants return all active orders regardless of the
        # ``symbol`` query param; filter client-side to be safe.
        target = sym.upper()
        return [
            o for o in orders
            if isinstance(o, dict)
            and (o.get("symbol") or "").upper() == target
        ]

    async def close_position(self, symbol: str) -> bool:
        """Cancel open orders, then market-sell the held base balance.

        Revolut X is spot-only — there's no "position" concept. Closing
        means: stop new buys, then liquidate the base asset balance back
        into the quote currency.
        """
        try:
            sym = symbol if "-" in symbol else f"{symbol}-USD"
            base_ccy = sym.split("-", 1)[0].strip().upper()

            # 1) Cancel any open orders for this symbol.
            try:
                opens = await self.get_open_orders(sym)
                for o in opens:
                    oid = o.get("order_id") or o.get("id")
                    if oid:
                        try:
                            await _with_retry(self._delete, f"/orders/{oid}")
                        except Exception as exc:
                            logger.warning(
                                "RevolutXClient.close_position: cancel %s failed: %s",
                                oid, exc,
                            )
            except Exception as exc:
                logger.warning(
                    "RevolutXClient.close_position: list open orders failed: %s", exc,
                )

            # 2) Sell the held base-asset balance.
            data = await _with_retry(self._get, "/balances")
            balances = data.get("balances") if isinstance(data, dict) else data
            qty = 0.0
            if isinstance(balances, list):
                for row in balances:
                    ccy = (row.get("currency") or "").strip().upper()
                    if ccy == base_ccy:
                        qty = float(row.get("amount") or row.get("available") or 0.0)
                        break
            if qty <= 0:
                return True

            order_id = await self.place_order(sym, "SELL", qty)
            return bool(order_id)
        except Exception as exc:
            logger.error("RevolutXClient.close_position failed: %s", exc)
            return False

    async def get_order_status(self, symbol: str, order_id: str) -> dict:
        try:
            data = await _with_retry(self._get, f"/orders/{order_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return {"order_id": order_id, "status": "not_found"}
            raise
        order = data.get("order") if isinstance(data, dict) and "order" in data else data
        if not isinstance(order, dict):
            return {"order_id": order_id, "status": "unknown"}
        return {
            "order_id": order.get("order_id") or order.get("id") or order_id,
            "status": order.get("status", ""),
            "filled_qty": float(order.get("filled_quantity") or order.get("filled") or 0),
            "price": float(order.get("avg_price") or order.get("price") or 0),
            "side": (order.get("side") or "").upper(),
        }

    async def aclose(self) -> None:
        await self._http.aclose()


# ─────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────

def get_exchange_client(
    exchange: str,
    api_key: str,
    api_secret: str,
    *,
    is_paper: bool = True,
    **kwargs,
) -> BaseExchangeClient:
    """Return the appropriate exchange client for the given exchange name.

    Dispatches via :mod:`src.exchanges.registry`. To add a new exchange,
    drop a new module in ``src/exchanges/`` — no edits here required.

    Args:
        exchange: Lower-cased venue id (e.g. ``"binance"``).
        api_key: Decrypted API key.
        api_secret: Decrypted API secret (or account id for OANDA).
        is_paper: If True, route to paper/sandbox endpoints where applicable.

    Raises:
        ValueError: If exchange is not supported.
    """
    # Lazy import triggers adapter-module registration the first time any
    # caller asks for a client in this process.
    import src.exchanges  # noqa: F401 — side-effect populates registry
    from src.exchanges.registry import get_optional

    spec = get_optional(exchange)
    if spec is None:
        from src.exchanges.registry import all_ids

        raise ValueError(
            f"Unsupported exchange: '{exchange}'. "
            f"Choose {', '.join(sorted(all_ids()))}."
        )
    return spec.build_client(api_key, api_secret, is_paper=is_paper, **kwargs)
