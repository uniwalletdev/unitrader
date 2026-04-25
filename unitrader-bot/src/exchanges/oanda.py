"""src/exchanges/oanda.py — OANDA v20 (forex / CFDs) registration."""
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
    """Forex only → EUR_USD wire format."""
    from src.integrations.market_data import classify_asset

    clean = symbol.upper().strip()
    parts = clean.split("/")
    if len(parts) == 3:
        clean = f"{parts[0]}/{parts[1]}"

    if classify_asset(clean) != "forex":
        raise ValueError(f"OANDA only supports forex — cannot trade {symbol}")

    return clean.replace("/", "_")


async def test_connection(
    client: httpx.AsyncClient,
    api_key: str,
    api_secret_or_account_id: str,
    is_paper: bool,
) -> dict:
    """For OANDA the "secret" slot carries the account_id — pre-existing
    convention in routers/exchanges.py before this refactor. Kept as-is.
    
    Routes to practice endpoint (fxpractice) for paper accounts and live
    endpoint (fxtrade) for production accounts.
    """
    account_id = api_secret_or_account_id
    base_url = "https://api-fxpractice.oanda.com" if is_paper else "https://api-fxtrade.oanda.com"
    resp = await client.get(
        f"{base_url}/v3/accounts/{account_id}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    account = data.get("account", {})
    return {
        "account_id": account.get("id"),
        "buying_power": float(account.get("unrealizedPL", 0))
        + float(account.get("balance", 0)),
        "currency": account.get("currency", "GBP"),
    }


async def fetch_market_data(symbol: str) -> dict:
    from src.integrations.market_data import _fetch_oanda

    return await _fetch_oanda(normalise_symbol(symbol))


def build_client(api_key: str, api_secret: str, *, is_paper: bool = True, **kwargs):
    from src.integrations.exchange_client import OandaClient

    # For OANDA the "api_secret" slot carries nothing; callers pass the
    # account id via kwargs.
    return OandaClient(api_key, api_secret, account_id=kwargs.get("account_id"))


def _build_spec() -> ExchangeSpec:
    from src.integrations.exchange_client import OandaClient

    return ExchangeSpec(
        id="oanda",
        display_name="Oanda",
        tagline="Forex",
        asset_classes=frozenset({AssetClass.FOREX}),
        primary_asset_class=AssetClass.FOREX,
        paper_mode=PaperMode.NATIVE,
        supports_paper=True,  # OANDA "practice" is a true paper environment
        supports_fractional=True,
        order_types=frozenset({OrderType.MARKET, OrderType.LIMIT, OrderType.STOP}),
        time_in_force=frozenset({TimeInForce.GTC, TimeInForce.IOC, TimeInForce.FOK}),
        min_notional_usd=None,
        leverage_max=50.0,
        search_placeholder="Search e.g. Euro, EUR_USD…",
        symbol_format_hint="EUR_USD",
        color_tone="from-emerald-500/20 to-teal-500/10",
        client_cls=OandaClient,
        build_client=build_client,
        normalise_symbol=normalise_symbol,
        test_connection=test_connection,
        # No pre-scorer for forex today; AI picks scores the universe directly.
        score_universe=None,
        fetch_market_data=fetch_market_data,
        # ── Wizard-driven connect UI (Commit 6: registry-driven frontend) ──
        connect_instructions_url="https://www.oanda.com/account/",
        connect_instructions_steps=(
            "Log in to OANDA (fxTrade) and open Manage API Access → Generate.",
            "Copy your Personal Access Token.",
            "Note your Account ID (v20 format, e.g. 001-004-1234567-001).",
            "Paste both into Unitrader. Practice accounts use the fxTrade-practice environment automatically.",
        ),
        credential_fields=(
            {
                "name": "api_key",
                "label": "API Token",
                "type": "password",
                "placeholder": "Your OANDA API token",
                "required": True,
            },
            {
                "name": "api_secret",
                "label": "Account ID",
                "type": "text",
                "placeholder": "001-004-1234567-001",
                "required": True,
            },
        ),
    )


register(_build_spec())
