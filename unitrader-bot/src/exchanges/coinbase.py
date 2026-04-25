"""src/exchanges/coinbase.py — Coinbase Advanced Trade (crypto) registration."""
from __future__ import annotations

import httpx

from src.exchanges.registry import (
    AssetClass,
    ExchangeSpec,
    OrderType,
    PaperMode,
    TimeInForce,
    register,
)


def normalise_symbol(symbol: str) -> str:
    """Crypto only → BASE-USD product id."""
    from src.integrations.market_data import classify_asset

    clean = symbol.upper().strip()
    parts = clean.split("/")
    if len(parts) == 3:
        clean = f"{parts[0]}/{parts[1]}"

    if classify_asset(clean) != "crypto":
        raise ValueError(f"Coinbase only supports crypto — cannot trade {symbol}")

    base = clean.split("/")[0].split("_")[0].split("-")[0]
    for s in ("USDT", "USDC", "BUSD", "USD"):
        if base.endswith(s):
            base = base[: -len(s)]
    return f"{base}-USD"


async def test_connection(
    client: httpx.AsyncClient, api_key: str, api_secret: str, is_paper: bool
) -> dict:
    """Test Coinbase connection using proper auth (JWT for CDP keys, HMAC for legacy keys).
    
    This routes through CoinbaseClient._headers() which auto-detects the auth method
    and applies the correct signing. CDP keys (PEM format) use JWT Bearer tokens,
    while legacy keys use CB-ACCESS-* HMAC headers.
    """
    from src.integrations.exchange_client import CoinbaseClient
    
    cb = CoinbaseClient(api_key, api_secret)
    try:
        resp = await client.get(
            "https://api.coinbase.com/api/v3/brokerage/accounts",
            headers=cb._headers("GET", "/api/v3/brokerage/accounts"),
        )
        resp.raise_for_status()
        data = resp.json()
        accounts = data.get("accounts", [])
        if accounts:
            acc = accounts[0]
            bal = acc.get("available_balance", {})
            return {
                "account_id": acc.get("uuid"),
                "buying_power": float(bal.get("value", 0)),
                "currency": bal.get("currency", "USD"),
            }
        return {"account_id": "unknown", "buying_power": 0.0, "currency": "USD"}
    finally:
        await cb.aclose()


async def fetch_market_data(symbol: str) -> dict:
    from src.integrations.market_data import _fetch_coinbase_spot

    return await _fetch_coinbase_spot(normalise_symbol(symbol))


async def score_universe() -> list[str]:
    from src.watchlists import CRYPTO_UNIVERSE, _score_crypto_coinbase

    return await _score_crypto_coinbase(CRYPTO_UNIVERSE)


def build_client(api_key: str, api_secret: str, *, is_paper: bool = True, **kwargs):
    from src.integrations.exchange_client import CoinbaseClient

    return CoinbaseClient(api_key, api_secret)


def _build_spec() -> ExchangeSpec:
    from src.integrations.exchange_client import CoinbaseClient

    return ExchangeSpec(
        id="coinbase",
        display_name="Coinbase",
        tagline="Crypto",
        asset_classes=frozenset({AssetClass.CRYPTO}),
        primary_asset_class=AssetClass.CRYPTO,
        # Coinbase has no paper API; the platform-wide paper-mode toggle is
        # synthetic for crypto venues other than Alpaca.
        paper_mode=PaperMode.SYNTHETIC,
        supports_paper=False,
        supports_fractional=True,
        order_types=frozenset({OrderType.MARKET, OrderType.LIMIT, OrderType.STOP_LIMIT}),
        time_in_force=frozenset({TimeInForce.GTC, TimeInForce.IOC}),
        min_notional_usd=1.0,
        leverage_max=None,
        search_placeholder="Search e.g. Bitcoin, BTC-USD…",
        symbol_format_hint="BTC-USD",
        color_tone="from-indigo-500/20 to-cyan-500/10",
        client_cls=CoinbaseClient,
        build_client=build_client,
        normalise_symbol=normalise_symbol,
        test_connection=test_connection,
        score_universe=score_universe,
        fetch_market_data=fetch_market_data,
        # ── Wizard-driven connect UI (Commit 6: registry-driven frontend) ──
        connect_instructions_url="https://portal.cdp.coinbase.com/",
        connect_instructions_steps=(
            "Open the Coinbase Developer Platform (link above) and sign in.",
            "Create a new API key with Trade permissions. Copy the API Key Name.",
            "Download or copy the full PEM private key block (-----BEGIN … END-----).",
            "Paste the key name and the PEM block into Unitrader. Coinbase also accepts the full JSON blob via smart-paste.",
        ),
        credential_fields=(
            {
                "name": "api_key",
                "label": "API Key Name",
                "type": "text",
                "placeholder": "organizations/.../apiKeys/...",
                "required": True,
            },
            {
                "name": "api_secret",
                "label": "Private Key (PEM)",
                "type": "password",
                "placeholder": "-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----",
                "multiline": True,
                "required": True,
            },
        ),
    )


register(_build_spec())
