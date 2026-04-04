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
    if market_context is None:
        return await _score_stocks_alpaca(STOCK_UNIVERSE)
    if market_context.exchange.value == "alpaca":
        return await _score_stocks_alpaca(STOCK_UNIVERSE)
    elif market_context.exchange.value == "coinbase":
        return await _score_crypto_coinbase(CRYPTO_UNIVERSE)
    elif market_context.exchange.value == "binance":
        return await _score_crypto_binance(
            [s.replace("-USD", "USDT") for s in CRYPTO_UNIVERSE]
        )
    elif market_context.exchange.value == "kraken":
        return await _score_crypto_kraken(KRAKEN_UNIVERSE)
    else:
        return []


async def _score_stocks_alpaca(universe: list[str], top_n: int = 10) -> list[str]:
    """Quickly score a stock universe using only raw market data (no Claude).

    Fetches price_change_pct and volume sequentially with a short delay between
    requests to avoid Alpaca rate limits (429). Computes a simple momentum
    score and returns the top_n tickers sorted by score descending.

    Score = abs(price_change_pct) * 0.6 + volume_percentile * 0.4
    """
    from src.integrations.market_data import fetch_market_data

    symbols = list(universe or [])
    raw: list[tuple[str, float, float]] = []

    for symbol in symbols:
        try:
            data = await fetch_market_data(symbol, "alpaca")
            change_pct = abs(float(data.get("price_change_pct") or 0))
            volume = float(data.get("volume") or 0)
            raw.append((symbol, change_pct, volume))
        except Exception as exc:
            logger.warning("score_universe: skipping %s — %s", symbol, exc)
        await asyncio.sleep(0.15)

    # Normalise volume to 0–1 percentile across the universe
    volumes = [r[2] for r in raw]
    max_vol = max(volumes) if max(volumes) > 0 else 1.0

    scored = []
    for sym, change_pct, volume in raw:
        vol_pct = volume / max_vol
        score = change_pct * 0.6 + vol_pct * 0.4
        scored.append((sym, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = [sym for sym, _ in scored[:top_n]]

    logger.info("score_universe(alpaca): top %d from %d — %s", top_n, len(symbols), top)
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
