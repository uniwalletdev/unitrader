"""
src/exchanges/revolutx.py — Revolut X (crypto) registration.

Revolut X is the consumer-grade crypto exchange Revolut launched as a
standalone product. Authentication uses Ed25519 keypair signing (the
private key never leaves Unitrader's encrypted storage; the user only
ever sees the public key PEM, which they paste into Revolut X to mint
an API key).

The wire-protocol client (``RevolutXClient``) lives in
``src/integrations/exchange_client.py`` and is referenced here.

UX contract (matches the wizard):
    1. Wizard calls ``POST /api/exchanges/revolutx/generate-keypair``
       which generates a fresh Ed25519 pair, stores the private key
       PEM encrypted, and returns the public key PEM for display.
    2. User copies the public key into Revolut X → API Keys.
    3. Wizard calls ``POST /api/trading/exchange-keys`` with the
       Revolut X-issued API key. The backend pairs it with the
       previously generated private key and runs a signed
       ``GET /balances`` to verify.

Revolut X is **live-only** — there is no sandbox/paper environment, so
``paper_mode=PaperMode.NONE`` and ``supports_paper=False``.
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
    """Crypto only → ``BASE-QUOTE`` (e.g. ``BTC-USD``).

    Revolut X uses dash-separated symbols like every other consumer-grade
    crypto exchange. We strip slashes/underscores and default the quote
    to USD when none is supplied (matches the rest of the registry).
    """
    from src.integrations.market_data import classify_asset

    clean = symbol.upper().strip()

    parts = clean.split("/")
    if len(parts) == 3:
        clean = f"{parts[0]}/{parts[1]}"

    if classify_asset(clean) != "crypto":
        raise ValueError(f"Revolut X only supports crypto — cannot trade {symbol}")

    if "-" in clean:
        base, _, quote = clean.partition("-")
    elif "/" in clean:
        base, _, quote = clean.partition("/")
    elif "_" in clean:
        base, _, quote = clean.partition("_")
    else:
        base, quote = clean, "USD"

    base = base.strip()
    quote = (quote or "USD").strip() or "USD"

    # Revolut X quotes are USD/USDT/EUR/GBP — normalise stable-coin variants
    # back to USD when the caller passed e.g. "BTCUSDT".
    for s in ("USDT", "USDC", "BUSD"):
        if base.endswith(s) and len(base) > len(s):
            base = base[: -len(s)]

    return f"{base}-{quote}"


# ── Connection test ────────────────────────────────────────────────────────

async def test_connection(
    client: httpx.AsyncClient,  # unused — RevolutXClient owns its http client
    api_key: str,               # Revolut X API key
    api_secret: str,            # Ed25519 private key PEM (we store this)
    is_paper: bool,             # always False — Revolut X is live-only
) -> dict:
    """Cheap signed round-trip via ``GET /balances``.

    Returns ``{account_id, buying_power, currency}`` so the wizard can
    show the user the cash they're about to put under management.
    ``buying_power`` is the sum of fiat (USD/EUR/GBP) balances; crypto
    balances aren't priced here to keep the call latency down.
    """
    from src.integrations.exchange_client import RevolutXClient

    revx = RevolutXClient(api_key=api_key, api_secret=api_secret)
    try:
        info = await revx.verify_connection()
    finally:
        await revx.aclose()
    return {
        "account_id": info.get("account_id", "revolutx"),
        "buying_power": float(info.get("available_cash", 0.0) or 0.0),
        "currency": info.get("currency", "USD"),
    }


# ── Registration ───────────────────────────────────────────────────────────

def build_client(api_key: str, api_secret: str, *, is_paper: bool = False, **kwargs):
    from src.integrations.exchange_client import RevolutXClient

    # Revolut X has no paper environment; ignore is_paper from callers.
    return RevolutXClient(api_key=api_key, api_secret=api_secret)


def _build_spec() -> ExchangeSpec:
    from src.integrations.exchange_client import RevolutXClient

    return ExchangeSpec(
        id="revolutx",
        display_name="Revolut X",
        tagline="Crypto — Revolut's exchange",
        asset_classes=frozenset({AssetClass.CRYPTO}),
        primary_asset_class=AssetClass.CRYPTO,
        # Revolut X has no sandbox / paper environment — all orders hit
        # production. We rely on the synthetic paper layer elsewhere when
        # users want a paper experience on this venue.
        paper_mode=PaperMode.NONE,
        supports_paper=False,
        coming_soon=False,
        supports_fractional=True,
        order_types=frozenset({OrderType.MARKET, OrderType.LIMIT}),
        time_in_force=frozenset({TimeInForce.GTC}),
        min_notional_usd=1.0,
        leverage_max=None,
        search_placeholder="Search e.g. Bitcoin, BTC-USD…",
        symbol_format_hint="BTC-USD",
        color_tone="from-fuchsia-500/20 to-pink-500/10",
        client_cls=RevolutXClient,
        build_client=build_client,
        normalise_symbol=normalise_symbol,
        test_connection=test_connection,
        score_universe=None,
        fetch_market_data=None,
        # ── Wizard-driven connect UI ──────────────────────────────────
        # has_environment_toggle=True forces ExchangeConnections to route
        # Revolut X into the wizard modal even though there's no env
        # toggle to render — the wizard owns the 3-step keypair flow.
        has_environment_toggle=True,
        environment_options=(),
        environment_help_text={},
        connect_instructions_url="https://exchangerevolut.com",
        connect_instructions_steps=(
            "Click 'Generate my secure key' below — Unitrader creates an "
            "Ed25519 keypair and shows you the public key.",
            "Open Revolut X → Profile → API Keys → 'Add API Key' and paste "
            "the public key. Tick 'Spot view', 'Spot trade', and 'Allow usage via Revolut X MCP and CLI'.",
            "Copy the API Key Revolut X gives you, paste it back here, and "
            "we'll verify the connection with a signed call to /balances.",
        ),
        # The api_key field is the Revolut X-issued API key. The api_secret
        # field is hidden in the wizard for Revolut X — we generate it on
        # the server. Listed here so backend validation and the inline
        # form (if anyone surfaces it) stay registry-driven.
        credential_fields=(
            {
                "name": "api_key",
                "label": "Revolut X API Key",
                "type": "password",
                "placeholder": "Paste the API key from Revolut X here",
                "required": True,
            },
        ),
    )


register(_build_spec())
