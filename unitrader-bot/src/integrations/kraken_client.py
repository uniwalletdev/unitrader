"""
Kraken exchange client for Unitrader.
Implements the same interface as CoinbaseClient and AlpacaClient.
Kraken API docs: https://docs.kraken.com/rest/
Authentication: HMAC-SHA512 with nonce.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Any, Optional

import httpx

from src.integrations.exchange_client import BaseExchangeClient

logger = logging.getLogger(__name__)

KRAKEN_BASE = "https://api.kraken.com"


class KrakenClient(BaseExchangeClient):
    """
    Kraken REST API client.
    api_key: Kraken API Key (public key)
    api_secret: Kraken Private Key (base64-encoded secret)
    """

    def __init__(self, api_key: str, api_secret: str):
        super().__init__(api_key, api_secret)
        self._client = httpx.AsyncClient(timeout=10.0)

    def _get_kraken_signature(self, urlpath: str, data: dict) -> str:
        """Generate HMAC-SHA512 signature for private endpoints."""
        post_data = urllib.parse.urlencode(data)
        encoded = (str(data["nonce"]) + post_data).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        mac = hmac.new(
            base64.b64decode(self.api_secret),
            message,
            hashlib.sha512,
        )
        return base64.b64encode(mac.digest()).decode()

    async def _private_request(self, endpoint: str, data: dict | None = None) -> dict:
        """Make authenticated POST request to Kraken private API."""
        urlpath = f"/0/private/{endpoint}"
        payload: dict[str, Any] = dict(data or {})
        payload["nonce"] = str(int(time.time() * 1000))
        signature = self._get_kraken_signature(urlpath, payload)
        headers = {
            "API-Key": self.api_key,
            "API-Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        url = f"{KRAKEN_BASE}{urlpath}"
        response = await self._client.post(url, data=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        err = result.get("error")
        if err:
            raise ValueError(f"Kraken API error: {err}")
        return result.get("result", {})

    async def _public_request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make unauthenticated GET request to Kraken public API."""
        url = f"{KRAKEN_BASE}/0/public/{endpoint}"
        response = await self._client.get(url, params=params or {})
        response.raise_for_status()
        result = response.json()
        err = result.get("error")
        if err:
            raise ValueError(f"Kraken API error: {err}")
        return result.get("result", {})

    async def get_account_balance(self) -> float:
        """Return total USD/ZUSD balance."""
        result = await self._private_request("Balance", {})
        usd = float(result.get("ZUSD", result.get("USD", 0)) or 0)
        return usd

    async def get_current_price(self, symbol: str) -> float:
        """Return last trade price for a Kraken pair (e.g. XBTUSD)."""
        result = await self._public_request("Ticker", {"pair": symbol})
        pair_data = list(result.values())[0]
        return float(pair_data["c"][0])

    async def get_ohlcv(self, symbol: str, interval: int = 5) -> list[dict]:
        """
        Return OHLCV bars.
        interval: minutes (1, 5, 15, 30, 60, 240, 1440, 10080, 21600)
        """
        result = await self._public_request(
            "OHLC", {"pair": symbol, "interval": interval}
        )
        pair_data = list(result.values())[0]
        return [
            {
                "timestamp": row[0],
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[6]),
            }
            for row in pair_data
        ]

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
    ) -> str:
        """Place a market or limit order. Returns the order transaction ID (txid)."""
        data: dict[str, str] = {
            "pair": symbol,
            "type": "buy" if side.upper() == "BUY" else "sell",
            "ordertype": "market" if price is None else "limit",
            "volume": str(quantity),
        }
        if price is not None:
            data["price"] = str(price)

        result = await self._private_request("AddOrder", data)
        txids = result.get("txid", [])
        return txids[0] if txids else ""

    async def set_stop_loss(self, symbol: str, order_id: str, stop_price: float) -> bool:
        logger.warning("Kraken set_stop_loss not implemented for spot orders")
        return False

    async def set_take_profit(self, symbol: str, order_id: str, target_price: float) -> bool:
        logger.warning("Kraken set_take_profit not implemented for spot orders")
        return False

    async def get_open_orders(self, symbol: str) -> list[dict]:
        # Kraken's OpenOrders endpoint returns all open orders regardless of
        # a `pair` filter, so we fetch all then filter client-side.
        result = await self._private_request("OpenOrders", {})
        open_map = result.get("open") or {}
        out: list[dict] = []

        def _canon_pair(p: str) -> str:
            s = (p or "").upper().strip()
            if not s:
                return ""
            # Drop separators.
            for sep in ("/", "-", "_"):
                s = s.replace(sep, "")
            # Common asset aliases.
            s = s.replace("XBT", "BTC").replace("XDG", "DOGE")
            # Strip Kraken prefixes (X/Z) from asset codes only when present.
            if s.startswith(("X", "Z")) and len(s) > 4:
                s = s[1:]
            return s

        want = _canon_pair(symbol)
        for txid, info in open_map.items():
            descr = info.get("descr") or {}
            pair = descr.get("pair", symbol)
            if want and _canon_pair(str(pair)) != want:
                continue
            out.append(
                {
                    "order_id": txid,
                    "pair": pair,
                    "side": descr.get("type", ""),
                    "vol": info.get("vol", "0"),
                }
            )
        return out

    async def close_position(self, symbol: str) -> bool:
        logger.warning(
            "Kraken close_position is not automated — sell/buy back the held base asset explicitly"
        )
        return False

    async def get_order_status(self, symbol: str, order_id: str) -> dict:
        result = await self._private_request("QueryOrders", {"txid": order_id})
        info = (result.get(order_id) or {}) if isinstance(result, dict) else {}
        if not info and isinstance(result, dict):
            # Kraken returns { txid: { ... } }
            first = next(iter(result.values()), {})
            info = first if isinstance(first, dict) else {}
        descr = info.get("descr") or {}
        return {
            "order_id": order_id,
            "status": info.get("status", ""),
            "filled_qty": float(info.get("vol_exec", 0) or 0),
            "price": float(descr.get("price", 0) or 0),
            "side": (descr.get("type") or "").upper(),
        }

    async def validate_credentials(self) -> bool:
        """Test that API credentials are valid."""
        try:
            await self._private_request("Balance", {})
            return True
        except Exception as exc:
            logger.warning("Kraken credential validation failed: %s", exc)
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
