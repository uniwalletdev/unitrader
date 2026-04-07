"""
routers/ws.py — WebSocket endpoints for live price streaming.

Endpoints:
    GET /api/ws/prices/{symbol}          — WebSocket live price stream
    GET /api/prices/{symbol}/latest      — Fallback REST endpoint for latest price
"""

import asyncio
import base64
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Set
from urllib.parse import urlparse

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
from src.integrations.alpaca_rate_limiter import alpaca_limiter, kraken_limiter
from src.market_context import Exchange, ExchangeAssetClassError, normalize_symbol, resolve_market_context

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

    api_key = settings.alpaca_paper_api_key or os.getenv("APCA_API_KEY_ID", "")
    api_secret = settings.alpaca_paper_api_secret or os.getenv("APCA_API_SECRET_KEY", "")
    base_url = settings.alpaca_paper_base_url or os.getenv(
        "APCA_API_BASE_URL", "https://paper-api.alpaca.markets"
    )

    if not api_key or not api_secret:
        raise ValueError(
            "Alpaca client not initialized: missing ALPACA_PAPER_API_KEY (or ALPACA_API_KEY) / secret configuration"
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

# In-memory JWKS cache keyed by JWKS URL (per Clerk Frontend API)
_ws_jwks_cache: dict[str, dict] = {}


async def _get_ws_jwks(jwks_url: str) -> dict:
    """Return cached Clerk JWKS, refreshing when older than 1 hour."""
    entry = _ws_jwks_cache.get(jwks_url)
    if entry and (time.monotonic() - entry.get("ts", 0.0)) < 3600:
        return entry["data"]
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        data = resp.json()
    _ws_jwks_cache[jwks_url] = {"data": data, "ts": time.monotonic()}
    return data


def _jwt_header_alg(token: str) -> str | None:
    try:
        header_b64 = token.split(".")[0]
        padded = header_b64 + "=" * (-len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        alg = header.get("alg")
        return str(alg) if alg else None
    except Exception:
        return None


def _clerk_issuer_allowed(iss: str) -> bool:
    """Allow JWKS fetch from iss only for known Clerk host patterns (plus optional env allowlist)."""
    iss = (iss or "").strip().rstrip("/")
    if not iss.startswith("https://"):
        return False
    try:
        host = (urlparse(iss).hostname or "").lower()
    except Exception:
        return False
    if host.endswith(".clerk.accounts.dev"):
        return True
    allow = (settings.clerk_jwt_iss_allowlist or "").strip()
    if not allow:
        return False
    allowed = {x.strip().rstrip("/") for x in allow.split(",") if x.strip()}
    return iss in allowed


def _resolve_clerk_jwks_url(token: str) -> str:
    """Settings-derived JWKS URL, or iss-based URL for allowlisted Clerk Frontends."""
    url = (settings.clerk_jwks_url or "").strip()
    if url:
        return url
    try:
        unverified = jose_jwt.get_unverified_claims(token)
        iss = (unverified.get("iss") or "").strip().rstrip("/")
        if iss and _clerk_issuer_allowed(iss):
            return f"{iss}/.well-known/jwks.json"
    except Exception as exc:
        logger.debug("Could not derive JWKS URL from Clerk token iss: %s", exc)
    return ""


async def _validate_token(token: str) -> str:
    """
    Validate a JWT token (Clerk RS256 or internal HS256) and return user_id.

    Clerk session tokens (from the browser) use RS256 and require JWKS. REST calls
    typically use the app's HS256 access token; this path supports both.

    Raises:
        HTTPException: If token is invalid
    """
    jwks_url = _resolve_clerk_jwks_url(token)

    if not jwks_url and _jwt_header_alg(token) == "RS256":
        logger.warning(
            "WebSocket auth: Clerk RS256 session token but no JWKS URL could be resolved. "
            "Set CLERK_PUBLISHABLE_KEY or CLERK_JWKS_URL on the API server, or add the token "
            "issuer to CLERK_JWT_ISS_ALLOWLIST for custom Clerk domains."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clerk JWKS not configured on server",
        )

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
            return str(user_id)
        except Exception as e:
            logger.debug("Clerk JWT validation failed, trying internal token: %s", e)

    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Missing 'sub' claim")
        return str(user_id)
    except JWTError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    except Exception as e:
        logger.warning("Token validation error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


# ─────────────────────────────────────────────
# Price Fetching
# ─────────────────────────────────────────────

def _classify_symbol(symbol: str) -> str:
    """Classify a symbol to determine which price source to use.

    Returns one of: 'alpaca_crypto', 'alpaca_stock', 'coinbase', 'binance'
    """
    s = symbol.upper()
    # Alpaca crypto format: BTC/USD
    if "/" in s:
        return "alpaca_crypto"
    # Coinbase format: BTC-USD, ETH-USD, SOL-USD etc.
    if "-" in s:
        return "coinbase"
    # Binance format: BTCUSDT, ETHUSDT, SOLUSDT etc.
    if s.endswith("USDT") or s.endswith("BUSD"):
        return "binance"
    # Default: Alpaca stock
    return "alpaca_stock"


def _is_stock_symbol(symbol: str) -> bool:
    """
    Best-effort heuristic: treat plain tickers as stocks.

    Note: this is only a fallback for unauthenticated/unscoped requests.
    When trading_account_id is provided, `src.market_context` is authoritative.
    """
    return _classify_symbol(symbol) == "alpaca_stock"


async def _fetch_coinbase_price(symbol: str) -> Dict[str, Any]:
    """Fetch latest price from Coinbase public spot price API (no auth required)."""
    url = f"https://api.coinbase.com/v2/prices/{symbol.upper()}/spot"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json().get("data", {})
    price = float(data.get("amount", 0))
    return {
        "symbol": symbol.upper(),
        "price": price,
        "bid": price,
        "ask": price,
        "bid_size": 0,
        "ask_size": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }


async def _fetch_binance_price(symbol: str) -> Dict[str, Any]:
    """Fetch latest price from Binance public ticker API (no auth required)."""
    url = "https://api.binance.com/api/v3/ticker/price"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, params={"symbol": symbol.upper()})
        resp.raise_for_status()
        data = resp.json()
    price = float(data.get("price", 0))
    return {
        "symbol": symbol.upper(),
        "price": price,
        "bid": price,
        "ask": price,
        "bid_size": 0,
        "ask_size": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }


async def _fetch_kraken_price(symbol: str) -> Dict[str, Any]:
    """Fetch last trade price from Kraken public Ticker (no auth required)."""
    await kraken_limiter.acquire()
    url = "https://api.kraken.com/0/public/Ticker"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, params={"pair": symbol.upper()})
        resp.raise_for_status()
        body = resp.json()
    err = body.get("error")
    if err:
        raise ValueError(f"Kraken API error: {err}")
    result = body.get("result") or {}
    if not result:
        raise ValueError(f"No Kraken ticker data for {symbol}")
    pair_data = list(result.values())[0]
    price = float(pair_data["c"][0])
    return {
        "symbol": symbol.upper(),
        "price": price,
        "bid": price,
        "ask": price,
        "bid_size": 0,
        "ask_size": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }


async def _fetch_latest_quote(symbol: str, exchange: str | None = None) -> Dict[str, Any]:
    """
    Fetch latest quote, routing to the correct data source based on symbol format:

    - BTC/USD  → Alpaca crypto endpoint (slash format)
    - BTC-USD  → Coinbase public spot price API (no auth, dash format)
    - BTCUSDT  → Binance public ticker API (no auth, USDT suffix)
    - AAPL     → Alpaca stocks endpoint

    Returns:
        Dict with symbol, price, bid, ask, bid_size, ask_size, timestamp
    """
    ex = (exchange or "").lower() if exchange else None
    sym = symbol.strip().upper().replace(" ", "")

    if ex:
        try:
            sym = normalize_symbol(sym, Exchange(ex))
        except ExchangeAssetClassError as e:
            if "not_supported_on_coinbase" in e.error_code and _is_stock_symbol(sym):
                raise ValueError("stocks_require_alpaca") from e
            raise
        except ValueError:
            # Unknown exchange string; fall back to symbol-only routing below.
            sym = symbol

    # Forced exchange routing (MarketContext-aware)
    if ex == "coinbase":
        if _is_stock_symbol(symbol):
            raise ValueError("stocks_require_alpaca")
        return await _fetch_coinbase_price(sym)
    if ex == "binance":
        if _is_stock_symbol(sym):
            raise ValueError("stocks_require_alpaca")
        return await _fetch_binance_price(sym)
    if ex == "kraken":
        # Pairs are e.g. XBTUSD; short equity tickers must not hit Kraken spot API.
        if _is_stock_symbol(sym) and len(sym) <= 5:
            raise ValueError("stocks_require_alpaca")
        return await _fetch_kraken_price(sym)

    source = _classify_symbol(sym)

    if source == "coinbase":
        return await _fetch_coinbase_price(sym)

    if source == "binance":
        return await _fetch_binance_price(sym)

    # Alpaca (crypto or stock)
    api_key = settings.alpaca_paper_api_key or os.getenv("APCA_API_KEY_ID", "")
    api_secret = settings.alpaca_paper_api_secret or os.getenv("APCA_API_SECRET_KEY", "")

    if not api_key or not api_secret:
        raise ValueError("Alpaca credentials not configured for price stream")

    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }

    async def _alpaca_get_json(url: str, params: dict | None = None) -> dict:
        # Basic 429 handling (free-tier can throttle aggressively).
        backoff_s = 1.0
        last_exc: Exception | None = None
        for _ in range(3):
            try:
                async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
                    await alpaca_limiter.acquire()
                    resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    retry_after = resp.headers.get("retry-after")
                    try:
                        wait_s = float(retry_after) if retry_after else backoff_s
                    except Exception:
                        wait_s = backoff_s
                    await asyncio.sleep(min(10.0, max(0.5, wait_s)))
                    backoff_s = min(10.0, backoff_s * 2)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_exc = exc
                await asyncio.sleep(min(10.0, backoff_s))
                backoff_s = min(10.0, backoff_s * 2)
        raise last_exc or RuntimeError("Alpaca request failed")

    if source == "alpaca_crypto":
        url = "https://data.alpaca.markets/v1beta3/crypto/us/latest/quotes"
        payload = await _alpaca_get_json(url, params={"symbols": sym.upper()})
        quotes = payload.get("quotes", {}) or {}
        q = quotes.get(sym.upper(), {}) or {}
        bid = float(q.get("bp", 0) or 0)
        ask = float(q.get("ap", 0) or 0)
    else:
        # Alpaca stocks endpoint
        url = f"https://data.alpaca.markets/v2/stocks/{sym.upper()}/quotes/latest"
        payload = await _alpaca_get_json(url)
        q = payload.get("quote", {}) or {}
        bid = float(q.get("bp", 0) or 0)
        ask = float(q.get("ap", 0) or 0)

    price = (bid + ask) / 2 if bid and ask else (ask or bid)

    return {
        "symbol": sym.upper(),
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


async def _poll_and_broadcast(symbol: str, exchange: str | None = None):
    """
    Poll Alpaca for price updates and broadcast to all connected clients.

    Runs until the symbol has no more subscribers.
    """
    logger.info(f"Starting price poll for {symbol}")
    poll_interval = 15  # seconds — stay within Alpaca free-tier rate limits
    error_count = 0
    max_errors = 5

    try:
        while symbol in _alpaca_subscriptions and error_count < max_errors:
            try:
                # Fetch latest quote
                message = await _fetch_latest_quote(symbol, exchange=exchange)

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


async def _subscribe_to_symbol(symbol: str, exchange: str | None = None):
    """
    Subscribe to price updates for a symbol.

    Creates a background polling task if not already active.
    """
    async with _subscription_lock:
        if symbol not in _alpaca_subscriptions:
            logger.info(f"Creating new subscription for {symbol}")
            task = asyncio.create_task(_poll_and_broadcast(symbol, exchange=exchange))
            _alpaca_subscriptions[symbol] = task


# ─────────────────────────────────────────────
# WebSocket Endpoint
# ─────────────────────────────────────────────


@router.websocket("/ws/prices/{symbol:path}")
async def websocket_price_stream(
    websocket: WebSocket,
    symbol: str,
    token: str = Query(...),
    trading_account_id: str | None = Query(default=None),
):
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

    resolved_exchange: str | None = None
    if trading_account_id:
        try:
            from database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                ctx = await resolve_market_context(
                    db=db, user_id=user_id, trading_account_id=trading_account_id
                )
            resolved_exchange = ctx.exchange.value
        except HTTPException:
            await websocket.close(code=4004, reason="Trading account not found")
            return

    # Accept the WebSocket connection
    await websocket.accept()
    logger.info(f"User {user_id} connected to price stream for {symbol}")

    try:
        # Add this connection to the symbol's subscribers
        if symbol not in _symbol_subscribers:
            _symbol_subscribers[symbol] = set()

        _symbol_subscribers[symbol].add(websocket)

        # Coinbase mode: crypto only (stocks require Alpaca connection)
        if resolved_exchange == "coinbase" and _is_stock_symbol(symbol):
            await websocket.send_json(
                {"symbol": symbol.upper(), "price": None, "error": "stocks_require_alpaca"}
            )
            await websocket.close(code=4002, reason="Stocks require Alpaca connection")
            return

        # Subscribe to polling loop (exchange-aware if trading_account_id provided)
        await _subscribe_to_symbol(symbol, exchange=resolved_exchange)

        # Send initial quote — failure is non-fatal; the poll loop will deliver prices
        try:
            initial_quote = await _fetch_latest_quote(symbol, exchange=resolved_exchange)
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
async def get_latest_price(
    symbol: str,
    token: str = Query(...),
    trading_account_id: str | None = Query(default=None),
):
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
        resolved_exchange: str | None = None
        if trading_account_id:
            from database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                ctx = await resolve_market_context(
                    db=db, user_id=user_id, trading_account_id=trading_account_id
                )
            resolved_exchange = ctx.exchange.value
        quote_data = await _fetch_latest_quote(symbol, exchange=resolved_exchange)
        return quote_data
    except ValueError as e:
        logger.warning(f"Quote fetch failed for {symbol}: {e}")
        raise HTTPException(status_code=404, detail=f"No quote found for {symbol}")
    except Exception as e:
        logger.error(f"Error fetching quote for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch price data")
