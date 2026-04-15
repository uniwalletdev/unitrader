from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import TradingAccount

logger = logging.getLogger(__name__)


class Exchange(str, Enum):
    ALPACA = "alpaca"
    COINBASE = "coinbase"
    BINANCE = "binance"
    OANDA = "oanda"
    KRAKEN = "kraken"


class AssetClass(str, Enum):
    STOCKS = "stocks"
    CRYPTO = "crypto"
    FOREX = "forex"


EXCHANGE_ASSET_CLASSES: dict[Exchange, set[AssetClass]] = {
    # Alpaca supports both stocks and crypto market data; execution still depends on your
    # connected account and TRADING_MODE elsewhere.
    Exchange.ALPACA: {AssetClass.STOCKS, AssetClass.CRYPTO},
    Exchange.COINBASE: {AssetClass.CRYPTO},
    Exchange.BINANCE: {AssetClass.CRYPTO},
    Exchange.KRAKEN: {AssetClass.CRYPTO},
    Exchange.OANDA: {AssetClass.FOREX},
}


CRYPTO_BASES = {
    "BTC",
    "XBT",
    "ETH",
    "SOL",
    "DOGE",
    "XDG",
    "ADA",
    "XRP",
    "AVAX",
    "MATIC",
    "LINK",
    "DOT",
    "ATOM",
    "LTC",
    "BCH",
    "UNI",
    "AAVE",
    "BNB",
}

FOREX_PAIRS = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EUR_USD", "GBP_USD"}

STOCK_PATTERN = re.compile(r"^[A-Z]{1,5}$")


class ExchangeAssetClassError(Exception):
    def __init__(self, exchange: Exchange, symbol: str, asset_class: AssetClass):
        self.exchange = exchange
        self.symbol = symbol
        self.asset_class = asset_class
        self.error_code = f"{asset_class.value}_not_supported_on_{exchange.value}"
        super().__init__(self.error_code)


def classify_symbol(symbol: str) -> AssetClass:
    s = symbol.strip().upper()
    base = (
        s.replace("-USD", "")
        .replace("USDT", "")
        .replace("BUSD", "")
        .replace("-", "")
        .replace("/", "")
        .replace("_", "")
    )
    if base in CRYPTO_BASES or s.endswith("-USD") or s.endswith("USDT") or s.endswith("BUSD") or "/" in s:
        return AssetClass.CRYPTO
    if "_" in s or s.replace("/", "") in FOREX_PAIRS:
        return AssetClass.FOREX
    if STOCK_PATTERN.match(s):
        return AssetClass.STOCKS
    return AssetClass.STOCKS  # conservative fallback


def normalize_symbol(symbol: str, exchange: Exchange) -> str:
    s = symbol.strip().upper()
    asset_class = classify_symbol(s)

    base = (
        s.replace("-USD", "")
        .replace("USDT", "")
        .replace("BUSD", "")
        .replace("-", "")
        .replace("/", "")
        .replace("_", "")
    )

    if exchange == Exchange.COINBASE:
        if asset_class != AssetClass.CRYPTO:
            raise ExchangeAssetClassError(exchange, symbol, asset_class)
        return f"{base}-USD"

    if exchange == Exchange.BINANCE:
        if asset_class != AssetClass.CRYPTO:
            raise ExchangeAssetClassError(exchange, symbol, asset_class)
        return f"{base}USDT"

    if exchange == Exchange.KRAKEN:
        if asset_class != AssetClass.CRYPTO:
            raise ExchangeAssetClassError(exchange, symbol, asset_class)
        kraken_map = {
            "BTC": "XBT",
            "DOGE": "XDG",
        }
        kb = kraken_map.get(base, base)
        return f"{kb}USD"

    if exchange == Exchange.ALPACA:
        if asset_class == AssetClass.STOCKS:
            return base  # AAPL, MSFT etc
        if asset_class == AssetClass.CRYPTO:
            # Keep Alpaca-friendly crypto format.
            return f"{base}/USD"
        raise ExchangeAssetClassError(exchange, symbol, asset_class)

    if exchange == Exchange.OANDA:
        if asset_class != AssetClass.FOREX:
            raise ExchangeAssetClassError(exchange, symbol, asset_class)
        return s  # caller may normalise EUR_USD / EURUSD

    return s


@dataclass(frozen=True)
class MarketContext:
    exchange: Exchange
    is_paper: bool
    trading_account_id: str
    user_id: str

    def supports(self, asset_class: AssetClass) -> bool:
        return asset_class in EXCHANGE_ASSET_CLASSES[self.exchange]

    def assert_supports(self, symbol: str) -> None:
        asset_class = classify_symbol(symbol)
        if not self.supports(asset_class):
            raise ExchangeAssetClassError(self.exchange, symbol, asset_class)

    def to_snapshot(self) -> dict:
        return {
            "exchange": self.exchange.value,
            "is_paper": self.is_paper,
            "trading_account_id": self.trading_account_id,
        }


async def resolve_market_context(
    db: AsyncSession,
    user_id: str,
    trading_account_id: Optional[str] = None,
) -> MarketContext:
    """
    Single authoritative resolver. Used by REST endpoints, WebSocket, and agents.
    Raises HTTP 404 if account not found, not owned by user, or inactive.
    Raises HTTP 400 if exchange value is unrecognised or trading_account_id missing.
    """
    if not trading_account_id:
        raise HTTPException(status_code=400, detail={"code": "trading_account_id_required"})

    result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.id == trading_account_id,
            TradingAccount.user_id == user_id,
            TradingAccount.is_active == True,  # noqa: E712
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail={"code": "trading_account_not_found"})

    try:
        exchange = Exchange((account.exchange or "").lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "unsupported_exchange", "exchange": account.exchange},
        )

    return MarketContext(
        exchange=exchange,
        is_paper=bool(account.is_paper),
        trading_account_id=trading_account_id,
        user_id=user_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAPER MODE TYPE
# ─────────────────────────────────────────────────────────────────────────────

class PaperModeType(str, Enum):
    NATIVE = "native"        # Exchange has real paper API (Alpaca)
    SYNTHETIC = "synthetic"  # We simulate the fill


# ─────────────────────────────────────────────────────────────────────────────
# EXCHANGE → ASSET CLASS DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────

# Primary asset class for each exchange (used when creating accounts).
EXCHANGE_PRIMARY_ASSET_CLASS: dict[str, AssetClass] = {
    "alpaca": AssetClass.STOCKS,
    "coinbase": AssetClass.CRYPTO,
    "binance": AssetClass.CRYPTO,
    "kraken": AssetClass.CRYPTO,
    "oanda": AssetClass.FOREX,
}

EXCHANGE_PAPER_MODE: dict[str, PaperModeType] = {
    "alpaca": PaperModeType.NATIVE,
    "coinbase": PaperModeType.SYNTHETIC,
    "binance": PaperModeType.SYNTHETIC,
    "kraken": PaperModeType.SYNTHETIC,
    "oanda": PaperModeType.SYNTHETIC,
}


def set_account_defaults(exchange: str) -> dict:
    """Return paper_mode_type and asset_class for a given exchange.

    Called at TradingAccount creation time.
    """
    ex = exchange.lower()
    return {
        "paper_mode_type": EXCHANGE_PAPER_MODE.get(ex, PaperModeType.SYNTHETIC).value,
        "asset_class": EXCHANGE_PRIMARY_ASSET_CLASS.get(ex, AssetClass.STOCKS).value,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION VENUE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExecutionVenue:
    """Resolved outcome of 'where should this trade go?'"""
    exchange: Exchange
    asset_class: AssetClass
    paper_mode_type: PaperModeType
    is_paper: bool
    trading_account_id: str
    display_label: str  # e.g. "Stocks · Paper" or "Crypto · Live"


# Priority order when no asset_class preference given
_EXCHANGE_PRIORITY = {
    Exchange.ALPACA: 0,
    Exchange.COINBASE: 1,
    Exchange.BINANCE: 2,
    Exchange.KRAKEN: 3,
    Exchange.OANDA: 4,
}


async def resolve_execution_venue(
    user_id: str,
    asset_class: Optional[AssetClass] = None,
    db: AsyncSession | None = None,
    trust_ladder_stage: int | None = None,
) -> ExecutionVenue:
    """Single source of truth: given a user and optionally an asset class,
    return the exchange, paper mode, and account to use.

    ``trust_ladder_stage`` overrides the is_paper decision:
      stages 1-2 → paper, stages 3-4 → live.
    If not provided the account's own ``is_paper`` flag is used.

    Raises ``ExchangeAssetClassError`` if no connected exchange serves
    the requested asset class.
    """
    if db is None:
        raise ValueError("db session is required for resolve_execution_venue")

    # ── Fetch all active accounts ───────────────────────────────────────────
    result = await db.execute(
        select(TradingAccount)
        .where(
            TradingAccount.user_id == user_id,
            TradingAccount.is_active == True,  # noqa: E712
        )
        .order_by(TradingAccount.created_at.asc())
    )
    accounts = list(result.scalars().all())

    if not accounts:
        raise ExchangeAssetClassError(
            Exchange.ALPACA,
            "",
            asset_class or AssetClass.STOCKS,
        )

    # ── Filter by asset_class if requested ──────────────────────────────────
    if asset_class is not None:
        filtered = [
            a for a in accounts
            if asset_class in EXCHANGE_ASSET_CLASSES.get(
                Exchange((a.exchange or "").lower()), set()
            )
        ]
        if not filtered:
            raise ExchangeAssetClassError(
                Exchange.ALPACA,
                "",
                asset_class,
            )
        accounts = filtered

    # ── Sort by exchange priority ───────────────────────────────────────────
    def _priority(acct: TradingAccount) -> int:
        try:
            return _EXCHANGE_PRIORITY[Exchange(acct.exchange.lower())]
        except (ValueError, KeyError):
            return 99

    accounts.sort(key=_priority)
    account = accounts[0]

    # ── Resolve fields ──────────────────────────────────────────────────────
    exchange = Exchange(account.exchange.lower())
    # Derive asset class: use the requested class if supported, otherwise
    # fall back to the account's stored value or the exchange's primary class.
    supported = EXCHANGE_ASSET_CLASSES.get(exchange, set())
    if asset_class is not None and asset_class in supported:
        acct_asset_class = asset_class
    else:
        acct_asset_class = AssetClass(
            getattr(account, "asset_class", None)
            or EXCHANGE_PRIMARY_ASSET_CLASS.get(account.exchange.lower(), AssetClass.STOCKS).value
        )
    paper_mode_type = PaperModeType(
        getattr(account, "paper_mode_type", None)
        or EXCHANGE_PAPER_MODE.get(account.exchange.lower(), PaperModeType.SYNTHETIC).value
    )

    if trust_ladder_stage is not None:
        is_paper = trust_ladder_stage <= 2
    else:
        is_paper = bool(account.is_paper)

    mode_label = "Paper" if is_paper else "Live"
    display_label = f"{acct_asset_class.value.title()} \u00b7 {mode_label}"

    return ExecutionVenue(
        exchange=exchange,
        asset_class=acct_asset_class,
        paper_mode_type=paper_mode_type,
        is_paper=is_paper,
        trading_account_id=account.id,
        display_label=display_label,
    )


async def get_user_asset_classes(
    user_id: str,
    db: AsyncSession,
) -> list[AssetClass]:
    """Return de-duplicated list of asset classes for a user's active accounts.

    Uses ``EXCHANGE_ASSET_CLASSES`` so multi-asset exchanges (e.g. Alpaca
    which supports both stocks and crypto) correctly surface all their
    capabilities instead of returning only a single hardcoded default.
    """
    result = await db.execute(
        select(TradingAccount)
        .where(
            TradingAccount.user_id == user_id,
            TradingAccount.is_active == True,  # noqa: E712
        )
    )
    accounts = result.scalars().all()
    seen: set[str] = set()
    classes: list[AssetClass] = []
    for a in accounts:
        try:
            exchange = Exchange((a.exchange or "").lower())
            supported = EXCHANGE_ASSET_CLASSES.get(exchange, set())
        except ValueError:
            supported = set()
        if not supported:
            # Fallback: use the stored asset_class on the account row
            supported = {AssetClass(getattr(a, "asset_class", None) or "stocks")}
        for ac in supported:
            if ac.value not in seen:
                seen.add(ac.value)
                classes.append(ac)
    return classes

