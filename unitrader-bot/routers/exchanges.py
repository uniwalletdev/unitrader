"""
routers/exchanges.py — Exchange API endpoints for Unitrader.

Endpoints:
    GET /api/exchanges/test-connection  — Test connection with stored API keys
"""

import logging
import httpx
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import AuditLog, ExchangeAPIKey
from routers.auth import get_current_user
from security import decrypt_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exchanges", tags=["Exchanges"])


# ─────────────────────────────────────────────
# GET /api/exchanges/test-connection
# ─────────────────────────────────────────────

@router.get("/test-connection")
async def test_exchange_connection(
    exchange: str = Query(..., regex="^(alpaca|binance|oanda|coinbase|kraken)$"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test connection to an exchange using stored API keys.

    Steps:
    1. Fetch the encrypted ExchangeAPIKey from the DB
    2. Decrypt the credentials
    3. Make a lightweight test API call:
       - Alpaca: GET /v2/account
       - Binance: GET /v1/account
       - OANDA: GET /v3/accounts
       - Coinbase: GET /api/v3/brokerage/accounts
    4. Extract account_id, buying_power, currency
    5. Log "API key test performed" to audit log (never log actual keys)
    6. Return success with account details

    Query Params:
        exchange: One of alpaca, binance, oanda, coinbase

    Returns:
        {
            "success": true,
            "exchange": "alpaca",
            "account_id": "PA123456789",
            "buying_power": 100000.00,
            "currency": "USD",
            "message": "Connected successfully"
        }
        OR
        {
            "success": false,
            "error": "Connection failed — please check your API key and secret"
        }
    """
    exchange = exchange.lower()

    # Step 1: Fetch stored API keys
    result = await db.execute(
        select(ExchangeAPIKey).where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.exchange == exchange,
            ExchangeAPIKey.is_active == True,  # noqa: E712
        )
    )
    api_key_row = result.scalar_one_or_none()

    if not api_key_row:
        return {
            "success": False,
            "error": f"No API key stored for {exchange}",
        }

    # Step 2: Decrypt credentials
    try:
        api_key, api_secret = decrypt_api_key(
            api_key_row.encrypted_api_key,
            api_key_row.encrypted_api_secret,
        )
    except Exception as e:
        logger.error(f"Failed to decrypt API keys for user {current_user.id}: {e}")
        await log_api_test(current_user.id, exchange, False, "Decryption failed", db)
        return {
            "success": False,
            "error": "Failed to decrypt API credentials",
        }

    # Step 3: Make test API call based on exchange
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if exchange == "alpaca":
                account_info = await _test_alpaca(client, api_key, api_secret, api_key_row.is_paper)
            elif exchange == "binance":
                account_info = await _test_binance(client, api_key, api_secret)
            elif exchange == "oanda":
                account_info = await _test_oanda(client, api_key, api_secret)
            elif exchange == "coinbase":
                account_info = await _test_coinbase(client, api_key, api_secret)
            elif exchange == "kraken":
                account_info = await _test_kraken(api_key, api_secret)
            else:
                raise ValueError(f"Unknown exchange: {exchange}")

        if not account_info:
            raise ValueError("Failed to extract account information")

        # Step 5: Log the test (never log actual keys)
        await log_api_test(current_user.id, exchange, True, "Connection test successful", db)

        # Step 6: Return success
        return {
            "success": True,
            "exchange": exchange,
            "account_id": account_info.get("account_id"),
            "buying_power": account_info.get("buying_power"),
            "currency": account_info.get("currency", "USD"),
            "message": "Connected successfully",
        }

    except Exception as e:
        logger.error(f"Exchange connection test failed for {exchange}: {e}")
        await log_api_test(current_user.id, exchange, False, str(e), db)
        return {
            "success": False,
            "error": "Connection failed — please check your API key and secret",
        }


# ─────────────────────────────────────────────
# Helper: Test Alpaca connection
# ─────────────────────────────────────────────

async def _test_alpaca(client: httpx.AsyncClient, api_key: str, api_secret: str, is_paper: bool) -> dict:
    """Test Alpaca API connection.

    Returns:
        {
            "account_id": "PA123456789",
            "buying_power": 100000.00,
            "currency": "USD"
        }
    """
    base_url = "https://paper-api.alpaca.markets" if is_paper else "https://api.alpaca.markets"
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }

    response = await client.get(f"{base_url}/v2/account", headers=headers)
    response.raise_for_status()
    data = response.json()

    return {
        "account_id": data.get("account_number"),
        "buying_power": float(data.get("buying_power", 0)),
        "currency": "USD",
    }


# ─────────────────────────────────────────────
# Helper: Test Binance connection
# ─────────────────────────────────────────────

async def _test_binance(client: httpx.AsyncClient, api_key: str, api_secret: str) -> dict:
    """Test Binance API connection.

    Returns:
        {
            "account_id": "123456789",
            "buying_power": 100000.00,
            "currency": "USDT"
        }
    """
    import hmac
    import hashlib
    import time

    # Binance requires HMAC-SHA256 signed requests
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    signature = hmac.new(
        api_secret.encode(),
        query_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    headers = {"X-MBX-APIKEY": api_key}
    params = {"timestamp": timestamp, "signature": signature}

    response = await client.get(
        "https://api.binance.com/api/v3/account",
        headers=headers,
        params=params,
    )
    response.raise_for_status()
    data = response.json()

    # Extract USDT balance
    balances = data.get("balances", [])
    usdt_balance = next(
        (float(b["free"]) for b in balances if b["asset"] == "USDT"),
        0.0,
    )

    return {
        "account_id": str(data.get("accountId")),
        "buying_power": usdt_balance,
        "currency": "USDT",
    }


# ─────────────────────────────────────────────
# Helper: Test OANDA connection
# ─────────────────────────────────────────────

async def _test_oanda(client: httpx.AsyncClient, api_token: str, account_id: str) -> dict:
    """Test OANDA API connection.

    api_token is the API token
    account_id is the OANDA account ID

    Returns:
        {
            "account_id": "101-001-1234567-001",
            "buying_power": 100000.00,
            "currency": "GBP"
        }
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    response = await client.get(
        f"https://api-fxtrade.oanda.com/v3/accounts/{account_id}",
        headers=headers,
    )
    response.raise_for_status()
    data = response.json()

    account = data.get("account", {})
    return {
        "account_id": account.get("id"),
        "buying_power": float(account.get("unrealizedPL", 0)) + float(account.get("balance", 0)),
        "currency": account.get("currency", "GBP"),
    }


# ─────────────────────────────────────────────
# Helper: Test Coinbase connection
# ─────────────────────────────────────────────

async def _test_coinbase(client: httpx.AsyncClient, api_key: str, api_secret: str) -> dict:
    """Test Coinbase API connection.

    Returns:
        {
            "account_id": "account-uuid",
            "buying_power": 100000.00,
            "currency": "USD"
        }
    """
    # Coinbase API requires Authorization header
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = await client.get(
        "https://api.coinbase.com/api/v3/brokerage/accounts",
        headers=headers,
    )
    response.raise_for_status()
    data = response.json()

    # Get first account (USD equivalent)
    accounts = data.get("accounts", [])
    if accounts:
        account = accounts[0]
        return {
            "account_id": account.get("uuid"),
            "buying_power": float(account.get("available_balance", {}).get("value", 0)),
            "currency": account.get("available_balance", {}).get("currency", "USD"),
        }

    return {
        "account_id": "unknown",
        "buying_power": 0.0,
        "currency": "USD",
    }


# ─────────────────────────────────────────────
# Helper: Test Kraken connection
# ─────────────────────────────────────────────

async def _test_kraken(api_key: str, api_secret: str) -> dict:
    """Kraken private Balance — returns ZUSD as buying_power."""
    from src.integrations.kraken_client import KrakenClient

    k = KrakenClient(api_key, api_secret)
    try:
        buying_power = await k.get_account_balance()
        return {
            "account_id": "kraken",
            "buying_power": buying_power,
            "currency": "USD",
        }
    finally:
        await k.aclose()


# ─────────────────────────────────────────────
# Helper: Log API test to audit log
# ─────────────────────────────────────────────

async def log_api_test(user_id: str, exchange: str, success: bool, details: str, db: AsyncSession) -> None:
    """Log API key test to audit_log.

    Never includes actual API keys — only the event.
    """
    try:
        audit_log = AuditLog(
            user_id=user_id,
            event_type="api_key_test",
            event_details={
                "exchange": exchange,
                "success": success,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
        db.add(audit_log)
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to log API test event: {e}")
        await db.rollback()
