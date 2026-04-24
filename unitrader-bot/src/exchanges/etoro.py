"""
src/exchanges/etoro.py — eToro registration (stocks + crypto + ETFs + commodities).

This module owns the per-venue metadata and thin dispatch helpers. The
wire-protocol client (``EtoroClient``) lives in
``src/integrations/etoro_client.py`` and is referenced here.

Importing this module (via :mod:`src.exchanges` __init__) side-effects a
``register(spec)`` call into the central registry. The spec's
``test_connection`` is what ``/api/exchanges/test-connection`` invokes for
eToro users, so the connect flow is unchanged from Alpaca/Coinbase.
"""
from __future__ import annotations

import logging

import httpx

from src.exchanges.registry import (
    AssetClass,
    ExchangeSpec,
    OrderType,
    PaperMode,
    TimeInForce,
    register,
)

logger = logging.getLogger(__name__)


# ── Symbol normalisation ────────────────────────────────────────────────────

def normalise_symbol(symbol: str) -> str:
    """eToro accepts plain tickers (AAPL, BTC, SPY, GOLD). Strip decoration."""
    clean = symbol.upper().strip()
    # Coinbase-style crypto hyphens and Alpaca-style slashes both need to
    # reduce to the bare base ticker for eToro's search endpoint.
    for sep in ("/", "-"):
        if sep in clean:
            clean = clean.split(sep)[0]
    for suffix in ("USDT", "USDC", "BUSD", "USD"):
        # Only strip if it looks like a quote-currency suffix on crypto.
        if clean.endswith(suffix) and len(clean) > len(suffix):
            candidate = clean[: -len(suffix)]
            # Don't strip e.g. 'GOLD' to 'GO'
            if len(candidate) >= 2:
                clean = candidate
                break
    return clean


# ── Connection test ────────────────────────────────────────────────────────

async def test_connection(
    client: httpx.AsyncClient,  # unused; EtoroClient manages its own httpx session
    api_key: str,               # user_key (x-user-key)
    api_secret: str,            # api_key_id (informational)
    is_paper: bool,             # True ⇔ demo environment
) -> dict:
    """Cheap round-trip that also returns account metadata the UI needs.

    Matches the spec contract returning ``{account_id, buying_power, currency,
    username, environment}``. ``buying_power`` is populated from the
    portfolio's available cash.
    """
    from src.integrations.etoro_client import EtoroClient

    eto = EtoroClient(api_key=api_key, api_secret=api_secret, is_paper=is_paper)
    try:
        info = await eto.verify_connection()
    finally:
        await eto.aclose()
    return {
        "account_id": info.get("account_id", ""),
        "buying_power": float(info.get("available_cash", 0.0)),
        "currency": info.get("currency", "USD"),
        "username": info.get("username", ""),
        "environment": info.get("environment", "demo" if is_paper else "real"),
    }


# ── Registration ───────────────────────────────────────────────────────────

def build_client(api_key: str, api_secret: str, *, is_paper: bool = True, **kwargs):
    from src.integrations.etoro_client import EtoroClient

    return EtoroClient(
        api_key=api_key,
        api_secret=api_secret,
        is_paper=is_paper,
        public_api_key=kwargs.get("public_api_key"),
    )


def _build_spec() -> ExchangeSpec:
    from src.integrations.etoro_client import EtoroClient

    return ExchangeSpec(
        id="etoro",
        display_name="eToro",
        tagline="Stocks, crypto, ETFs & commodities — one account",
        asset_classes=frozenset({
            AssetClass.STOCKS,
            AssetClass.CRYPTO,
            AssetClass.ETFS,
            AssetClass.COMMODITIES,
        }),
        primary_asset_class=AssetClass.STOCKS,
        paper_mode=PaperMode.NATIVE,      # eToro has a real Demo environment
        supports_paper=True,
        supports_fractional=True,
        order_types=frozenset({OrderType.MARKET, OrderType.LIMIT}),
        time_in_force=frozenset({TimeInForce.GTC, TimeInForce.DAY}),
        min_notional_usd=10.0,             # eToro's typical minimum is $10
        leverage_max=None,                 # We trade cash accounts only for safety
        search_placeholder="Search stocks, crypto, ETFs, commodities…",
        symbol_format_hint="AAPL · BTC · SPY · GOLD",
        color_tone="from-emerald-500/20 to-lime-500/10",
        client_cls=EtoroClient,
        build_client=build_client,
        normalise_symbol=normalise_symbol,
        test_connection=test_connection,
        score_universe=None,              # Not yet — Phase B2/3 work
        fetch_market_data=None,           # Not yet — Phase B2/3 work
    )


register(_build_spec())
