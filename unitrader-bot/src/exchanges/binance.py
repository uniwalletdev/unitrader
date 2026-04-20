"""src/exchanges/binance.py — Binance (spot crypto) registration."""
from __future__ import annotations

import hashlib
import hmac
import time

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
    """Crypto only → BASEUSDT wire format."""
    from src.integrations.market_data import classify_asset

    clean = symbol.upper().strip()
    parts = clean.split("/")
    if len(parts) == 3:
        clean = f"{parts[0]}/{parts[1]}"

    if classify_asset(clean) != "crypto":
        raise ValueError(f"Binance only supports crypto — cannot trade {symbol}")

    base = clean.split("/")[0].split("_")[0]
    for s in ("USDT", "USDC", "BUSD", "USD"):
        if base.endswith(s):
            base = base[: -len(s)]
    return f"{base}USDT"


async def test_connection(
    client: httpx.AsyncClient, api_key: str, api_secret: str, is_paper: bool
) -> dict:
    timestamp = int(time.time() * 1000)
    query = f"timestamp={timestamp}"
    sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    resp = await client.get(
        "https://api.binance.com/api/v3/account",
        headers={"X-MBX-APIKEY": api_key},
        params={"timestamp": timestamp, "signature": sig},
    )
    resp.raise_for_status()
    data = resp.json()
    balances = data.get("balances", [])
    usdt = next((float(b["free"]) for b in balances if b["asset"] == "USDT"), 0.0)
    return {
        "account_id": str(data.get("accountId")),
        "buying_power": usdt,
        "currency": "USDT",
    }


async def fetch_market_data(symbol: str) -> dict:
    """Normalise then hit the existing binance public 24hr ticker helper."""
    from src.integrations.market_data import _fetch_binance

    return await _fetch_binance(normalise_symbol(symbol))


async def score_universe() -> list[str]:
    from src.watchlists import CRYPTO_UNIVERSE, _score_crypto_binance

    return await _score_crypto_binance(
        [s.replace("-USD", "USDT") for s in CRYPTO_UNIVERSE]
    )


def build_client(api_key: str, api_secret: str, *, is_paper: bool = True, **kwargs):
    from src.integrations.exchange_client import BinanceClient

    return BinanceClient(api_key, api_secret, base_url=kwargs.get("base_url"))


def _build_spec() -> ExchangeSpec:
    from src.integrations.exchange_client import BinanceClient

    return ExchangeSpec(
        id="binance",
        display_name="Binance",
        tagline="Crypto",
        asset_classes=frozenset({AssetClass.CRYPTO}),
        primary_asset_class=AssetClass.CRYPTO,
        paper_mode=PaperMode.SYNTHETIC,
        supports_paper=True,
        supports_fractional=True,
        order_types=frozenset({OrderType.MARKET, OrderType.LIMIT, OrderType.STOP_LIMIT}),
        time_in_force=frozenset({TimeInForce.GTC, TimeInForce.IOC, TimeInForce.FOK}),
        min_notional_usd=10.0,
        leverage_max=None,
        search_placeholder="Search e.g. Bitcoin, ETHUSDT…",
        symbol_format_hint="BTC/USDT",
        color_tone="from-amber-500/20 to-yellow-500/10",
        client_cls=BinanceClient,
        build_client=build_client,
        normalise_symbol=normalise_symbol,
        test_connection=test_connection,
        score_universe=score_universe,
        fetch_market_data=fetch_market_data,
    )


register(_build_spec())
