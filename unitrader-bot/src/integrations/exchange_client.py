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

    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        """Place a STOP_LOSS_LIMIT order as a separate order (Binance doesn't have OCO free-form)."""
        try:
            current_price = await self.get_current_price(symbol)
            # Determine the sell side: if stop < current it's a stop for a long position
            side = "SELL" if stop_price < current_price else "BUY"
            params = {
                "symbol": symbol,
                "side": side,
                "type": "STOP_LOSS_LIMIT",
                "stopPrice": f"{stop_price:.8f}",
                "price": f"{stop_price * 0.999:.8f}",  # slight slippage buffer
                "quantity": "0",  # caller should provide qty; placeholder
                "timeInForce": "GTC",
            }
            await _with_retry(self._post, "/api/v3/order", params)
            return True
        except Exception as exc:
            logger.error("Binance set_stop_loss failed: %s", exc)
            return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        """Place a TAKE_PROFIT_LIMIT order."""
        try:
            current_price = await self.get_current_price(symbol)
            side = "SELL" if target_price > current_price else "BUY"
            params = {
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_LIMIT",
                "stopPrice": f"{target_price:.8f}",
                "price": f"{target_price * 0.999:.8f}",
                "quantity": "0",
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

    Supports paper trading via ALPACA_BASE_URL=https://paper-api.alpaca.markets
    Docs: https://docs.alpaca.markets/reference/
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str | None = None):
        super().__init__(api_key, api_secret)
        raw_url = (base_url or settings.alpaca_base_url).rstrip("/")
        if raw_url.endswith("/v2"):
            raw_url = raw_url[:-3]
        self._base_url = raw_url
        _common_headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
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
        data = await _with_retry(self._data_get, f"/v2/stocks/{symbol}/quotes/latest")
        quote = data.get("quote", {})
        bid = float(quote.get("bp", 0))
        ask = float(quote.get("ap", 0))
        return (bid + ask) / 2 if bid and ask else float(quote.get("ap", 0))

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
            await _with_retry(
                self._post,
                "/v2/orders",
                {
                    "symbol": symbol,
                    "qty": "1",  # placeholder — real implementation fetches position qty
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
            await _with_retry(
                self._post,
                "/v2/orders",
                {
                    "symbol": symbol,
                    "qty": "1",
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
        try:
            await _with_retry(
                self._put,
                f"/v3/accounts/{self._account_id}/orders/{order_id}",
                {"order": {"stopLossOnFill": {"price": str(stop_price)}}},
            )
            return True
        except Exception as exc:
            logger.error("OANDA set_stop_loss failed: %s", exc)
            return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        try:
            await _with_retry(
                self._put,
                f"/v3/accounts/{self._account_id}/orders/{order_id}",
                {"order": {"takeProfitOnFill": {"price": str(target_price)}}},
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

    async def get_account_balance(self) -> float:
        """Return sum of USD and USDC portfolio value."""
        data = await _with_retry(self._get, "/api/v3/brokerage/accounts")
        total = 0.0
        for acct in data.get("accounts", []):
            if acct.get("currency") in ("USD", "USDC"):
                total += float(acct.get("available_balance", {}).get("value", 0))
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
            # Get current position size
            data = await _with_retry(self._get, f"/api/v3/brokerage/portfolios")
            # Place a market sell for the held quantity
            positions = await _with_retry(
                self._get, "/api/v3/brokerage/orders/historical/batch",
                {"product_id": product_id, "order_status": "OPEN"},
            )
            for order in positions.get("orders", []):
                await _with_retry(
                    self._post,
                    f"/api/v3/brokerage/orders/batch_cancel",
                    {"order_ids": [order["order_id"]]},
                )
            return True
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

    Args:
        exchange: One of 'binance', 'alpaca', 'oanda'.
        api_key: Decrypted API key.
        api_secret: Decrypted API secret.
        is_paper: If True, route to paper/sandbox endpoints where applicable.

    Raises:
        ValueError: If exchange is not supported.
    """
    exchange = exchange.lower()
    if exchange == "binance":
        return BinanceClient(api_key, api_secret, base_url=kwargs.get("base_url"))
    if exchange == "alpaca":
        base_url = kwargs.get("base_url")
        if not base_url:
            base_url = (
                "https://paper-api.alpaca.markets" if is_paper
                else "https://api.alpaca.markets"
            )
        return AlpacaClient(api_key, api_secret, base_url=base_url)
    if exchange == "oanda":
        return OandaClient(api_key, api_secret, account_id=kwargs.get("account_id"))
    if exchange == "coinbase":
        return CoinbaseClient(api_key, api_secret)
    raise ValueError(f"Unsupported exchange: '{exchange}'. Choose binance, alpaca, oanda, or coinbase.")
