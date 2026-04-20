"""
tests/test_exchange_registry.py — Unit tests for the exchange capabilities registry.

Covers:
  • Registry completeness (all known exchanges registered)
  • Factory dispatch via registry
  • normalise_symbol round-trip through registry
  • Back-compat dicts are in sync with registry
  • Capabilities endpoint serialisation shape
  • Adding a fake exchange without touching core code
  • fetch_market_data / score_universe callables present
  • build_client returns correct type
  • to_public_dict excludes callables

Run:
    pytest tests/test_exchange_registry.py -v
"""
from __future__ import annotations

import pytest

# Force registry population
import src.exchanges  # noqa: F401

from src.exchanges.registry import (
    AssetClass,
    ExchangeSpec,
    OrderType,
    PaperMode,
    TimeInForce,
    _clear,
    _unregister,
    all_ids,
    all_specs,
    get,
    get_optional,
    register,
)


EXPECTED_IDS = {"alpaca", "binance", "coinbase", "kraken", "oanda"}


# ─────────────────────────────────────────────
# 1. Registry completeness
# ─────────────────────────────────────────────

def test_registry_has_all_known_exchanges():
    ids = set(all_ids())
    assert ids == EXPECTED_IDS, f"Expected {EXPECTED_IDS}, got {ids}"


def test_all_specs_returns_five():
    specs = all_specs()
    assert len(specs) == 5
    assert all(isinstance(s, ExchangeSpec) for s in specs)


# ─────────────────────────────────────────────
# 2. Factory dispatch
# ─────────────────────────────────────────────

def test_factory_dispatches_via_registry():
    from src.integrations.exchange_client import get_exchange_client, BinanceClient

    client = get_exchange_client("binance", "test_key", "test_secret")
    assert isinstance(client, BinanceClient)


def test_factory_raises_on_unknown():
    from src.integrations.exchange_client import get_exchange_client

    with pytest.raises(ValueError, match="Unsupported exchange"):
        get_exchange_client("foobar_exchange", "k", "s")


# ─────────────────────────────────────────────
# 3. normalise_symbol via registry
# ─────────────────────────────────────────────

@pytest.mark.parametrize("exchange,symbol,expected", [
    ("alpaca", "BTC/USD", "BTC/USD"),
    ("alpaca", "AAPL", "AAPL"),
    ("binance", "BTCUSDT", "BTCUSDT"),
    ("binance", "ETH/USDT", "ETHUSDT"),
    ("coinbase", "BTC-USD", "BTC-USD"),
    ("coinbase", "BTC/USD", "BTC-USD"),
    ("kraken", "BTC/USD", "XBTUSD"),
    ("kraken", "DOGE/USD", "XDGUSD"),
    ("oanda", "EUR/USD", "EUR_USD"),
])
def test_normalise_symbol_parametrised(exchange, symbol, expected):
    from src.integrations.market_data import normalise_symbol

    result = normalise_symbol(symbol, exchange)
    assert result == expected, f"{exchange}: normalise({symbol!r}) → {result!r}, expected {expected!r}"


# ─────────────────────────────────────────────
# 4. Back-compat dicts are views of registry
# ─────────────────────────────────────────────

def test_exchange_capabilities_matches_registry():
    from src.integrations.market_data import EXCHANGE_CAPABILITIES

    for spec in all_specs():
        caps = EXCHANGE_CAPABILITIES[spec.id]
        assert caps["stocks"] == (AssetClass.STOCKS in spec.asset_classes)
        assert caps["crypto"] == (AssetClass.CRYPTO in spec.asset_classes)
        assert caps["forex"] == (AssetClass.FOREX in spec.asset_classes)


def test_market_context_primary_matches_registry():
    from src.market_context import EXCHANGE_PRIMARY_ASSET_CLASS

    for spec in all_specs():
        expected = spec.primary_asset_class.value
        actual = EXCHANGE_PRIMARY_ASSET_CLASS[spec.id].value
        assert actual == expected, f"{spec.id}: {actual} != {expected}"


def test_market_context_paper_mode_matches_registry():
    from src.market_context import EXCHANGE_PAPER_MODE

    for spec in all_specs():
        actual = EXCHANGE_PAPER_MODE[spec.id].value
        # Registry PaperMode.NONE maps to PaperModeType.SYNTHETIC
        expected = spec.paper_mode.value if spec.paper_mode.value != "none" else "synthetic"
        assert actual == expected, f"{spec.id}: {actual} != {expected}"


# ─────────────────────────────────────────────
# 5. to_public_dict shape (no callables leak)
# ─────────────────────────────────────────────

def test_to_public_dict_excludes_callables():
    spec = get("binance")
    pub = spec.to_public_dict()
    # Must have these JSON-safe keys
    for k in ("id", "display_name", "tagline", "asset_classes", "order_types",
              "time_in_force", "search_placeholder", "symbol_format_hint", "color_tone"):
        assert k in pub, f"Missing key {k}"
    # Must NOT have any callable references
    for k in ("client_cls", "build_client", "normalise_symbol",
              "test_connection", "score_universe", "fetch_market_data"):
        assert k not in pub, f"Callable key {k} leaked into public dict"


# ─────────────────────────────────────────────
# 6. Dynamic registration (no core edits needed)
# ─────────────────────────────────────────────

def test_adding_exchange_requires_no_core_edits():
    """Register a fake exchange, verify factory/normalise pick it up."""

    class FakeClient:
        def __init__(self, k, s):
            pass

    fake_spec = ExchangeSpec(
        id="testex",
        display_name="TestEx",
        tagline="Testing",
        asset_classes=frozenset({AssetClass.CRYPTO}),
        primary_asset_class=AssetClass.CRYPTO,
        paper_mode=PaperMode.NONE,
        supports_paper=False,
        supports_fractional=False,
        order_types=frozenset({OrderType.MARKET}),
        time_in_force=frozenset({TimeInForce.GTC}),
        min_notional_usd=None,
        leverage_max=None,
        search_placeholder="Search…",
        symbol_format_hint="TEST",
        color_tone="from-gray-500/20 to-gray-500/10",
        client_cls=FakeClient,
        build_client=lambda k, s, **kw: FakeClient(k, s),
        normalise_symbol=lambda sym: sym.upper(),
        test_connection=None,  # type: ignore[arg-type]
    )
    register(fake_spec)
    try:
        assert "testex" in all_ids()
        assert get("testex").display_name == "TestEx"
        assert get("testex").normalise_symbol("foo") == "FOO"
    finally:
        _unregister("testex")
    assert "testex" not in all_ids()


# ─────────────────────────────────────────────
# 7. build_client type check
# ─────────────────────────────────────────────

def test_build_client_returns_correct_type():
    """Each adapter's build_client should produce an instance of client_cls."""
    for spec in all_specs():
        client = spec.build_client("k", "s", is_paper=True)
        assert isinstance(client, spec.client_cls), (
            f"{spec.id}: build_client returned {type(client).__name__}, "
            f"expected {spec.client_cls.__name__}"
        )


# ─────────────────────────────────────────────
# 8. All callables present
# ─────────────────────────────────────────────

def test_all_specs_have_required_callables():
    for spec in all_specs():
        assert callable(spec.normalise_symbol), f"{spec.id} missing normalise_symbol"
        assert callable(spec.build_client), f"{spec.id} missing build_client"
        assert callable(spec.test_connection), f"{spec.id} missing test_connection"
        assert callable(spec.fetch_market_data), f"{spec.id} missing fetch_market_data"
        # score_universe is optional (oanda has None)
        if spec.id != "oanda":
            assert callable(spec.score_universe), f"{spec.id} missing score_universe"


# ─────────────────────────────────────────────
# 9. get() raises KeyError for unknown
# ─────────────────────────────────────────────

def test_get_raises_key_error():
    with pytest.raises(KeyError, match="Unsupported exchange"):
        get("nonexistent")


def test_get_optional_returns_none():
    assert get_optional("nonexistent") is None
