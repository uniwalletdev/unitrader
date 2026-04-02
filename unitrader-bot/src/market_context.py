from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import TradingAccount


class Exchange(str, Enum):
    ALPACA = "alpaca"
    COINBASE = "coinbase"
    BINANCE = "binance"
    OANDA = "oanda"


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
    Exchange.OANDA: {AssetClass.FOREX},
}


CRYPTO_BASES = {
    "BTC",
    "ETH",
    "SOL",
    "DOGE",
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

