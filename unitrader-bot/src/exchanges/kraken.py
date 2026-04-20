"""src/exchanges/kraken.py — Kraken (crypto) registration."""
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
    """Crypto only → BASEUSD with Kraken quirks (BTC→XBT, DOGE→XDG)."""
    from src.integrations.market_data import classify_asset

    clean = symbol.upper().strip()
    parts = clean.split("/")
    if len(parts) == 3:
        clean = f"{parts[0]}/{parts[1]}"

    if classify_asset(clean) != "crypto":
        raise ValueError(f"Kraken only supports crypto — cannot trade {symbol}")

    base = clean.split("/")[0].split("_")[0].split("-")[0]
    for s in ("USDT", "USDC", "BUSD", "USD"):
        if base.endswith(s):
            base = base[: -len(s)]
    kb = {"BTC": "XBT", "DOGE": "XDG"}.get(base, base)
    return f"{kb}USD"


async def test_connection(
    client: httpx.AsyncClient,  # unused — KrakenClient owns its http client
    api_key: str,
    api_secret: str,
    is_paper: bool,
) -> dict:
    from src.integrations.kraken_client import KrakenClient

    k = KrakenClient(api_key, api_secret)
    try:
        balance = await k.get_account_balance()
        return {"account_id": "kraken", "buying_power": balance, "currency": "USD"}
    finally:
        await k.aclose()


async def fetch_market_data(symbol: str) -> dict:
    from src.integrations.market_data import _fetch_kraken

    return await _fetch_kraken(normalise_symbol(symbol))


async def score_universe() -> list[str]:
    from src.watchlists import KRAKEN_UNIVERSE, _score_crypto_kraken

    return await _score_crypto_kraken(KRAKEN_UNIVERSE)


def build_client(api_key: str, api_secret: str, *, is_paper: bool = True, **kwargs):
    from src.integrations.kraken_client import KrakenClient

    return KrakenClient(api_key, api_secret)


def _build_spec() -> ExchangeSpec:
    # KrakenClient lives in its own module — import lazily to avoid a cycle
    # with exchange_client.py that already imports kraken_client lazily.
    from src.integrations.kraken_client import KrakenClient

    return ExchangeSpec(
        id="kraken",
        display_name="Kraken",
        tagline="Crypto",
        asset_classes=frozenset({AssetClass.CRYPTO}),
        primary_asset_class=AssetClass.CRYPTO,
        paper_mode=PaperMode.SYNTHETIC,
        supports_paper=False,
        supports_fractional=True,
        order_types=frozenset({OrderType.MARKET, OrderType.LIMIT, OrderType.STOP_LIMIT}),
        time_in_force=frozenset({TimeInForce.GTC, TimeInForce.IOC}),
        min_notional_usd=1.0,
        leverage_max=None,
        search_placeholder="Search e.g. Bitcoin, XBTUSD…",
        symbol_format_hint="XBTUSD",
        color_tone="from-violet-500/20 to-purple-500/10",
        client_cls=KrakenClient,
        build_client=build_client,
        normalise_symbol=normalise_symbol,
        test_connection=test_connection,
        score_universe=score_universe,
        fetch_market_data=fetch_market_data,
    )


register(_build_spec())
