"""
routers/ws.py — WebSocket endpoints for live price streaming.

Endpoints:
    GET /api/ws/prices/{symbol}          — WebSocket live price stream
    GET /api/prices/{symbol}/latest      — Fallback REST endpoint for latest price
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, Set

try:
    from alpaca_trade_api import REST as AlpacaREST
except ImportError:
    AlpacaREST = None

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState
from jose import JWTError

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
if AlpacaREST:
    try:
        alpaca = AlpacaREST(
            base_url=os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets"),
            key_id=os.getenv("APCA_API_KEY_ID"),
            secret_key=os.getenv("APCA_API_SECRET_KEY"),
        )
    except Exception as e:
        logger.error(f"Failed to initialize Alpaca client: {e}")
        alpaca = None
else:
    logger.warning("alpaca_trade_api not installed — WebSocket price streaming will not work")


# ─────────────────────────────────────────────
# Token Validation
# ─────────────────────────────────────────────

def _validate_token(token: str) -> str:
    """
    Validate JWT token and return user_id.

    Raises:
        HTTPException: If token is invalid
    """
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

def _fetch_latest_quote(symbol: str) -> Dict[str, Any]:
    """
    Fetch latest quote from Alpaca REST API.

    Returns:
        Dict with symbol, price, bid, ask, volume, change_pct, timestamp

    Raises:
        Exception: If fetch fails
    """
    if not alpaca:
        raise ValueError("Alpaca client not initialized")

    quote = alpaca.get_last_quote(symbol)
    if not quote:
        raise ValueError(f"No quote found for {symbol}")

    # Extract timestamp if available
    timestamp = datetime.utcnow().isoformat()
    if hasattr(quote, "timestamp"):
        timestamp = (
            quote.timestamp.isoformat()
            if isinstance(quote.timestamp, datetime)
            else str(quote.timestamp)
        )

    # Build response
    return {
        "symbol": symbol.upper(),
        "price": float(quote.last),
        "bid": float(quote.bid),
        "ask": float(quote.ask),
        "bid_size": int(quote.bid_size) if hasattr(quote, "bid_size") else 0,
        "ask_size": int(quote.ask_size) if hasattr(quote, "ask_size") else 0,
        "timestamp": timestamp,
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
    poll_interval = 1  # seconds
    error_count = 0
    max_errors = 5

    try:
        while symbol in _alpaca_subscriptions and error_count < max_errors:
            try:
                # Fetch latest quote
                message = _fetch_latest_quote(symbol)

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


@router.websocket("/ws/prices/{symbol}")
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
        user_id = _validate_token(token)
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

        # Send initial quote
        try:
            initial_quote = _fetch_latest_quote(symbol)
            await websocket.send_json(initial_quote)
        except Exception as e:
            logger.error(f"Failed to send initial quote for {symbol}: {e}")
            await websocket.close(code=4000, reason="Failed to fetch price")
            return

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
        user_id = _validate_token(token)
    except HTTPException as e:
        raise e

    # Fetch latest quote
    try:
        quote_data = _fetch_latest_quote(symbol)
        return quote_data
    except ValueError as e:
        logger.warning(f"Quote fetch failed for {symbol}: {e}")
        raise HTTPException(status_code=404, detail=f"No quote found for {symbol}")
    except Exception as e:
        logger.error(f"Error fetching quote for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch price data")
