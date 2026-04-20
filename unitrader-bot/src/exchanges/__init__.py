"""
src/exchanges — per-exchange metadata + dispatch registry.

Importing this package auto-registers every supported exchange by importing
each adapter module (which calls :func:`registry.register` at module scope).

Callers should use :mod:`src.exchanges.registry` as the public API:

    from src.exchanges.registry import get, all_specs, all_ids
"""
from __future__ import annotations

# Importing the adapter modules has the side-effect of populating the registry.
# Order is deterministic — it shapes the order `all_specs()` returns to the UI.
from . import alpaca  # noqa: F401
from . import binance  # noqa: F401
from . import coinbase  # noqa: F401
from . import kraken  # noqa: F401
from . import oanda  # noqa: F401

from .registry import (  # noqa: F401  (re-exports)
    AssetClass,
    ExchangeSpec,
    OrderType,
    PaperMode,
    TimeInForce,
    all_ids,
    all_specs,
    get,
    get_optional,
    register,
)
