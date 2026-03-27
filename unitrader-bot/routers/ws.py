"""
routers/ws.py — WebSocket endpoints for live price streaming.

Endpoints:
    GET /api/ws/prices/{symbol}          — WebSocket live price stream
    GET /api/prices/{symbol}/latest      — Fallback REST endpoint for latest price
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Set

try:
    from alpaca_trade_api import REST as AlpacaREST
except ImportError:
    AlpacaREST = None

import httpx
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState
from jose import JWTError, jwt as jose_jwt

from config import settings
from security import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["WebSocket"])

# Module-level connection pool: {symbol: set of websockets}
_symbol_subscribers: Dict[str, Set[WebSocket]] = {}
# Track active Alpaca subscriptions: {symbol: subscription_task}
_alpaca_subscriptions: Dict[str, asyncio.Task] = {}
# Lock for thread-safe operations
_subscription_lock = asyncio.Lock()

# Alpaca client for REST API calls
alpaca = None


def _get_alpaca_client() -> Any:
    """Return a lazily initialized Alpaca REST client.

    Uses the same settings-backed credentials as the rest of the application,
    with legacy APCA_* environment variables as a fallback.
    """
    global alpaca

    if alpaca is not None:
        return alpaca

    if not AlpacaREST:
        raise ValueError("alpaca_trade_api not installed")

    api_key = settings.alpaca_api_key or os.getenv("APCA_API_KEY_ID", "")
    api_secret = settings.alpaca_api_secret or os.getenv("APCA_API_SECRET_KEY", "")
    base_url = settings.alpaca_base_url or os.getenv(
        "APCA_API_BASE_URL", "https://paper-api.alpaca.markets"
    )

    if not api_key or not api_secret:
        raise ValueError(
            "Alpaca client not initialized: missing ALPACA_API_KEY/ALPACA_API_SECRET configuration"
        )

    try:
        alpaca = AlpacaREST(
            base_url=base_url,
            key_id=api_key,
            secret_key=api_secret,
        )
        return alpaca
    except Exception as exc:
        logger.error("Failed to initialize Alpaca client: %s", exc)
        raise ValueError(f"Alpaca client not initialized: {exc}") from exc


# ─────────────────────────────────────────────
# Token Validation
# ─────────────────────────────────────────────

# In-memory JWKS cache shared by WebSocket validation
_ws_jwks_cache: dict = {}


async def _get_ws_jwks(jwks_url: str) -> dict:
    """Return cached Clerk JWKS, refreshing when older than 1 hour."""
    if _ws_jwks_cache.get("data") and (time.monotonic() - _ws_jwks_cache.get("ts", 0.0)) < 3600:
        return _ws_jwks_cache["data"]
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        data = resp.json()
    _ws_jwks_cache["data"] = data
    _ws_jwks_cache["ts"] = time.monotonic()
    return data


async def _validate_token(token: str) -> str:
    """
    Validate a JWT token (Clerk RS256 or internal HS256) and return user_id.

    Tries Clerk JWKS first (RS256), then falls back to internal HS256 token.

    Raises:
        HTTPException: If token is invalid
    """
    # Try Clerk RS256 via JWKS
    jwks_url = settings.clerk_jwks_url if hasattr(settings, "clerk_jwks_url") else None
    if jwks_url:
        try:
            jwks = await _get_ws_jwks(jwks_url)
            claims = jose_jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
            user_id = claims.get("sub")
            if not user_id:
                raise ValueError("Missing 'sub' claim")
            return user_id
        except Exception as e:
            logger.warning(f"JWT validation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )

    # Fallback: internal HS256 token
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Missing 'sub' claim")
        return user_id
    except JWTError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    except Exception as e:
        logger.warning(f"Token validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


# ─────────────────────────────────────────────
# Price Fetching
# ─────────────────────────────────────────────

async def _fetch_latest_quote(symbol: str) -> Dict[str, Any]:
    """
    Fetch latest quote from Alpaca data REST API via httpx.

    Routes to the crypto endpoint for symbols containing '/' (e.g. BTC/USD)
    and the stocks endpoint for plain equity tickers (e.g. AAPL).

    Returns:
        Dict with symbol, price, bid, ask, bid_size, ask_size, timestamp

    Raises:
        Exception: If fetch fails or credentials are missing
    """
    api_key = settings.alpaca_api_key or os.getenv("APCA_API_KEY_ID", "")
    api_secret = settings.alpaca_api_secret or os.getenv("APCA_API_SECRET_KEY", "")

    if not api_key or not api_secret:
        raise ValueError("Alpaca credentials not configured for price stream")

    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }

    is_crypto = "/" in symbol

    if is_crypto:
        # Crypto endpoint — symbol is a query param, e.g. BTC/USD
        url = "https://data.alpaca.markets/v1beta3/crypto/us/latest/quotes"
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
            resp = await client.get(url, params={"symbols": symbol.upper()})
            resp.raise_for_status()
            payload = resp.json()

        quotes = payload.get("quotes", {}) or {}
        q = quotes.get(symbol.upper(), {}) or {}
        bid = float(q.get("bp", 0) or 0)
        ask = float(q.get("ap", 0) or 0)
    else:
        # Stocks endpoint — symbol in URL path
        url = f"https://data.alpaca.markets/v2/stocks/{symbol.upper()}/quotes/latest"
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()

        q = payload.get("quote", {}) or {}
        bid = float(q.get("bp", 0) or 0)
        ask = float(q.get("ap", 0) or 0)

    price = (bid + ask) / 2 if bid and ask else (ask or bid)

    return {
        "symbol": symbol.upper(),
        "price": price,
        "bid": bid,
        "ask": ask,
        "bid_size": int(q.get("bs", 0) or 0),
        "ask_size": int(q.get("as", 0) or 0),
        "timestamp": q.get("t", datetime.utcnow().isoformat()),
    }


# ─────────────────────────────────────────────
# WebSocket Connection Management
# ─────────────────────────────────────────────


async def _broadcast_to_subscribers(symbol: str, message: Dict[str, Any]):
    """
    Broadcast a message to all WebSocket clients subscribed to a symbol.

    Removes disconnected clients automatically.
    """
    if symbol not in _symbol_subscribers:
        return

    disconnected = set()

    for ws in _symbol_subscribers[symbol]:
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json(message)
            else:
                disconnected.add(ws)
        except Exception as e:
            logger.debug(f"Failed to send to client: {e}")
            disconnected.add(ws)

    # Remove disconnected clients
    _symbol_subscribers[symbol] -= disconnected

    # Clean up symbol if no more subscribers
    if not _symbol_subscribers[symbol]:
        del _symbol_subscribers[symbol]


async def _poll_and_broadcast(symbol: str):
    """
    Poll Alpaca for price updates and broadcast to all connected clients.

    Runs until the symbol has no more subscribers.
    """
    logger.info(f"Starting price poll for {symbol}")
    poll_interval = 3  # seconds — stay within Alpaca free-tier rate limits
    error_count = 0
    max_errors = 5

    try:
        while symbol in _alpaca_subscriptions and error_count < max_errors:
            try:
                # Fetch latest quote
                message = await _fetch_latest_quote(symbol)

                # Broadcast to all subscribers
                if symbol in _symbol_subscribers:
                    await _broadcast_to_subscribers(symbol, message)

                # If no more subscribers, exit the loop
                if symbol not in _symbol_subscribers:
                    logger.info(f"No more subscribers for {symbol}, stopping poll")
                    break

                # Wait before next poll
                await asyncio.sleep(poll_interval)
                error_count = 0  # Reset error count on success

            except Exception as e:
                error_count += 1
                logger.warning(
                    f"Error polling price for {symbol} (attempt {error_count}/{max_errors}): {e}"
                )
                await asyncio.sleep(5)  # Longer wait on error

    except asyncio.CancelledError:
        logger.info(f"Price poll cancelled for {symbol}")
    finally:
        # Clean up subscription
        async with _subscription_lock:
            if symbol in _alpaca_subscriptions:
                del _alpaca_subscriptions[symbol]
        logger.info(f"Stopped price poll for {symbol}")


async def _subscribe_to_symbol(symbol: str):
    """
    Subscribe to price updates for a symbol.

    Creates a background polling task if not already active.
    """
    async with _subscription_lock:
        if symbol not in _alpaca_subscriptions:
            logger.info(f"Creating new subscription for {symbol}")
            task = asyncio.create_task(_poll_and_broadcast(symbol))
            _alpaca_subscriptions[symbol] = task


# ─────────────────────────────────────────────
# WebSocket Endpoint
# ─────────────────────────────────────────────


@router.websocket("/ws/prices/{symbol:path}")
async def websocket_price_stream(websocket: WebSocket, symbol: str, token: str = Query(...)):
    """
    WebSocket endpoint for live price streaming.

    Usage:
        ws://localhost:8000/api/ws/prices/AAPL?token=<jwt_token>

    Sends JSON messages with format:
        {
            "symbol": "AAPL",
            "price": 150.25,
            "bid": 150.24,
            "ask": 150.26,
            "bid_size": 1000,
            "ask_size": 500,
            "timestamp": "2026-03-14T10:30:00.000000"
        }

    Closes with code 4001 if token is invalid.
    """
    # Validate token before accepting connection
    try:
        user_id = await _validate_token(token)
    except HTTPException:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Accept the WebSocket connection
    await websocket.accept()
    logger.info(f"User {user_id} connected to price stream for {symbol}")

    try:
        # Add this connection to the symbol's subscribers
        if symbol not in _symbol_subscribers:
            _symbol_subscribers[symbol] = set()

        _symbol_subscribers[symbol].add(websocket)

        # Subscribe to Alpaca stream if not already active
        await _subscribe_to_symbol(symbol)

        # Send initial quote — failure is non-fatal; the poll loop will deliver prices
        try:
            initial_quote = await _fetch_latest_quote(symbol)
            await websocket.send_json(initial_quote)
        except Exception as e:
            logger.error(f"Failed to send initial quote for {symbol}: {e}")

        # Keep connection alive, listen for disconnect
        while True:
            # This will raise WebSocketDisconnect when client disconnects
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info(f"Client disconnected from price stream for {symbol}")
    except Exception as e:
        logger.error(f"WebSocket error for {symbol}: {e}")
    finally:
        # Remove this connection from subscribers
        if symbol in _symbol_subscribers:
            _symbol_subscribers[symbol].discard(websocket)

            # Clean up symbol if no more subscribers
            if not _symbol_subscribers[symbol]:
                logger.info(f"Last subscriber disconnected for {symbol}")
                del _symbol_subscribers[symbol]

        # Close connection if still open
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────
# Fallback REST Endpoint
# ─────────────────────────────────────────────


@router.get("/prices/{symbol}/latest")
async def get_latest_price(symbol: str, token: str = Query(...)):
    """
    Fallback endpoint for environments where WebSocket is blocked.

    Returns latest price snapshot in same format as WebSocket messages.

    Usage:
        GET /api/prices/AAPL/latest?token=<jwt_token>

    Returns:
        {
            "symbol": "AAPL",
            "price": 150.25,
            "bid": 150.24,
            "ask": 150.26,
            "bid_size": 1000,
            "ask_size": 500,
            "timestamp": "2026-03-14T10:30:00.000000"
        }
    """
    # Validate token
    try:
        user_id = await _validate_token(token)
    except HTTPException as e:
        raise e

    # Fetch latest quote
    try:
        quote_data = await _fetch_latest_quote(symbol)
        return quote_data
    except ValueError as e:
        logger.warning(f"Quote fetch failed for {symbol}: {e}")
        raise HTTPException(status_code=404, detail=f"No quote found for {symbol}")
    except Exception as e:
        logger.error(f"Error fetching quote for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch price data")
