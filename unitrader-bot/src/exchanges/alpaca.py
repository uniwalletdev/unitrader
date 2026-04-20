"""
src/exchanges/alpaca.py — Alpaca Markets (US equities + crypto) registration.

This module owns the per-venue metadata and thin dispatch helpers. The
wire-protocol client (``AlpacaClient``) remains in
``src/integrations/exchange_client.py`` and is referenced here.
"""
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


# ── Symbol normalisation ────────────────────────────────────────────────────

def normalise_symbol(symbol: str) -> str:
    """Stocks → plain ticker. Crypto → BASE/USD (Alpaca crypto format)."""
    from src.integrations.market_data import classify_asset

    clean = symbol.upper().strip()
    parts = clean.split("/")
    if len(parts) == 3:
        clean = f"{parts[0]}/{parts[1]}"

    asset_type = classify_asset(clean)
    if asset_type == "crypto":
        base = clean.split("/")[0].split("_")[0]
        for s in ("USDT", "USDC", "BUSD"):
            if base.endswith(s):
                base = base[: -len(s)]
        return f"{base}/USD"
    return clean.split("/")[0].split("_")[0]


# ── Connection test ────────────────────────────────────────────────────────

async def test_connection(
    client: httpx.AsyncClient, api_key: str, api_secret: str, is_paper: bool
) -> dict:
    base = "https://paper-api.alpaca.markets" if is_paper else "https://api.alpaca.markets"
    resp = await client.get(
        f"{base}/v2/account",
        headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret},
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "account_id": data.get("account_number"),
        "buying_power": float(data.get("buying_power", 0)),
        "currency": "USD",
    }


# ── Market data ────────────────────────────────────────────────────────────

async def fetch_market_data(symbol: str) -> dict:
    from src.integrations.market_data import (
        classify_asset,
        _fetch_alpaca_crypto,
        _fetch_alpaca_stock,
    )

    normalised = normalise_symbol(symbol)
    asset_type = classify_asset(normalised)
    if asset_type == "crypto":
        return await _fetch_alpaca_crypto(normalised)
    if asset_type == "stock":
        return await _fetch_alpaca_stock(normalised)
    raise ValueError(f"Unsupported asset type '{asset_type}' for Alpaca: {symbol}")


# ── Universe scoring ───────────────────────────────────────────────────────

async def score_universe() -> list[str]:
    from src.watchlists import STOCK_UNIVERSE, _score_stocks_alpaca

    return await _score_stocks_alpaca(STOCK_UNIVERSE)


# ── Registration ───────────────────────────────────────────────────────────

def build_client(api_key: str, api_secret: str, *, is_paper: bool = True, **kwargs):
    from src.integrations.exchange_client import AlpacaClient

    return AlpacaClient(
        api_key, api_secret, base_url=kwargs.get("base_url"), is_paper=is_paper
    )


def _build_spec() -> ExchangeSpec:
    from src.integrations.exchange_client import AlpacaClient

    return ExchangeSpec(
        id="alpaca",
        display_name="Alpaca",
        tagline="Stocks & ETFs",
        asset_classes=frozenset({AssetClass.STOCKS, AssetClass.CRYPTO}),
        primary_asset_class=AssetClass.STOCKS,
        paper_mode=PaperMode.NATIVE,
        supports_paper=True,
        supports_fractional=True,
        order_types=frozenset({OrderType.MARKET, OrderType.LIMIT, OrderType.STOP}),
        time_in_force=frozenset({TimeInForce.GTC, TimeInForce.DAY}),
        min_notional_usd=1.0,
        leverage_max=None,
        search_placeholder="Search e.g. Apple, AAPL, Tesla…",
        symbol_format_hint="AAPL",
        color_tone="from-sky-500/20 to-blue-500/10",
        client_cls=AlpacaClient,
        build_client=build_client,
        normalise_symbol=normalise_symbol,
        test_connection=test_connection,
        score_universe=score_universe,
        fetch_market_data=fetch_market_data,
    )


register(_build_spec())
