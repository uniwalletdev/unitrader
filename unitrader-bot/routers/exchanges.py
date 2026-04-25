"""
routers/exchanges.py — Exchange API endpoints for Unitrader.

Endpoints:
    GET  /api/exchanges/list                          — Wizard-facing registry projection
    GET  /api/exchanges/test-connection               — Test connection with stored API keys
    POST /api/exchanges/revolutx/generate-keypair     — Generate + store a pending Ed25519 keypair
"""

import json
import logging
import hashlib
import httpx
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings as app_settings
from database import get_db
from models import AuditLog, ExchangeAPIKey
from routers.auth import get_current_user
from security import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exchanges", tags=["Exchanges"])


# ─────────────────────────────────────────────
# GET /api/exchanges/list
# ─────────────────────────────────────────────

@router.get("/list")
async def list_exchanges(current_user=Depends(get_current_user)) -> Response:
    """Return every registered ``ExchangeSpec`` as a wizard-facing projection.

    Coming-soon exchanges (``spec.coming_soon == True``) are returned with
    a ``coming_soon`` flag + ``coming_soon_reason`` so the frontend can
    render a "Coming Soon" badge instead of a Connect button. They are
    NOT hidden — users can see what's on the roadmap.

    Response shape: ``{"exchanges": [ {...}, ... ]}``.

    Only wizard-relevant fields are serialised — internal priority maps,
    client classes, and callable fields stay server-side. Cached for 60s
    because specs change only on deploy.
    """
    # Ensure the registry is populated (side-effect import).
    import src.exchanges  # noqa: F401
    from src.exchanges.registry import all_specs

    items: list[dict] = []
    for spec in all_specs():
        items.append({
            "id": spec.id,
            "display_name": spec.display_name,
            "tagline": spec.tagline,
            "asset_classes": sorted(a.value for a in spec.asset_classes),
            "primary_asset_class": spec.primary_asset_class.value,
            "paper_mode": spec.paper_mode.value,
            "supports_paper": spec.supports_paper,
            "supports_fractional": spec.supports_fractional,
            "symbol_format_hint": spec.symbol_format_hint,
            "search_placeholder": spec.search_placeholder,
            "color_tone": spec.color_tone,
            # Wizard-driven config (Commit 2 populates these on ExchangeSpec).
            # getattr with defaults keeps this endpoint forward- and
            # backward-compatible so Commit 1 ships standalone.
            "has_environment_toggle": bool(
                getattr(spec, "has_environment_toggle", False)
            ),
            "environment_options": list(
                getattr(spec, "environment_options", []) or []
            ),
            "environment_help_text": dict(
                getattr(spec, "environment_help_text", {}) or {}
            ),
            "connect_instructions_url": getattr(
                spec, "connect_instructions_url", None
            ),
            "connect_instructions_steps": list(
                getattr(spec, "connect_instructions_steps", []) or []
            ),
            "credential_fields": list(
                getattr(spec, "credential_fields", []) or []
            ),
            # Coming-soon lifecycle: when True the frontend shows a badge
            # and disables the Connect flow. Backend also rejects writes.
            "coming_soon": bool(getattr(spec, "coming_soon", False)),
            "coming_soon_reason": getattr(spec, "coming_soon_reason", None),
        })

    return Response(
        content=json.dumps({"exchanges": items}),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )


# ─────────────────────────────────────────────
# GET /api/exchanges/test-connection
# ─────────────────────────────────────────────

@router.get("/test-connection")
async def test_exchange_connection(
    exchange: str = Query(..., regex="^(alpaca|binance|oanda|coinbase|kraken|etoro|revolutx)$"),
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

    # Coming-soon gate — generic, registry-driven. Any exchange flagged
    # coming_soon=True is rejected here so users can't smoke-test
    # credentials against an integration that isn't production-ready.
    import src.exchanges  # noqa: F401 — populate registry
    from src.exchanges.registry import get_optional as _get_spec_optional

    _spec_pre = _get_spec_optional(exchange)
    if _spec_pre is not None and getattr(_spec_pre, "coming_soon", False):
        return {
            "success": False,
            "error": (
                getattr(_spec_pre, "coming_soon_reason", None)
                or f"{_spec_pre.display_name} integration is not available yet. Coming soon."
            ),
        }

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

    # Step 3: Make test API call via the exchange registry
    try:
        import src.exchanges  # noqa: F401 — populate registry
        from src.exchanges.registry import get_optional

        spec = get_optional(exchange)
        if spec is None:
            raise ValueError(f"Unknown exchange: {exchange}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            account_info = await spec.test_connection(
                client, api_key, api_secret, api_key_row.is_paper
            )

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


# ─────────────────────────────────────────────
# POST /api/exchanges/revolutx/generate-keypair
# ─────────────────────────────────────────────

# Sentinel placeholder we encrypt into ``encrypted_api_key`` on the pending
# row. The real Revolut X-issued API key replaces it on the active row when
# the user submits it via the connect endpoint.
_REVOLUTX_PENDING_API_KEY_SENTINEL = "__revolutx_pending__"


@router.post("/revolutx/generate-keypair")
async def revolutx_generate_keypair(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an Ed25519 keypair on the server, return the public key PEM.

    Step 1 of the Revolut X 3-step connect flow:
      - Generates a fresh Ed25519 keypair.
      - Stores the **private** key PEM encrypted on a *pending* row
        (``is_active=False``, ``key_version=0``) so the user can come
        back later or refresh the page without losing it.
      - Returns the **public** key PEM (plus a short fingerprint) for
        the user to register inside Revolut X → Profile → API Keys.

    Any pre-existing pending Revolut X row for this user is overwritten
    so the wizard never accumulates stale keypairs.

    Response:
        {
            "public_key_pem": "-----BEGIN PUBLIC KEY-----\\n...",
            "fingerprint": "ab:cd:...",
            "expires_at": null,
            "instructions_url": "https://revx.revolut.com/profile/api-keys"
        }
    """
    # Generate the keypair using the same cryptography library that
    # powers Coinbase JWT signing. Ed25519 keys are 32 bytes private +
    # 32 bytes public; PEM serialisation gives us a portable string the
    # frontend can render in a copy-button.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    # Short SHA-256 fingerprint (first 8 bytes hex, colon-separated) so
    # users can sanity-check the public key matches what they pasted into
    # Revolut X. Mirrors how SSH renders fingerprints.
    digest = hashlib.sha256(public_pem.encode("utf-8")).hexdigest()
    fingerprint = ":".join(digest[i : i + 2] for i in range(0, 16, 2))

    # Encrypt the private key PEM with Fernet (the same field-level
    # encryption used for every other broker secret). The placeholder
    # api_key gets encrypted too so column constraints stay intact.
    enc_key, enc_secret = encrypt_api_key(
        _REVOLUTX_PENDING_API_KEY_SENTINEL, private_pem
    )

    # Drop any prior pending row for this user — there can only be one
    # outstanding keypair waiting for an API key.
    existing = await db.execute(
        select(ExchangeAPIKey).where(
            ExchangeAPIKey.user_id == current_user.id,
            ExchangeAPIKey.exchange == "revolutx",
            ExchangeAPIKey.is_active == False,  # noqa: E712
            ExchangeAPIKey.key_version == 0,
        )
    )
    for row in existing.scalars().all():
        await db.delete(row)

    pending = ExchangeAPIKey(
        user_id=current_user.id,
        exchange="revolutx",
        encrypted_api_key=enc_key,
        encrypted_api_secret=enc_secret,
        # key_hash is not meaningful for the placeholder; hash the
        # fingerprint so the column has something deterministic.
        key_hash=hashlib.sha256(fingerprint.encode()).hexdigest(),
        is_active=False,
        # Revolut X is live-only — pending rows are always live.
        is_paper=False,
        key_version=0,
    )
    db.add(pending)

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error(
            "Failed to store Revolut X pending keypair for user %s: %s",
            current_user.id, exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate Revolut X key. Please try again.",
        )

    # Audit-log the generation event (never include the private key).
    try:
        db.add(
            AuditLog(
                user_id=current_user.id,
                event_type="revolutx_keypair_generated",
                event_details={
                    "exchange": "revolutx",
                    "fingerprint": fingerprint,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to write revolutx_keypair_generated audit row: %s", exc)
        await db.rollback()

    return {
        "public_key_pem": public_pem,
        "fingerprint": fingerprint,
        "instructions_url": "https://revx.revolut.com/profile/api-keys",
        "next_step": (
            "Open Revolut X → Profile → API Keys → Add API Key, paste the "
            "public key above, then come back and paste the API key Revolut "
            "X gives you."
        ),
    }
