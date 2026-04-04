"""
src/agents/sentiment_agent.py — Market sentiment analysis for trading signals.

Analyzes news headlines, earnings cycles, and market sentiment indices to provide
context for trading decisions. Results are cached for 30 minutes per symbol.

Depth of analysis adapts to trader class:
  - Novices: simplified sentiment + plain English summaries
  - Intermediate/Pro: detailed sentiment with technical context + full headlines
  - Crypto natives: adds Fear & Greed Index for crypto assets
"""

import asyncio
import csv
import io
import json
import logging
from datetime import datetime, timedelta, timezone

import anthropic
import httpx

from config import settings
from src.agents.shared_memory import SharedContext
from src.integrations.alpaca_rate_limiter import alpaca_limiter
from src.market_context import Exchange, MarketContext

logger = logging.getLogger(__name__)

# Module-level cache: symbol -> (result_dict, cached_at_timestamp)
_sentiment_cache: dict[str, tuple[dict, datetime]] = {}
CACHE_TTL_SECONDS = 30 * 60  # 30 minutes
_insider_cache: dict[str, tuple[dict, datetime]] = {}
INSIDER_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours


class SentimentAgent:
    """Analyzes market sentiment for a given symbol.

    Fetches news, earnings data, and market indicators, then synthesizes
    into sentiment scores and summaries tailored to trader experience level.
    """

    def __init__(self, alpaca_api_key: str = None, alpaca_base_url: str = None):
        """Initialize sentiment agent with API credentials.
        
        Args:
            alpaca_api_key: Alpaca API key (defaults to environment)
            alpaca_base_url: Alpaca base URL (defaults to paper trading)
        """
        self.alpaca_api_key = alpaca_api_key
        self.alpaca_base_url = alpaca_base_url or "https://paper-api.alpaca.markets"
        self.claude_client = anthropic.AsyncAnthropic()

    async def get_sentiment(self, symbol: str, ctx: SharedContext) -> dict:
        """Get market sentiment for a symbol, adapted to trader class.

        Returns cached result if available and fresh. Otherwise fetches new data.

        Args:
            symbol: Trading pair (e.g., "AAPL", "BTC/USD")
            ctx: SharedContext with trader_class and user preferences

        Returns:
            dict with keys:
              - sentiment_score: "very_bearish"|"bearish"|"neutral"|"bullish"|"very_bullish"
              - sentiment_summary: Technical analysis (1-2 sentences)
              - sentiment_summary_simple: Plain English (1 sentence)
              - earnings_alert: bool (True if earnings within 7 days)
              - earnings_date: ISO date string or None
              - risk_flag: str describing major risk event or None
              - headlines: list of 3 most recent headlines
              - fear_greed_index: int 0-100 or None
        """
        # Check cache
        if symbol in _sentiment_cache:
            cached_result, cached_at = _sentiment_cache[symbol]
            if datetime.utcnow() - cached_at < timedelta(seconds=CACHE_TTL_SECONDS):
                logger.debug(f"Sentiment cache hit for {symbol}")
                return cached_result

        # Cache miss - fetch new sentiment
        logger.debug(f"Sentiment cache miss for {symbol}, fetching fresh data")
        result = {
            "sentiment_score": "neutral",
            "sentiment_summary": "",
            "sentiment_summary_simple": "",
            "earnings_alert": False,
            "earnings_date": None,
            "risk_flag": None,
            "headlines": [],
            "fear_greed_index": None,
        }

        # 1. Fetch news (exchange-aware)
        try:
            news_items = await self.fetch_news(
                symbol, market_context=getattr(ctx, "market_context", None)
            )
            headlines = [
                (item.get("headline") or item.get("title") or "")
                for item in news_items[:10]
                if (item.get("headline") or item.get("title"))
            ]
            result["headlines"] = headlines[:3]
        except Exception as e:
            logger.warning(f"Failed to fetch news for {symbol}: {e}")
            return result  # Return neutral on failure, never crash

        # 2. Earnings calendar for stocks only
        is_crypto = "/" in symbol or symbol.upper() in ["BTC", "ETH", "SOL", "XRP"]
        if not is_crypto:
            try:
                earnings = await self._fetch_earnings(symbol)
                if earnings:
                    days_until = (earnings["date"] - datetime.utcnow().date()).days
                    if 0 <= days_until <= 7:
                        result["earnings_alert"] = True
                        result["earnings_date"] = earnings["date"].isoformat()
            except Exception as e:
                logger.debug(f"Failed to fetch earnings for {symbol}: {e}")

        # 3. Fear and Greed index for crypto_native class only
        if ctx.is_crypto_native() and is_crypto:
            try:
                result["fear_greed_index"] = await self._fetch_fear_greed()
            except Exception as e:
                logger.debug(f"Failed to fetch fear/greed index: {e}")

        # 4. Claude sentiment analysis - depth depends on trader_class
        if result["headlines"]:
            try:
                sentiment = await self._analyze_sentiment_with_claude(
                    symbol, result["headlines"], ctx
                )
                result.update(sentiment)
            except Exception as e:
                logger.warning(f"Failed to analyze sentiment with Claude for {symbol}: {e}")

        # Cache the result
        _sentiment_cache[symbol] = (result, datetime.utcnow())

        return result

    async def fetch_news(
        self,
        symbol: str,
        market_context: MarketContext | None = None,
    ) -> list[dict]:
        exchange = market_context.exchange if market_context else Exchange.ALPACA

        if exchange == Exchange.ALPACA:
            return await self._fetch_alpaca_news(symbol)

        if exchange in (Exchange.COINBASE, Exchange.BINANCE):
            return await self._fetch_coingecko_news(symbol)

        # No news source for OANDA yet.
        return []

    async def _fetch_coingecko_news(self, symbol: str) -> list[dict]:
        """
        Interim crypto news via CoinGecko /news endpoint (free, no API key needed).
        Replace with LunarCrush in Phase 11.
        """
        url = "https://api.coingecko.com/api/v3/news"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                articles = data.get("data", []) or []
                return [
                    {"title": a.get("title", "") or "", "url": a.get("url", "") or "", "source": "coingecko"}
                    for a in articles[:10]
                ]
        except Exception as e:
            logger.warning("CoinGecko news fetch failed for %s: %s", symbol, e)
            return []

    async def _fetch_alpaca_news(self, symbol: str) -> list[dict]:
        """Fetch recent news headlines from Alpaca API.

        Args:
            symbol: Trading pair

        Returns:
            List of news items with headline, author, created_at, url
        """
        # Normalize symbol for Alpaca API
        alpaca_symbol = symbol.replace("/", "")  # BTC/USD -> BTCUSD

        api_key = self.alpaca_api_key or settings.alpaca_api_key
        api_secret = getattr(settings, "alpaca_api_secret", None)
        if not api_key:
            logger.warning(f"No Alpaca API key available — skipping news fetch for {symbol}")
            return []

        # News lives on the data subdomain, not the trading API
        url = "https://data.alpaca.markets/v1beta1/news"
        headers = {
            "APCA-API-KEY-ID": api_key,
            "Content-Type": "application/json",
        }
        if api_secret:
            headers["APCA-API-SECRET-KEY"] = api_secret
        params = {"symbols": alpaca_symbol, "limit": 10}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await alpaca_limiter.acquire()
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                return data.get("news", [])
        except Exception as e:
            logger.error(f"Alpaca news API error for {symbol}: {e}")
            raise

    async def _fetch_earnings(self, symbol: str) -> dict | None:
        """Fetch next earnings date for a stock.

        Args:
            symbol: Stock symbol (e.g., "AAPL")

        Returns:
            dict with "date" (datetime.date) or None if not found
        """
        api_key = settings.alpha_vantage_api_key
        if not api_key:
            logger.debug("No Alpha Vantage API key configured — skipping earnings lookup for %s", symbol)
            return None

        url = "https://www.alphavantage.co/query"
        params = {
            "function": "EARNINGS_CALENDAR",
            "symbol": symbol.upper().strip(),
            "horizon": "3month",
            "apikey": api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                text = response.text.strip()

            if not text or "reportDate" not in text:
                logger.debug("No earnings CSV returned for %s", symbol)
                return None

            rows = list(csv.DictReader(io.StringIO(text)))
            if not rows:
                return None

            today = datetime.now(timezone.utc).date()
            upcoming_dates = []
            for row in rows:
                row_symbol = (row.get("symbol") or "").upper().strip()
                report_date = (row.get("reportDate") or "").strip()
                if row_symbol != symbol.upper().strip() or not report_date:
                    continue
                try:
                    parsed = datetime.strptime(report_date, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if parsed >= today:
                    upcoming_dates.append(parsed)

            if not upcoming_dates:
                return None

            return {"date": min(upcoming_dates)}
        except Exception as e:
            logger.error("Earnings API error for %s: %s", symbol, e)
            return None

    async def _fetch_fear_greed(self) -> int | None:
        """Fetch current crypto Fear & Greed Index.

        Calls https://api.alternative.me/fng/?limit=1

        Returns:
            int 0-100 (0=extreme fear, 100=extreme greed) or None on error
        """
        url = "https://api.alternative.me/fng/?limit=1"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                # Extract value from first result
                if data.get("data"):
                    value_str = data["data"][0].get("value")
                    return int(value_str) if value_str else None
        except Exception as e:
            logger.error(f"Fear & Greed API error: {e}")
            raise

    async def _fetch_insider_activity(self, symbol: str) -> dict:
        """Phase-2 scaffold for insider Form 4 enrichment.

        Returns a normalized, cached shape so Signal Stack can start consuming
        insider context later without another refactor.
        """
        cached = _insider_cache.get(symbol)
        now = datetime.utcnow()
        if cached and (now - cached[1]).total_seconds() < INSIDER_CACHE_TTL_SECONDS:
            return cached[0]

        normalized = {
            "insider_signal": "neutral",
            "insider_summary": "No insider filing signal applied yet.",
            "recent_insider_buy_value_usd": None,
            "recent_insider_buy_count": 0,
        }

        # Phase 2: query SEC EDGAR Form 4 data here, normalize, then cache.
        _insider_cache[symbol] = (normalized, now)
        return normalized

    async def _analyze_sentiment_with_claude(
        self, symbol: str, headlines: list[str], ctx: SharedContext
    ) -> dict:
        """Analyze sentiment of headlines using Claude.

        Prompt depth varies by trader class:
          - Pro/Intermediate: Full technical analysis with risk flags
          - Novice/Crypto Native: Simplified sentiment with plain English

        Args:
            symbol: Trading pair
            headlines: List of news headlines
            ctx: SharedContext with trader_class

        Returns:
            dict with sentiment_score, sentiment_summary, sentiment_summary_simple, risk_flag
        """
        sentiment_result = {
            "sentiment_score": "neutral",
            "sentiment_summary": "",
            "sentiment_summary_simple": "",
            "risk_flag": None,
        }

        if not headlines:
            return sentiment_result

        # Build prompt based on trader class
        if ctx.is_pro() or ctx.is_intermediate():
            # Full technical analysis for experienced traders
            headline_text = "\n".join(f"- {h}" for h in headlines)
            prompt = f"""Analyse these headlines about {symbol}:
{headline_text}
Return JSON only:
{{
  "sentiment_score": "very_bearish|bearish|neutral|bullish|very_bullish",
  "sentiment_summary": "2 sentences - specific market implications and risk factors",
  "sentiment_summary_simple": "1 plain English sentence for a beginner",
  "risk_flag": "describe any major risk event or null"
}}"""
        else:
            # Simplified analysis for novices
            headline_text = "\n".join(f"- {h}" for h in headlines[:5])
            prompt = f"""Look at these news headlines about {symbol}:
{headline_text}
In plain English with no financial jargon, is the news mostly good,
bad, or mixed for this company right now?
Return JSON only:
{{
  "sentiment_score": "bearish|neutral|bullish",
  "sentiment_summary": "1 short technical sentence",
  "sentiment_summary_simple": "1 sentence as if explaining to someone who has never invested before",
  "risk_flag": null
}}"""

        try:
            response = await self.claude_client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            analysis = json.loads(response.content[0].text)
            sentiment_result.update(analysis)
        except Exception as e:
            logger.error(f"Claude sentiment analysis failed for {symbol}: {e}")

        return sentiment_result


async def invalidate_sentiment_cache(symbol: str | None = None) -> None:
    """Invalidate sentiment cache for a symbol or all symbols.

    Args:
        symbol: Symbol to invalidate, or None to clear entire cache
    """
    global _sentiment_cache
    if symbol:
        if symbol in _sentiment_cache:
            del _sentiment_cache[symbol]
            logger.debug(f"Invalidated sentiment cache for {symbol}")
    else:
        _sentiment_cache.clear()
        logger.debug("Invalidated entire sentiment cache")
