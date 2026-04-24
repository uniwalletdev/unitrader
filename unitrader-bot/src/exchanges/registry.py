"""
src/exchanges/registry.py — single source of truth for per-exchange metadata
and behavioural dispatch.

Each supported exchange has a module in this package (e.g. ``binance.py``)
that imports its wire-protocol client from ``src/integrations/exchange_client.py``
and calls :func:`register` with an :class:`ExchangeSpec`.

Callers should NEVER branch on exchange name directly. Instead:

    from src.exchanges.registry import get, all_specs

    spec = get("binance")
    client = spec.client_cls(api_key, api_secret)
    normalised = spec.normalise_symbol(raw_symbol)

Adding a new exchange = drop a new module in ``src/exchanges/`` and it
auto-registers via :mod:`src.exchanges` ``__init__`` import.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Enums — stable wire format for API + DB
# ─────────────────────────────────────────────

class AssetClass(str, Enum):
    STOCKS = "stocks"
    CRYPTO = "crypto"
    FOREX = "forex"
    OPTIONS = "options"
    ETFS = "etfs"          # Phase B1 — routed as stocks for risk/trading, tagged
                           # separately only for UI display (e.g. SPY, QQQ, GLD).
    COMMODITIES = "commodities"  # Phase B1 — first-class, minimal surface area:
                                 # one explanation template + 0.75x position
                                 # size multiplier until tuned with real data.


class PaperMode(str, Enum):
    NATIVE = "native"        # venue itself has a paper/sandbox API
    SYNTHETIC = "synthetic"  # we simulate fills locally
    NONE = "none"            # no paper support at all


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    GTC = "gtc"  # good-till-cancelled
    IOC = "ioc"  # immediate-or-cancel
    FOK = "fok"  # fill-or-kill
    DAY = "day"  # valid for the trading day only


# ─────────────────────────────────────────────
# Spec
# ─────────────────────────────────────────────

# Type aliases for callable fields. Kept loose (`Any` for client instances)
# to avoid a circular import with src/integrations/exchange_client.py.
NormaliseFn = Callable[[str], str]
TestConnectionFn = Callable[..., Awaitable[dict]]
ScoreUniverseFn = Callable[[], Awaitable[list[str]]]
FetchMarketDataFn = Callable[[str], Awaitable[dict]]
# build_client(api_key, api_secret, *, is_paper=True, **kwargs) -> BaseExchangeClient
BuildClientFn = Callable[..., Any]


@dataclass(frozen=True)
class ExchangeSpec:
    """Declarative description of a supported exchange.

    JSON-safe fields (everything except ``client_cls`` and the callables) are
    what the public ``/api/exchanges/capabilities`` endpoint serialises.
    """

    # ── Identity ───────────────────────────────
    id: str                                   # lower-case key, e.g. "binance"
    display_name: str                         # e.g. "Binance"
    tagline: str                              # short UI subtitle, e.g. "Crypto"

    # ── Asset & paper support ──────────────────
    asset_classes: frozenset[AssetClass]
    primary_asset_class: AssetClass
    paper_mode: PaperMode
    supports_paper: bool
    supports_fractional: bool

    # ── Order capabilities (surfaced in PR 3 UI) ──
    order_types: frozenset[OrderType]
    time_in_force: frozenset[TimeInForce]
    min_notional_usd: Optional[float]
    leverage_max: Optional[float]             # None = cash only

    # ── UI metadata (consumed by frontend via capabilities endpoint) ──
    search_placeholder: str
    symbol_format_hint: str                   # e.g. "BTC/USDT"
    color_tone: str                           # Tailwind gradient utilities

    # ── Behaviour (not serialised) ─────────────
    # A concrete BaseExchangeClient subclass (kept as Any to avoid cycle).
    client_cls: Any = field(repr=False)
    # Factory for a concrete client instance. Each adapter knows which kwargs
    # its client accepts (some want ``is_paper``, some ``account_id``, etc.).
    build_client: BuildClientFn = field(repr=False)
    # Canonicalise a user-entered symbol into the venue's wire format.
    normalise_symbol: NormaliseFn = field(repr=False)
    # Test a user-supplied key pair. Signature:
    #   await test_connection(http_client, api_key, api_secret_or_id, is_paper)
    # Returning {"account_id", "buying_power", "currency"}.
    test_connection: TestConnectionFn = field(repr=False)
    # Optional: fast momentum pre-scorer for the AI picks watchlist.
    score_universe: Optional[ScoreUniverseFn] = field(default=None, repr=False)
    # Optional: venue-specific market-data fetcher (ticker/24h/volume).
    fetch_market_data: Optional[FetchMarketDataFn] = field(default=None, repr=False)

    def to_public_dict(self) -> dict:
        """Serialisable projection for the public capabilities endpoint."""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "tagline": self.tagline,
            "asset_classes": sorted(a.value for a in self.asset_classes),
            "primary_asset_class": self.primary_asset_class.value,
            "paper_mode": self.paper_mode.value,
            "supports_paper": self.supports_paper,
            "supports_fractional": self.supports_fractional,
            "order_types": sorted(o.value for o in self.order_types),
            "time_in_force": sorted(t.value for t in self.time_in_force),
            "min_notional_usd": self.min_notional_usd,
            "leverage_max": self.leverage_max,
            "search_placeholder": self.search_placeholder,
            "symbol_format_hint": self.symbol_format_hint,
            "color_tone": self.color_tone,
        }


# ─────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────

_REGISTRY: dict[str, ExchangeSpec] = {}


def register(spec: ExchangeSpec) -> None:
    """Register an exchange. Duplicate ids log a warning and replace the entry.

    Each per-exchange module calls this exactly once at import time.
    """
    key = spec.id.lower()
    if key in _REGISTRY:
        logger.warning("ExchangeSpec '%s' re-registered; replacing previous entry", key)
    _REGISTRY[key] = spec


def get(exchange_id: str) -> ExchangeSpec:
    """Return the spec for ``exchange_id`` (case-insensitive)."""
    try:
        return _REGISTRY[exchange_id.lower()]
    except KeyError as exc:
        raise KeyError(
            f"Unsupported exchange: '{exchange_id}'. "
            f"Registered: {sorted(_REGISTRY)}"
        ) from exc


def get_optional(exchange_id: str) -> Optional[ExchangeSpec]:
    """Non-raising lookup."""
    return _REGISTRY.get(exchange_id.lower())


def all_specs() -> list[ExchangeSpec]:
    """Return every registered spec, in insertion order."""
    return list(_REGISTRY.values())


def all_ids() -> list[str]:
    return list(_REGISTRY.keys())


# Test-only helpers (not part of the public contract) ─────────────────────
def _clear() -> None:  # pragma: no cover — used by tests
    _REGISTRY.clear()


def _unregister(exchange_id: str) -> None:  # pragma: no cover
    _REGISTRY.pop(exchange_id.lower(), None)
