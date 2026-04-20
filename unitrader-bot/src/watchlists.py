"""
src/watchlists.py — Symbol universe and pre-scorer for dynamic AI watchlist.

Instead of a fixed 5–10 symbol list every user sees, the backend scans a
large private universe, does a fast momentum pre-filter, then runs full AI
analysis on only the top candidates. Users always see the best opportunities
for that day, not a static predefined list.
"""

from __future__ import annotations

import asyncio
import logging
logger = logging.getLogger(__name__)

# Module-level universes for scoring (must exist before score_universe and helpers).
STOCK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN",
    "GOOGL", "META", "AMD", "NFLX", "JPM",
    "V", "MA", "UNH", "JNJ", "WMT",
    "BAC", "GS", "CRM", "ADBE", "INTC",
]

CRYPTO_UNIVERSE = [
    "BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "ADA-USD",
    "AVAX-USD", "LINK-USD", "MATIC-USD", "DOT-USD", "UNI-USD",
]

KRAKEN_UNIVERSE = [
    "XBTUSD",
    "ETHUSD",
    "SOLUSD",
    "XDGUSD",
    "ADAUSD",
    "AVAXUSD",
    "LINKUSD",
    "DOTUSD",
    "UNIUSD",
    "ATOMUSD",
]

# ─────────────────────────────────────────────
# Full scanning universe (never shown to users directly)
# ─────────────────────────────────────────────

SYMBOL_UNIVERSE: dict[str, list[str]] = {
    "alpaca": list(STOCK_UNIVERSE),
    "binance": [
        # Layer 1
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT",
        "AVAXUSDT", "DOTUSDT", "NEARUSDT", "ATOMUSDT", "ALGOUSDT",
        # Layer 2 / DeFi
        "MATICUSDT", "LINKUSDT", "UNIUSDT", "ARBUSDT", "OPUSDT",
        # High-volume altcoins
        "XRPUSDT", "DOGEUSDT", "LTCUSDT", "BNBUSDT", "APTUSDT",
        "INJUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT",
    ],
    "coinbase": list(CRYPTO_UNIVERSE),
    "kraken": list(KRAKEN_UNIVERSE),
    "oanda": [
        "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD",
        "NZD_USD", "USD_CHF", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    ],
}

# ─────────────────────────────────────────────
# Human-readable labels (ticker → name)
# Used by symbol search endpoint
# ─────────────────────────────────────────────

SYMBOL_LABELS: dict[str, str] = {
    # Stocks
    "AAPL": "Apple Inc", "MSFT": "Microsoft Corp", "NVDA": "NVIDIA Corp",
    "TSLA": "Tesla Inc", "AMZN": "Amazon.com", "GOOGL": "Alphabet / Google",
    "META": "Meta Platforms", "NFLX": "Netflix", "AMD": "Advanced Micro Devices",
    "INTC": "Intel Corp", "CRM": "Salesforce", "ORCL": "Oracle Corp",
    "ADBE": "Adobe Inc", "QCOM": "Qualcomm",
    "JPM": "JPMorgan Chase", "V": "Visa Inc", "MA": "Mastercard",
    "BAC": "Bank of America", "GS": "Goldman Sachs", "MS": "Morgan Stanley",
    "BLK": "BlackRock",
    "JNJ": "Johnson & Johnson", "UNH": "UnitedHealth Group", "PFE": "Pfizer",
    "ABBV": "AbbVie", "MRK": "Merck & Co",
    "KO": "Coca-Cola", "PEP": "PepsiCo", "WMT": "Walmart", "COST": "Costco",
    "TGT": "Target Corp",
    "XOM": "Exxon Mobil", "CVX": "Chevron", "CAT": "Caterpillar",
    "DE": "Deere & Company", "BA": "Boeing", "GE": "GE Aerospace", "HON": "Honeywell",
    # ETFs
    "SPY": "S&P 500 ETF (SPY)", "QQQ": "Nasdaq 100 ETF (QQQ)",
    "VOO": "Vanguard S&P 500 (VOO)", "IWM": "Russell 2000 ETF (IWM)",
    "DIA": "Dow Jones ETF (DIA)", "XLF": "Financials ETF",
    "XLK": "Technology ETF", "XLE": "Energy ETF", "XLV": "Healthcare ETF",
    "XLI": "Industrials ETF", "XLY": "Consumer Discretionary ETF",
    "ARKK": "ARK Innovation ETF",
    # Crypto (Binance)
    "BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum", "SOLUSDT": "Solana",
    "BNBUSDT": "BNB (Binance Coin)", "ADAUSDT": "Cardano",
    "AVAXUSDT": "Avalanche", "DOTUSDT": "Polkadot", "NEARUSDT": "NEAR Protocol",
    "ATOMUSDT": "Cosmos", "ALGOUSDT": "Algorand",
    "MATICUSDT": "Polygon (MATIC)", "LINKUSDT": "Chainlink",
    "UNIUSDT": "Uniswap", "ARBUSDT": "Arbitrum", "OPUSDT": "Optimism",
    "XRPUSDT": "XRP (Ripple)", "DOGEUSDT": "Dogecoin",
    "LTCUSDT": "Litecoin", "APTUSDT": "Aptos", "INJUSDT": "Injective",
    "SUIUSDT": "Sui", "SEIUSDT": "Sei Network", "TIAUSDT": "Celestia",
    # Crypto (Coinbase)
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "ADA-USD": "Cardano", "AVAX-USD": "Avalanche", "DOT-USD": "Polkadot",
    "LINK-USD": "Chainlink", "MATIC-USD": "Polygon", "DOGE-USD": "Dogecoin",
    "LTC-USD": "Litecoin", "NEAR-USD": "NEAR Protocol", "APT-USD": "Aptos",
    "OP-USD": "Optimism", "INJ-USD": "Injective", "XRP-USD": "XRP (Ripple)",
    # Crypto (Kraken)
    "XBTUSD": "Bitcoin", "ETHUSD": "Ethereum", "SOLUSD": "Solana",
    "XDGUSD": "Dogecoin", "ADAUSD": "Cardano", "AVAXUSD": "Avalanche",
    "LINKUSD": "Chainlink", "DOTUSD": "Polkadot", "UNIUSD": "Uniswap",
    "ATOMUSD": "Cosmos",
    # Forex (OANDA)
    "EUR_USD": "Euro / US Dollar", "GBP_USD": "British Pound / US Dollar",
    "USD_JPY": "US Dollar / Japanese Yen", "AUD_USD": "Australian Dollar / USD",
    "USD_CAD": "US Dollar / Canadian Dollar", "NZD_USD": "NZ Dollar / USD",
    "USD_CHF": "US Dollar / Swiss Franc", "EUR_GBP": "Euro / British Pound",
    "EUR_JPY": "Euro / Japanese Yen", "GBP_JPY": "British Pound / Japanese Yen",
}


# ─────────────────────────────────────────────
# Fast momentum pre-scorer
# ─────────────────────────────────────────────

async def score_universe(market_context=None) -> list[str]:
    """Dispatch to the exchange adapter's pre-scorer via the registry.

    Falls back to Alpaca stock scoring when no market_context is provided.
    """
    import src.exchanges  # noqa: F401 — populate registry
    from src.exchanges.registry import get_optional

    if market_context is None:
        # Default to Alpaca stocks (backwards-compat)
        return await _score_stocks_alpaca(STOCK_UNIVERSE)

    exchange_id = market_context.exchange.value
    spec = get_optional(exchange_id)
    if spec is not None and spec.score_universe is not None:
        return await spec.score_universe()
    return []


async def _score_stocks_alpaca(universe: list[str], top_n: int = 10) -> list[str]:
    """Momentum pre-score using historical closes from configured stock provider."""
    from src.integrations.data_providers.factory import get_stock_history_provider

    provider = get_stock_history_provider()
    scores: dict[str, float] = {}

    for symbol in universe or []:
        try:
            closes = await provider.get_historical_closes(symbol, days=60)
            if not closes or len(closes) < 20:
                continue

            recent_return = (closes[-1] - closes[-10]) / closes[-10]
            long_return = (closes[-1] - closes[0]) / closes[0]
            volatility = (max(closes[-20:]) - min(closes[-20:])) / closes[-1]

            score = (recent_return * 0.6) + (long_return * 0.3) - (volatility * 0.1)
            scores[symbol] = score

        except Exception as e:
            logger.warning("score_universe: skipping %s — %s", symbol, e)
            continue

    ranked = sorted(scores, key=scores.get, reverse=True)
    top = ranked[:top_n]
    logger.info(
        "score_universe(alpaca): top %d from %d — %s",
        top_n,
        len(scores),
        top,
    )
    return top


async def _score_crypto_coinbase(universe: list[str]) -> list[str]:
    # TODO Phase 11: score by Signal Convergence Engine
    # For now return full list — Apex will rank from these
    return universe


async def _score_crypto_binance(universe: list[str]) -> list[str]:
    return universe


async def _score_crypto_kraken(universe: list[str]) -> list[str]:
    """
    Score Kraken crypto pairs using public ticker data.
    No API key required — Kraken public endpoints are open.
    """
    import httpx

    from src.integrations.alpaca_rate_limiter import kraken_limiter

    scored: list[tuple[str, float]] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for symbol in universe:
            try:
                await kraken_limiter.acquire()
                resp = await client.get(
                    "https://api.kraken.com/0/public/Ticker",
                    params={"pair": symbol},
                )
                resp.raise_for_status()
                data = resp.json().get("result", {})
                if not data:
                    continue
                pair_data = list(data.values())[0]
                volume_24h = float(pair_data["v"][1])
                high_24 = float(pair_data["h"][1])
                low_24 = float(pair_data["l"][1])
                price_change = abs(high_24 - low_24) / low_24 * 100 if low_24 else 0.0
                score = volume_24h * price_change
                scored.append((symbol, score))
            except Exception as exc:
                logger.warning("score_universe: skipping %s — %s", symbol, exc)
                continue
    scored.sort(key=lambda x: x[1], reverse=True)
    return [s[0] for s in scored[:8]]


def symbol_search(query: str, exchange: str | None = None, limit: int = 8) -> list[dict]:
    """Fuzzy search symbols by ticker or company name.

    Returns up to `limit` results of the form:
        {"symbol": str, "label": str, "exchange": str}
    """
    q = query.strip().lower()
    if not q:
        return []

    results: list[dict] = []
    seen: set[str] = set()

    # Decide which exchanges to search
    if exchange:
        exchanges = [exchange.lower()]
    else:
        exchanges = list(SYMBOL_UNIVERSE.keys())

    for ex in exchanges:
        for sym in SYMBOL_UNIVERSE[ex]:
            if sym in seen:
                continue
            label = SYMBOL_LABELS.get(sym, sym)
            if q in sym.lower() or q in label.lower():
                results.append({"symbol": sym, "label": label, "exchange": ex})
                seen.add(sym)
            if len(results) >= limit * 2:
                break
        if len(results) >= limit * 2:
            break

    return results[:limit]
